"""
Smart Matcher - 智能模板和形状库匹配服务
Combines keyword filtering with LLM-based evaluation for better matching.

Import boundary (refactor):
    :class:`SmartMatcher` is pure Python. It does **not** import agno.
    Any LLM call is invoked through :func:`_complete`, a tiny adapter
    that only assumes the caller passed an object supporting either

    - ``model.complete(prompt_str) -> str`` (the recommended protocol),
      or
    - ``model.response([msg])`` returning an object with ``.content``
      (legacy agno-style). In that case we construct a minimal duck-typed
      message with ``role`` / ``content`` attributes so the agno model
      can still be injected by :mod:`apps.agent_os`.

    The app / MCP layer is responsible for bridging whichever concrete
    LLM SDK it uses into one of those shapes.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from .library_cache import get_library_cache
from ..context.instruction_loader import get_instruction_loader


class _UserMessage:
    """Minimal duck-typed message compatible with agno's model.response().

    Kept local so this module never needs to ``import agno``.
    """

    __slots__ = ("role", "content")

    def __init__(self, content: str):
        self.role = "user"
        self.content = content


def _complete(model: Any, prompt: str) -> str:
    """Call the injected LLM and return the text response.

    Works with both a simple callable-style model (``model.complete(str)``)
    and the agno-style ``model.response([msg]).content`` protocol. Raises
    a descriptive error when neither shape is supported.
    """
    if model is None:
        raise RuntimeError(
            "SmartMatcher requires an LLM model. Inject one via "
            "PromptTools.set_model() or SmartMatcher.smart_match(model=...)."
        )
    if hasattr(model, "complete"):
        return str(model.complete(prompt))
    if hasattr(model, "response"):
        response = model.response([_UserMessage(prompt)])
        return str(getattr(response, "content", response))
    raise TypeError(
        f"Unsupported LLM model of type {type(model).__name__}: expected "
        "either a .complete(prompt) -> str or a .response([msg]) -> obj "
        "with .content callable."
    )


class SmartMatcher:
    """智能匹配器 - 用于模板和形状库的智能匹配"""
    
    def __init__(self, template_library_path: str = "assets/indexes/template_library.json",
                 stencil_library_path: str = "assets/indexes/stencil_library.json",
                 auto_load: bool = False,
                 use_cache: bool = True):
        """
        初始化智能匹配器
        
        Args:
            template_library_path: 完整版模板库JSON文件路径（用于LLM评估）
            stencil_library_path: 完整版形状库JSON文件路径（用于LLM评估）
            auto_load: 是否自动加载库文件（默认False，按需加载）
            use_cache: 是否使用缓存（默认True）
        """
        # Use absolute paths if needed
        if not os.path.isabs(template_library_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            template_library_path = os.path.join(base_dir, template_library_path)
        if not os.path.isabs(stencil_library_path):
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            stencil_library_path = os.path.join(base_dir, stencil_library_path)
        
        # 完整版路径（用于步骤3 LLM评估）
        self.template_library_path = template_library_path
        self.stencil_library_path = stencil_library_path
        
        # 精简版路径（用于步骤2 关键词筛选）
        self.template_library_lite_path = template_library_path.replace('.json', '_lite.json')
        self.stencil_library_lite_path = stencil_library_path.replace('.json', '_lite.json')
        
        # 缓存配置
        self.use_cache = use_cache
        self._cache = get_library_cache() if use_cache else None
        
        # 延迟加载：只有在需要时才加载
        self._templates_lite = None  # 精简版用于关键词筛选
        self._stencils_lite = None   # 精简版用于关键词筛选
        self._templates_full = None  # 完整版用于LLM评估
        self._stencils_full = None   # 完整版用于LLM评估
        
        # 指令加载器（用于加载提示词模板）
        self.instruction_loader = get_instruction_loader()
        
        # 可选的自动加载
        if auto_load:
            self._load_lite_libraries()
    
    @property
    def templates_lite(self) -> Dict[str, Any]:
        """延迟加载精简版模板库（用于关键词筛选）"""
        if self._templates_lite is None:
            # 优先使用精简版
            if os.path.exists(self.template_library_lite_path):
                self._templates_lite = self._load_json(self.template_library_lite_path, lite=True)
                if not self.use_cache:  # 缓存会自动打印，避免重复
                    print(f"✓ 已加载精简版模板库 {len(self._templates_lite)} 个")
            else:
                print(f"⚠ 精简版不存在，使用完整版: {self.template_library_lite_path}")
                self._templates_lite = self._load_json(self.template_library_path, lite=False)
                if not self.use_cache:
                    print(f"✓ 已加载 {len(self._templates_lite)} 个模板（完整版）")
        return self._templates_lite
    
    @property
    def stencils_lite(self) -> Dict[str, Any]:
        """延迟加载精简版形状库（用于关键词筛选）"""
        if self._stencils_lite is None:
            # 优先使用精简版
            if os.path.exists(self.stencil_library_lite_path):
                self._stencils_lite = self._load_json(self.stencil_library_lite_path, lite=True)
                if not self.use_cache:
                    print(f"✓ 已加载精简版形状库 {len(self._stencils_lite)} 个")
            else:
                print(f"⚠ 精简版不存在，使用完整版: {self.stencil_library_lite_path}")
                self._stencils_lite = self._load_json(self.stencil_library_path, lite=False)
                if not self.use_cache:
                    print(f"✓ 已加载 {len(self._stencils_lite)} 个形状库（完整版）")
        return self._stencils_lite
    
    @property
    def templates_full(self) -> Dict[str, Any]:
        """延迟加载完整版模板库（用于LLM评估）"""
        if self._templates_full is None:
            self._templates_full = self._load_json(self.template_library_path, lite=False)
            if not self.use_cache:
                print(f"✓ 已加载完整版模板库 {len(self._templates_full)} 个")
        return self._templates_full
    
    @property
    def stencils_full(self) -> Dict[str, Any]:
        """延迟加载完整版形状库（用于LLM评估）"""
        if self._stencils_full is None:
            self._stencils_full = self._load_json(self.stencil_library_path, lite=False)
            if not self.use_cache:
                print(f"✓ 已加载完整版形状库 {len(self._stencils_full)} 个")
        return self._stencils_full
    
    def _load_lite_libraries(self):
        """手动加载精简版库文件（用于关键词筛选）"""
        _ = self.templates_lite  # 触发延迟加载
        _ = self.stencils_lite   # 触发延迟加载
    
    def _load_full_libraries(self):
        """手动加载完整版库文件（用于LLM评估）"""
        _ = self.templates_full  # 触发延迟加载
        _ = self.stencils_full   # 触发延迟加载
    
    def _load_json(self, path: str, lite: bool = False) -> Dict[str, Any]:
        """
        加载JSON文件（带缓存支持）
        
        Args:
            path: 文件路径
            lite: 是否是精简版（用于缓存键）
            
        Returns:
            加载的数据字典
        """
        # 如果使用缓存，尝试从缓存加载
        if self.use_cache and self._cache:
            return self._cache.load_library(path, lite=lite)
        
        # 否则直接加载文件
        if not os.path.exists(path):
            print(f"⚠ 警告：文件不存在 {path}")
            return {}
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"❌ 加载失败 {path}: {e}")
            return {}
    
    def extract_english_keywords(self, chinese_text: str, model: Any) -> Dict[str, Any]:
        """
        从中文文本中提取英文关键词和需求分析
        
        Args:
            chinese_text: 中文输入文本
            model: OpenAI模型实例
            
        Returns:
            包含关键词和需求分析的字典:
            {
                'keywords': List[str],  # 英文关键词列表
                'analysis': Dict[str, Any]  # 完整需求分析
            }
        """
        # 从动态指令模板加载提示词
        prompt_template = self.instruction_loader.load_template('keyword_extraction')
        prompt = prompt_template.replace('{chinese_text}', chinese_text)
        
        try:
            result_text = _complete(model, prompt).strip()

            # Parse JSON response
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            analysis = json.loads(result_text)
            
            # Extract keywords list from keywords field
            keywords_str = analysis.get('keywords', '')
            keywords = [kw.strip() for kw in keywords_str.split(',')]
            keywords = [kw for kw in keywords if kw and len(kw) > 1]
            
            # Log extracted information
            print(f"✓ 提取的英文关键词: {', '.join(keywords)}")
            print(f"✓ 图表类型: {analysis.get('chart_type', '未知')}")
            print(f"✓ 复杂度: {analysis.get('complexity', '未知')}")
            print(f"✓ 预估形状数: {analysis.get('estimated_shapes', '未知')}")
            print(f"✓ 架构模式: {analysis.get('architecture_pattern', '未知')}")
            
            # Return complete result
            return {
                'keywords': keywords,
                'analysis': analysis
            }
        except Exception as e:
            print(f"❌ 关键词提取失败: {e}")
            # Fallback to basic extraction
            return {
                'keywords': self._fallback_keyword_extraction(chinese_text),
                'analysis': {}
            }
    
    def _fallback_keyword_extraction(self, text: str) -> List[str]:
        """备用关键词提取（不使用LLM）"""
        keyword_map = {
            '流程图': ['flowchart', 'process', 'workflow'],
            '架构图': ['architecture', 'structure'],
            '架构': ['architecture', 'structure'],
            '组织图': ['organization', 'org chart', 'hierarchy'],
            '组织': ['organization', 'org'],
            '网络图': ['network', 'topology'],
            '网络': ['network'],
            '云': ['cloud', 'Azure', 'AWS', 'GCP'],
            '时序图': ['sequence', 'timeline'],
            '时序': ['sequence'],
            '数据': ['data', 'database'],
            '用户': ['user', 'login'],
            '系统': ['system'],
            '基础设施': ['infrastructure'],
        }
        
        keywords = []
        for chinese_key, english_terms in keyword_map.items():
            if chinese_key in text:
                keywords.extend(english_terms)
        
        return list(set(keywords))[:8]
    
    def filter_by_keywords(self, keywords: List[str], 
                          search_type: str = "template",
                          min_match_score: float = 0.5) -> List[Dict[str, Any]]:
        """
        通过关键词筛选模板或形状库（步骤2 - 使用精简版）
        
        Args:
            keywords: 英文关键词列表
            search_type: "template" 或 "stencil"
            min_match_score: 最小匹配分数（0-1）
            
        Returns:
            筛选后的结果列表，包含匹配分数
        """
        # 使用精简版进行快速筛选
        library = self.templates_lite if search_type == "template" else self.stencils_lite
        results = []
        
        for filename, item_data in library.items():
            score = self._calculate_keyword_score(item_data, keywords)
            
            if score >= min_match_score:
                result = {
                    'filename': filename,
                    'keyword_match_score': round(score, 2),
                    **item_data
                }
                results.append(result)
        
        # Sort by score
        results.sort(key=lambda x: x['keyword_match_score'], reverse=True)
        
        print(f"✓ 关键词筛选: 找到 {len(results)} 个匹配项 (最小分数: {min_match_score})")
        return results
    
    def filter_by_keywords_and_structure(self, 
                                        keywords: List[str],
                                        requirement_analysis: Dict[str, Any],
                                        search_type: str = "template",
                                        keyword_threshold: float = 0.2,
                                        structure_threshold: float = 0.3,
                                        keyword_weight: float = 0.4,
                                        structure_weight: float = 0.6) -> List[Dict[str, Any]]:
        """
        通过关键词+结构综合筛选模板或形状库（步骤2增强版 - 使用精简版）
        
        评分策略：
        - 加权平均：关键词分数 * 40% + 结构分数 * 60%
        - 双阈值过滤：关键词分数 >= keyword_threshold 且 结构分数 >= structure_threshold
        
        Args:
            keywords: 英文关键词列表
            requirement_analysis: 需求分析结果（包含结构特征）
            search_type: "template" 或 "stencil"
            keyword_threshold: 关键词最小阈值（0-1）
            structure_threshold: 结构最小阈值（0-1）
            keyword_weight: 关键词权重（默认0.4）
            structure_weight: 结构权重（默认0.6）
            
        Returns:
            筛选后的结果列表，包含关键词分数、结构分数和综合分数
        """
        # 使用精简版进行快速筛选
        library = self.templates_lite if search_type == "template" else self.stencils_lite
        results = []
        passed_count = 0
        failed_keyword = 0
        failed_structure = 0
        failed_both = 0
        
        for filename, item_data in library.items():
            # 1. 计算关键词分数
            keyword_score = self._calculate_keyword_score(item_data, keywords)
            
            # 2. 计算结构分数
            structure_score = self._calculate_structure_score(item_data, requirement_analysis)
            
            # 3. 双阈值过滤
            keyword_pass = keyword_score >= keyword_threshold
            structure_pass = structure_score >= structure_threshold
            
            # 统计未通过的原因
            if not keyword_pass and not structure_pass:
                failed_both += 1
            elif not keyword_pass:
                failed_keyword += 1
            elif not structure_pass:
                failed_structure += 1
            
            # 两者都要通过才能进入候选
            if keyword_pass and structure_pass:
                # 4. 加权组合得到最终分数
                final_score = keyword_score * keyword_weight + structure_score * structure_weight
                
                result = {
                    'filename': filename,
                    'keyword_match_score': round(keyword_score, 3),
                    'structure_match_score': round(structure_score, 3),
                    'combined_score': round(final_score, 3),
                    **item_data
                }
                results.append(result)
                passed_count += 1
        
        # 5. 按综合分数排序
        results.sort(key=lambda x: x['combined_score'], reverse=True)
        
        # 优化的日志输出
        print(f"✓ 关键词+结构筛选: 找到 {len(results)} 个匹配项")
        print(f"  - 通过双阈值: {passed_count} 个")
        print(f"  - 未通过（关键词不足）: {failed_keyword} 个")
        print(f"  - 未通过（结构不匹配）: {failed_structure} 个")
        print(f"  - 未通过（两者都不足）: {failed_both} 个")
        print(f"  - 关键词阈值: {keyword_threshold}, 结构阈值: {structure_threshold}")
        print(f"  - 权重配比: 关键词{keyword_weight*100:.0f}% + 结构{structure_weight*100:.0f}%")
        
        return results
    
    def _calculate_keyword_score(self, item_data: Dict[str, Any], 
                                 keywords: List[str]) -> float:
        """计算关键词匹配分数"""
        if not keywords:
            return 0.0
        
        # Build searchable text from item
        searchable_parts = [
            item_data.get('name', ''),
            ' '.join(item_data.get('keywords', [])),
            ' '.join(item_data.get('use_cases', [])),
            item_data.get('category', ''),
        ]
        
        # Add shape types for templates
        if 'shape_types' in item_data:
            searchable_parts.append(' '.join(item_data.get('shape_types', [])))
        
        # Add master names for stencils
        if 'master_names' in item_data:
            searchable_parts.append(' '.join(item_data.get('master_names', [])[:50]))
        
        searchable_text = ' '.join(searchable_parts).lower()
        
        # Calculate match score
        matches = 0
        for keyword in keywords:
            if keyword.lower() in searchable_text:
                matches += 1
        
        return matches / len(keywords) if keywords else 0.0
    
    def _topology_similarity(self, user_topology: str, template_topology: Dict[str, Any]) -> float:
        """
        计算拓扑结构相似度（基于相似度打分）
        
        Args:
            user_topology: 用户需求的拓扑类型（如：hierarchical_tree, linear_chain, network等）
            template_topology: 模板的拓扑模式字典（包含pattern_type等字段）
            
        Returns:
            相似度分数（0-1）
        """
        if not user_topology or not template_topology:
            return 0.0
        
        template_type = template_topology.get('pattern_type', '').lower()
        user_type = user_topology.lower()
        
        # 完全匹配
        if user_type == template_type:
            return 1.0
        
        # 相似拓扑映射（模糊匹配）
        topology_groups = {
            'hierarchical': ['hierarchical_tree', 'tree', 'hierarchy'],
            'linear': ['linear_chain', 'sequential', 'chain'],
            'network': ['network', 'mesh', 'graph'],
            'star': ['star', 'hub_spoke', 'radial'],
            'hybrid': ['hybrid', 'mixed', 'composite']
        }
        
        # 查找用户需求和模板的拓扑组
        user_group = None
        template_group = None
        for group_name, patterns in topology_groups.items():
            if any(pattern in user_type for pattern in patterns):
                user_group = group_name
            if any(pattern in template_type for pattern in patterns):
                template_group = group_name
        
        # 同组相似度高
        if user_group and template_group and user_group == template_group:
            return 0.8
        
        # 部分相似（如linear和hierarchical都是有序结构）
        compatible_pairs = [
            ('linear', 'hierarchical'),
            ('hierarchical', 'hybrid'),
            ('network', 'hybrid'),
            ('star', 'network')
        ]
        if user_group and template_group:
            for pair in compatible_pairs:
                if (user_group, template_group) == pair or (template_group, user_group) == pair:
                    return 0.4
        
        # 不匹配
        return 0.0
    
    def _layout_similarity(self, user_layout: str, template_layout: Dict[str, Any]) -> float:
        """
        计算布局模式相似度
        
        Args:
            user_layout: 用户需求的布局方向（如：vertical, horizontal, mixed）
            template_layout: 模板的布局模式字典（包含primary_direction等字段）
            
        Returns:
            相似度分数（0-1）
        """
        if not user_layout or not template_layout:
            return 0.0
        
        template_direction = template_layout.get('primary_direction', '').lower()
        user_dir = user_layout.lower()
        
        # 完全匹配
        if user_dir in template_direction or template_direction in user_dir:
            return 1.0
        
        # 方向映射
        direction_map = {
            'vertical': ['top_to_bottom', 'bottom_to_top', 'vertical'],
            'horizontal': ['left_to_right', 'right_to_left', 'horizontal'],
            'mixed': ['mixed', 'multi', 'free']
        }
        
        # 检查是否在同一组
        for direction, patterns in direction_map.items():
            user_match = user_dir in patterns or any(p in user_dir for p in patterns)
            template_match = any(p in template_direction for p in patterns)
            if user_match and template_match:
                return 1.0
        
        # mixed布局通用性强，给予中等分数
        if 'mixed' in user_dir or 'mixed' in template_direction:
            return 0.6
        
        # 不匹配（如需要vertical但模板是horizontal）
        return 0.2
    
    def _connection_similarity(self, user_connection: str, template_topology: Dict[str, Any]) -> float:
        """
        计算连接关系相似度
        
        Args:
            user_connection: 用户需求的连接类型（如：sequential, branching, bidirectional等）
            template_topology: 模板的拓扑模式字典（包含has_cycles等连接信息）
            
        Returns:
            相似度分数（0-1）
        """
        if not user_connection:
            return 0.5  # 未指定连接类型，给中等分
        
        if not template_topology:
            return 0.0
        
        user_conn = user_connection.lower()
        has_cycles = template_topology.get('has_cycles', False)
        pattern_type = template_topology.get('pattern_type', '').lower()
        
        # 连接类型与拓扑特征的映射
        connection_features = {
            'sequential': {'expects_cycles': False, 'compatible_patterns': ['linear_chain', 'hierarchical_tree']},
            'branching': {'expects_cycles': False, 'compatible_patterns': ['hierarchical_tree', 'hybrid']},
            'bidirectional': {'expects_cycles': True, 'compatible_patterns': ['network', 'hybrid']},
            'mesh': {'expects_cycles': True, 'compatible_patterns': ['network', 'hybrid']},
            'star_topology': {'expects_cycles': False, 'compatible_patterns': ['star', 'radial']}
        }
        
        if user_conn in connection_features:
            features = connection_features[user_conn]
            
            # 检查循环匹配
            cycle_match = (has_cycles == features['expects_cycles'])
            
            # 检查模式匹配
            pattern_match = any(p in pattern_type for p in features['compatible_patterns'])
            
            if cycle_match and pattern_match:
                return 1.0
            elif cycle_match or pattern_match:
                return 0.6
            else:
                return 0.2
        
        # 未知连接类型
        return 0.5
    
    def _scale_similarity(self, estimated_shapes: str, template_shapes: int) -> float:
        """
        计算规模相似度（基于形状数量）
        
        Args:
            estimated_shapes: 用户需求的预估形状数（如："8-12"或"20"）
            template_shapes: 模板的实际形状数
            
        Returns:
            相似度分数（0-1）
        """
        if not estimated_shapes or template_shapes is None:
            return 0.5  # 未指定规模，给中等分
        
        # 解析估算范围
        try:
            if '-' in str(estimated_shapes):
                # 范围格式："8-12"
                parts = estimated_shapes.split('-')
                min_shapes = int(parts[0].strip())
                max_shapes = int(parts[1].strip())
            else:
                # 单个数值
                min_shapes = max_shapes = int(estimated_shapes)
            
            # 计算中点
            mid_point = (min_shapes + max_shapes) / 2
            
            # 在范围内：满分
            if min_shapes <= template_shapes <= max_shapes:
                return 1.0
            
            # 在±20%范围内：高分
            if mid_point * 0.8 <= template_shapes <= mid_point * 1.2:
                return 0.9
            
            # 在±50%范围内：中等分
            if mid_point * 0.5 <= template_shapes <= mid_point * 1.5:
                return 0.6
            
            # 差异较大但可接受
            if mid_point * 0.3 <= template_shapes <= mid_point * 2:
                return 0.3
            
            # 差异过大
            return 0.1
            
        except (ValueError, AttributeError):
            # 解析失败
            return 0.5
    
    def _calculate_structure_score(self, item_data: Dict[str, Any], 
                                   requirement_analysis: Dict[str, Any]) -> float:
        """
        计算结构匹配分数（综合拓扑、布局、连接、规模四个维度）
        
        Args:
            item_data: 模板数据（来自 lite JSON）
            requirement_analysis: 需求分析结果（包含结构特征）
            
        Returns:
            结构匹配分数（0-1）
        """
        if not requirement_analysis:
            return 0.0
        
        # 提取用户需求的结构特征
        user_topology = requirement_analysis.get('topology_type', '')
        user_layout = requirement_analysis.get('layout_direction', '')
        user_connection = requirement_analysis.get('connection_type', '')
        estimated_shapes = requirement_analysis.get('estimated_shapes', '')
        
        # 提取模板的结构信息
        template_topology = item_data.get('topology_pattern', {})
        template_layout = item_data.get('layout_pattern', {})
        template_shapes = item_data.get('shape_total', 0)
        
        # 计算各维度相似度
        topology_score = self._topology_similarity(user_topology, template_topology)
        layout_score = self._layout_similarity(user_layout, template_layout)
        connection_score = self._connection_similarity(user_connection, template_topology)
        scale_score = self._scale_similarity(estimated_shapes, template_shapes)
        
        # 加权组合（拓扑30%、布局25%、连接25%、规模20%）
        structure_score = (
            topology_score * 0.30 +
            layout_score * 0.25 +
            connection_score * 0.25 +
            scale_score * 0.20
        )
        
        return structure_score
    
    def evaluate_with_llm(self, candidates: List[Dict[str, Any]], 
                         user_requirement: str,
                         requirement_analysis: Dict[str, Any],
                         model: Any,
                         top_k: int = 5,
                         search_type: str = "template",
                         confidence_score: float = 0.5) -> List[Dict[str, Any]]:
        """
        使用大模型对候选项进行评估和排序（步骤3 - 使用完整版详细信息）
        
        Args:
            candidates: 候选模板或形状库列表（来自关键词筛选）
            user_requirement: 用户需求描述
            requirement_analysis: 需求分析结果（包含图表类型、复杂度、预估形状数等）
            model: OpenAI模型实例
            top_k: 返回前k个结果
            search_type: "template" 或 "stencil"
            confidence_score: 输入置信度分数（用于动态权重）
            
        Returns:
            评估和排序后的结果列表（中文描述）
        """
        if not candidates:
            return []
        
        # Limit candidates to avoid token overflow
        candidates_for_eval = candidates[:20]
        print(f"✓ 限制候选项数量: {len(candidates)} → {len(candidates_for_eval)} 个（实际传给LLM）")
        
        # 从完整版库中加载详细信息
        full_library = self.templates_full if search_type == "template" else self.stencils_full
        
        # 用完整版数据丰富候选项信息
        enriched_candidates = []
        for candidate in candidates_for_eval:
            filename = candidate['filename']
            if filename in full_library:
                # 合并精简版和完整版数据
                enriched = {**candidate, **full_library[filename]}
                enriched_candidates.append(enriched)
            else:
                enriched_candidates.append(candidate)
        
        candidates_for_eval = enriched_candidates
        
        # Build prompt for LLM evaluation
        candidates_text = self._format_candidates_for_llm(candidates_for_eval)
        
        # 格式化需求分析为文本
        analysis_text = self._format_requirement_analysis(requirement_analysis)
        
        # 根据置信度确定评分权重策略
        scoring_strategy = self._get_scoring_strategy(confidence_score)
        
        # 从动态指令模板加载提示词
        prompt_template = self.instruction_loader.load_template('template_evaluation')
        prompt = prompt_template.replace('{user_requirement}', user_requirement)
        prompt = prompt.replace('{requirement_analysis}', analysis_text)
        prompt = prompt.replace('{candidates_text}', candidates_text)
        prompt = prompt.replace('{top_k}', str(top_k))
        
        # 如果有评分策略说明，添加到prompt中
        if scoring_strategy:
            prompt += f"\n\n## 评分权重策略\n\n{scoring_strategy}"
        
        try:
            result_text = _complete(model, prompt).strip()
            
            # 🐛 DEBUG: Print raw response to diagnose formatting issues
            print(f"\n{'='*60}")
            print(f"🐛 调试信息 - LLM原始响应:")
            print(f"{'='*60}")
            print(f"响应长度: {len(result_text)} 字符")
            print(f"前500字符: {result_text[:500]}")
            if len(result_text) > 500:
                print(f"... (省略 {len(result_text) - 500} 字符)")
            print(f"是否包含markdown代码块: {'```' in result_text}")
            print(f"{'='*60}\n")
            
            # Try to parse JSON
            # Remove markdown code blocks if present
            original_text = result_text
            if "```json" in result_text:
                print("⚠ 检测到markdown ```json代码块，正在提取...")
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                print("⚠ 检测到markdown ```代码块，正在提取...")
                result_text = result_text.split("```")[1].split("```")[0].strip()
            
            # Additional debug: show cleaned JSON
            if result_text != original_text:
                print(f"🐛 清理后的JSON（前200字符）: {result_text[:200]}\n")
            
            llm_result = json.loads(result_text)
            print("✓ JSON解析成功！")
            recommendations = llm_result.get('recommendations', [])
            print(f"\n{'='*60}")
            print(f"📋 LLM评估结果详情:")
            print(f"{'='*60}")
            print(f"LLM返回推荐数量: {len(recommendations)}")
            print(f"将处理前 {min(len(recommendations), top_k)} 个推荐 (top_k={top_k})")
            print(f"候选池大小: {len(candidates)} 个")
            
            # 打印 LLM 推荐的文件名列表
            print(f"\nLLM推荐的文件名:")
            for idx, rec in enumerate(recommendations[:top_k], 1):
                print(f"  {idx}. {rec.get('filename', 'N/A')} (得分: {rec.get('llm_score', 'N/A')})")
            
            print(f"\n候选池中的文件名（前10个）:")
            for idx, c in enumerate(candidates[:10], 1):
                print(f"  {idx}. {c.get('filename', 'N/A')}")
            print(f"{'='*60}\n")
            
            # Merge LLM evaluation with original data
            final_results = []
            match_failures = []
            
            for rec_idx, rec in enumerate(recommendations[:top_k], 1):
                filename = rec.get('filename', '')
                print(f"🔍 [{rec_idx}/{min(len(recommendations), top_k)}] 尝试匹配: {filename}")
                
                # Find original candidate with flexible matching
                # 1. 首先尝试精确匹配
                original = next((c for c in candidates if c['filename'] == filename), None)
                
                # 2. 如果精确匹配失败，尝试匹配文件名的basename部分
                if not original:
                    basename_match = next((c for c in candidates if c['filename'].endswith(filename)), None)
                    if basename_match:
                        print(f"   ℹ️ 使用basename匹配: {basename_match['filename']}")
                        original = basename_match
                
                # 3. 如果还是失败，尝试匹配去掉路径后的文件名
                if not original:
                    filename_only = os.path.basename(filename)
                    basename_only_match = next((c for c in candidates if os.path.basename(c['filename']) == filename_only), None)
                    if basename_only_match:
                        print(f"   ℹ️ 使用文件名匹配: {basename_only_match['filename']}")
                        original = basename_only_match
                
                # 4. 尝试不区分大小写的匹配
                if not original:
                    case_insensitive_match = next((c for c in candidates if c['filename'].lower() == filename.lower()), None)
                    if case_insensitive_match:
                        print(f"   ℹ️ 使用不区分大小写匹配: {case_insensitive_match['filename']}")
                        original = case_insensitive_match
                
                # 5. 尝试模糊匹配（去除空格、短横线等）
                if not original:
                    normalized_filename = filename.replace(' ', '').replace('-', '').replace('–', '').lower()
                    fuzzy_match = next((c for c in candidates 
                                      if c['filename'].replace(' ', '').replace('-', '').replace('–', '').lower() == normalized_filename), 
                                     None)
                    if fuzzy_match:
                        print(f"   ℹ️ 使用模糊匹配（忽略空格和短横线）: {fuzzy_match['filename']}")
                        original = fuzzy_match
                
                if original:
                    print(f"   ✅ 成功匹配到候选项: {original['filename']}")
                    # 确保template_path正确
                    template_path = rec.get('template_path', '')
                    if not template_path:
                        # 如果LLM没有提供，使用original中的路径
                        template_path = original.get('path', original.get('full_path', ''))
                        if not template_path:
                            # 如果都没有，使用original的filename构建路径
                            template_path = f"assets/templates/library/{original['filename']}"
                    
                    merged = {
                        **original,
                        'llm_score': rec.get('llm_score', 0),
                        'template_path': template_path,  # 使用确保正确的路径
                        'structure_description': rec.get('structure_description', ''),
                        'dimension_scores': rec.get('dimension_scores', {}),
                        'final_rank': len(final_results) + 1
                    }
                    final_results.append(merged)
                else:
                    print(f"   ❌ 匹配失败: 未在候选池中找到 '{filename}'")
                    print(f"      候选池中最相似的文件名（前3个）:")
                    # 显示最相似的候选项
                    similar_candidates = []
                    for c in candidates[:10]:
                        c_filename = c.get('filename', '')
                        # 计算简单的相似度（包含相同单词的数量）
                        if c_filename:
                            similarity = sum(1 for word in filename.split() if word in c_filename)
                            similar_candidates.append((c_filename, similarity))
                    similar_candidates.sort(key=lambda x: x[1], reverse=True)
                    for similar_name, sim_score in similar_candidates[:3]:
                        print(f"        - {similar_name} (相似度: {sim_score})")
                    match_failures.append(filename)
            
            # 汇总匹配结果
            print(f"\n{'='*60}")
            print(f"📊 匹配汇总:")
            print(f"{'='*60}")
            print(f"LLM推荐数量: {len(recommendations[:top_k])}")
            print(f"成功匹配数量: {len(final_results)}")
            print(f"匹配失败数量: {len(match_failures)}")
            if match_failures:
                print(f"失败的文件名: {', '.join(match_failures)}")
            print(f"{'='*60}\n")
            
            print(f"✓ 大模型评估完成: 推荐 {len(final_results)} 个最佳匹配")
            return final_results
        
        except json.JSONDecodeError as e:
            print(f"\n{'='*60}")
            print(f"❌ JSON解析失败！")
            print(f"{'='*60}")
            print(f"错误信息: {e}")
            print(f"错误位置: 行{e.lineno} 列{e.colno}")
            print(f"问题文本片段: {e.doc[max(0, e.pos-50):e.pos+50] if hasattr(e, 'doc') else '(无法显示)'}")
            print(f"\n💡 建议检查:")
            print(f"  1. LLM是否按照JSON格式要求输出")
            print(f"  2. 是否有多余的文字说明")
            print(f"  3. JSON格式是否正确（逗号、引号、括号等）")
            print(f"{'='*60}\n")
            # Fallback to keyword-based ranking
            fallback_results = candidates[:top_k]
            print(f"⚠️ 【重要】触发FALLBACK: 返回基于关键词排序的前 {len(fallback_results)} 个结果")
            print(f"   这可能导致推荐数量与预期不符！\n")
            return fallback_results
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"❌ 大模型评估失败: {type(e).__name__}")
            print(f"{'='*60}")
            print(f"错误信息: {e}")
            import traceback
            print(f"错误堆栈:\n{traceback.format_exc()}")
            print(f"{'='*60}\n")
            # Fallback to keyword-based ranking
            fallback_results = candidates[:top_k]
            print(f"⚠️ 【重要】触发FALLBACK: 返回基于关键词排序的前 {len(fallback_results)} 个结果")
            print(f"   这可能导致推荐数量与预期不符！\n")
            return fallback_results
    
    def _format_requirement_analysis(self, analysis: Dict[str, Any]) -> str:
        """格式化需求分析为文本"""
        if not analysis:
            return "（需求分析信息不可用）"
        
        lines = []
        
        # 图表类型
        chart_type = analysis.get('chart_type', '未知')
        lines.append(f"- **图表类型**: {chart_type}")
        
        # 复杂度
        complexity = analysis.get('complexity', '未知')
        complexity_map = {
            'simple': '简单（3-5个元素）',
            'medium': '中等（6-15个元素）',
            'complex': '复杂（16-30个元素）',
            'large': '大型（30+个元素）'
        }
        complexity_desc = complexity_map.get(complexity, complexity)
        lines.append(f"- **复杂度等级**: {complexity_desc}")
        
        # 预估形状数
        estimated_shapes = analysis.get('estimated_shapes', '未知')
        lines.append(f"- **预估形状数量**: {estimated_shapes}")
        
        # 架构模式
        architecture = analysis.get('architecture_pattern', '未知')
        lines.append(f"- **架构模式**: {architecture}")
        
        # 具体要求
        requirements = analysis.get('specific_requirements', [])
        if requirements:
            req_text = '、'.join(requirements[:5])
            lines.append(f"- **具体要求**: {req_text}")
        
        return '\n'.join(lines)
    
    def _get_scoring_strategy(self, confidence_score: float) -> str:
        """根据置信度返回评分权重策略说明"""
        if confidence_score < 0.4:
            # 低置信度（简短输入）：更重视功能匹配和可扩展性
            return """
当前为**低置信度匹配**（用户输入较简短），请按以下权重评分：
- 功能匹配度：权重 3（最重要，确保图表类型正确）
- 规模匹配度：权重 1（次要，因为用户未明确规模）
- 架构适配度：权重 2（重要）
- 专业度与细节：权重 1（次要）
- 可扩展性：权重 3（最重要，模板应易于扩展以适应不同需求）

推荐策略：优先推荐通用性强、易于扩展的模板。
"""
        elif confidence_score < 0.7:
            # 中置信度：均衡权重
            return """
当前为**中等置信度匹配**，请均衡考虑各个维度：
- 功能匹配度：权重 2
- 规模匹配度：权重 2
- 架构适配度：权重 2
- 专业度与细节：权重 2
- 可扩展性：权重 2

推荐策略：综合评估，选择最平衡的模板。
"""
        else:
            # 高置信度（详细输入）：更重视规模和架构匹配
            return """
当前为**高置信度匹配**（用户输入详细），请按以下权重评分：
- 功能匹配度：权重 2（基础要求）
- 规模匹配度：权重 3（最重要，严格匹配形状数量）
- 架构适配度：权重 3（最重要，严格匹配架构模式）
- 专业度与细节：权重 1（次要）
- 可扩展性：权重 1（次要，因为需求已明确）

推荐策略：精确匹配用户需求的规模和架构特征。
"""
    
    def _assess_input_complexity(self, user_input: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        评估用户输入的详细程度和置信度
        
        Args:
            user_input: 用户输入文本
            analysis: 需求分析结果
            
        Returns:
            复杂度评估结果：
            {
                'complexity_level': "brief" / "moderate" / "detailed",
                'confidence_score': 0.0-1.0,
                'missing_info': [...],
                'suggestions': [...]
            }
        """
        # 计算输入长度
        input_length = len(user_input)
        
        # 检查需求分析中是否包含关键信息
        has_chart_type = bool(analysis.get('chart_type') and analysis.get('chart_type') != '未知')
        has_complexity = bool(analysis.get('complexity') and analysis.get('complexity') != '未知')
        has_shapes_estimate = bool(analysis.get('estimated_shapes') and analysis.get('estimated_shapes') != '未知')
        has_architecture = bool(analysis.get('architecture_pattern') and analysis.get('architecture_pattern') != '未知')
        has_requirements = bool(analysis.get('specific_requirements'))
        
        # 计算信息完整度分数（0-1）
        info_completeness = sum([
            has_chart_type * 0.3,      # 图表类型最重要
            has_complexity * 0.15,      # 复杂度
            has_shapes_estimate * 0.25, # 形状数量估算
            has_architecture * 0.15,    # 架构模式
            has_requirements * 0.15     # 具体要求
        ])
        
        # 基于长度和信息完整度综合判断
        if input_length < 10:
            complexity_level = "brief"
            base_confidence = 0.2
        elif input_length < 50:
            complexity_level = "moderate"
            base_confidence = 0.5
        else:
            complexity_level = "detailed"
            base_confidence = 0.8
        
        # 综合置信度 = 基础置信度 * 0.4 + 信息完整度 * 0.6
        confidence_score = base_confidence * 0.4 + info_completeness * 0.6
        confidence_score = max(0.1, min(1.0, confidence_score))  # 限制在 0.1-1.0
        
        # 识别缺失的信息
        missing_info = []
        if not has_chart_type:
            missing_info.append("图表类型")
        if not has_shapes_estimate:
            missing_info.append("元素/形状数量")
        if not has_architecture:
            missing_info.append("架构模式或布局方式")
        if not has_requirements:
            missing_info.append("具体使用场景或要求")
        
        # 生成优化建议
        suggestions = []
        if confidence_score < 0.7 and missing_info:
            suggestions.append(f"建议补充以下信息以获得更精确推荐：{', '.join(missing_info)}")
            
            if not has_shapes_estimate:
                suggestions.append("例如：\"预计包含10-15个步骤\" 或 \"需要展示5个主要组件\"")
            
            if not has_requirements:
                suggestions.append("例如：\"用于系统设计\" 或 \"展示业务流程\"")
        
        return {
            'complexity_level': complexity_level,
            'confidence_score': confidence_score,
            'missing_info': missing_info,
            'suggestions': suggestions,
            'info_completeness': info_completeness
        }
    
    def _get_dynamic_filter_threshold(self, confidence_score: float) -> float:
        """
        根据置信度动态调整筛选阈值（关键词）
        
        Args:
            confidence_score: 置信度分数 (0.0-1.0)
            
        Returns:
            筛选阈值（关键词阈值非常宽松，主要依赖结构筛选）
        """
        if confidence_score < 0.4:
            # 低置信度：极低阈值，几乎不过滤
            return 0.02
        elif confidence_score < 0.7:
            # 中置信度：很低阈值
            return 0.05
        else:
            # 高置信度：低阈值
            return 0.08
    
    def _format_candidates_for_llm(self, candidates: List[Dict[str, Any]]) -> str:
        """格式化候选项供LLM评估（强化结构信息）"""
        lines = []
        for i, item in enumerate(candidates, 1):
            name = item.get('name', item.get('filename', ''))
            filename = item['filename']
            
            # 构建完整路径（如果没有提供的话）
            full_path = item.get('path', item.get('full_path', ''))
            if not full_path:
                # 根据文件名构建默认路径
                full_path = f"assets/templates/library/{filename}"
            
            category = item.get('category', 'general')
            complexity = item.get('complexity', 'unknown')
            
            lines.append(f"{i}. 文件名: {filename}")
            lines.append(f"   完整路径: {full_path}")
            lines.append(f"   类别: {category}")
            lines.append(f"   复杂度: {complexity}")
            
            # Add shape info for templates (结构信息优先)
            if 'shape_total' in item:
                lines.append(f"   形状总数: {item.get('shape_total', 0)}")
                lines.append(f"   连接器数: {item.get('total_connectors', 0)}")
                
                # ⭐ 结构信息放在最前面（最重要）
                topology = item.get('topology_pattern', {})
                layout = item.get('layout_pattern', {})
                
                if topology and topology.get('description'):
                    lines.append(f"   ⭐ 拓扑结构: {topology.get('description', '未知')}")
                    # 添加更多拓扑细节
                    if topology.get('pattern_type'):
                        lines.append(f"      - 拓扑类型: {topology.get('pattern_type')}")
                    if topology.get('max_depth'):
                        lines.append(f"      - 最大深度: {topology.get('max_depth')}")
                    if topology.get('branching_factor'):
                        lines.append(f"      - 分支因子: {topology.get('branching_factor')}")
                
                if layout and layout.get('description'):
                    lines.append(f"   ⭐ 布局模式: {layout.get('description', '未知')}")
                    # 添加更多布局细节
                    if layout.get('pattern_type'):
                        lines.append(f"      - 布局类型: {layout.get('pattern_type')}")
                    if layout.get('primary_direction'):
                        lines.append(f"      - 主要方向: {layout.get('primary_direction')}")
                    if layout.get('alignment'):
                        lines.append(f"      - 对齐方式: {layout.get('alignment')}")
                
                # 连接图谱信息
                conn_graph = item.get('connection_graph', {})
                if conn_graph and conn_graph.get('edge_count'):
                    lines.append(f"   连接关系: {conn_graph.get('edge_count')} 条连接")
            
            # Add master info for stencils
            if 'master_count' in item:
                lines.append(f"   主形状数: {item.get('master_count', 0)}")
                masters = item.get('master_names', [])[:10]
                if masters:
                    lines.append(f"   主形状示例: {', '.join(masters)}")
            
            lines.append("")
        
        return '\n'.join(lines)
    
    def smart_match(self, user_input: str, model: Any,
                   search_type: str = "template",
                   top_k: int = 5) -> Dict[str, Any]:
        """
        智能匹配流程：中文输入 -> 需求分析 -> 关键词筛选 -> LLM评估 -> 中文输出
        
        Args:
            user_input: 用户输入（支持中文）
            model: OpenAI模型实例
            search_type: "template" 或 "stencil"
            top_k: 返回前k个结果
            
        Returns:
            包含匹配结果的字典（中文描述）
        """
        print(f"\n{'='*60}")
        print(f"🔍 开始智能匹配 - 搜索类型: {search_type}")
        print(f"{'='*60}")
        
        # Step 1: Extract English keywords and requirement analysis from input
        print("\n📝 步骤 1: 提取英文关键词和需求分析...")
        extraction_result = self.extract_english_keywords(user_input, model)
        keywords = extraction_result['keywords']
        analysis = extraction_result['analysis']
        
        if not keywords:
            print("⚠ 警告: 未能提取关键词，使用备用方案")
            keywords = self._fallback_keyword_extraction(user_input)
        
        # Assess input complexity for dynamic matching
        print("\n🎯 步骤 1.5: 评估输入复杂度...")
        complexity_assessment = self._assess_input_complexity(user_input, analysis)
        confidence_score = complexity_assessment['confidence_score']
        print(f"✓ 输入复杂度: {complexity_assessment['complexity_level']}")
        print(f"✓ 匹配置信度: {confidence_score:.2f}")
        
        # Step 2: Filter by keywords and structure (dynamic threshold based on complexity)
        print("\n🔎 步骤 2: 关键词+结构筛选（动态阈值）...")
        keyword_threshold = self._get_dynamic_filter_threshold(confidence_score)
        structure_threshold = 0.5  # 结构阈值：提高到0.5，严格要求结构匹配
        print(f"✓ 使用关键词阈值: {keyword_threshold}, 结构阈值: {structure_threshold}")
        print(f"✓ 筛选策略: 关键词极宽松（{keyword_threshold}），结构严格把关（{structure_threshold}）")
        
        candidates = self.filter_by_keywords_and_structure(
            keywords,
            analysis,  # 传递需求分析结果
            search_type=search_type,
            keyword_threshold=keyword_threshold,
            structure_threshold=structure_threshold
        )
        
        if not candidates:
            print("⚠ 未找到匹配项，降低筛选标准...")
            candidates = self.filter_by_keywords_and_structure(
                keywords,
                analysis,
                search_type=search_type,
                keyword_threshold=0.0,
                structure_threshold=0.0  # 降低两个阈值
            )
        
        # Step 3: Evaluate with LLM (using full library and requirement analysis)
        print(f"\n🤖 步骤 3: 大模型评估（从 {len(candidates)} 个候选中选择前20个进行评估）...")
        if candidates:
            final_results = self.evaluate_with_llm(
                candidates,
                user_input,
                analysis,  # Pass requirement analysis
                model,
                top_k=top_k,
                search_type=search_type,
                confidence_score=confidence_score  # Pass confidence score for dynamic scoring
            )
        else:
            final_results = []
        
        # Step 4: Format output in Chinese
        print("\n📊 步骤 4: 生成中文输出...")
        output = self._format_chinese_output(
            user_input,
            keywords,
            final_results,
            search_type,
            complexity_assessment,  # Pass complexity assessment
            analysis  # Pass analysis
        )
        
        print(f"\n{'='*60}")
        print(f"✅ 智能匹配完成")
        print(f"{'='*60}\n")
        
        return output
    
    def _format_chinese_output(self, user_input: str, keywords: List[str],
                              results: List[Dict[str, Any]], 
                              search_type: str,
                              complexity_assessment: Optional[Dict[str, Any]] = None,
                              analysis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """格式化中文输出（极简版，最小化token占用）"""
        print(f"\n{'='*60}")
        print(f"📝 步骤 4: 格式化中文输出")
        print(f"{'='*60}")
        print(f"收到结果数量: {len(results)}")
        if results:
            print(f"结果详情:")
            for idx, r in enumerate(results, 1):
                filename = r.get('filename', 'N/A')
                score = r.get('llm_score', r.get('combined_score', 'N/A'))
                print(f"  {idx}. {filename} (得分: {score})")
        else:
            print(f"⚠️ 警告: 没有结果可格式化！")
        print(f"{'='*60}\n")
        
        type_name = "模板" if search_type == "template" else "形状库"
        
        # 极简输出：只返回推荐列表，移除所有冗余信息
        output = {
            "搜索类型": type_name,
            "推荐列表": []
        }
        
        # 格式化推荐列表（仅保留核心字段）
        for i, item in enumerate(results, 1):
            # 获取或构建完整路径
            template_path = item.get('template_path', item.get('path', item.get('full_path', '')))
            if not template_path:
                # 根据文件名构建默认路径
                template_path = f"assets/templates/library/{item['filename']}"
            
            # 核心信息：路径、得分、描述
            recommendation = {
                "排名": i,
                "路径": template_path,
                "得分": round(item.get('llm_score', 0), 1),
                "描述": item.get('structure_description', ''),
            }
            
            # 添加预览URL（模板）或形状数（形状库）
            if search_type == "template":
                # 使用Markdown链接格式避免URL因空格被拆分
                filename = os.path.basename(template_path)
                recommendation["预览"] = f"[{filename}](http://localhost:7777/api/visio/preview?path={template_path})"
            
            output["推荐列表"].append(recommendation)
        
        print(f"✅ 最终生成推荐列表: {len(output['推荐列表'])} 项\n")
        
        return output


def create_smart_matcher(template_library_path: str = "assets/indexes/template_library.json",
                        stencil_library_path: str = "assets/indexes/stencil_library.json",
                        auto_load: bool = False,
                        use_cache: bool = True) -> SmartMatcher:
    """
    创建智能匹配器实例
    
    Args:
        template_library_path: 模板库路径
        stencil_library_path: 形状库路径
        auto_load: 是否自动加载库文件（默认False，延迟加载）
        use_cache: 是否使用缓存（默认True）
        
    Returns:
        SmartMatcher实例（默认不自动加载，只在需要时才加载）
    """
    return SmartMatcher(template_library_path, stencil_library_path, auto_load=auto_load, use_cache=use_cache)
