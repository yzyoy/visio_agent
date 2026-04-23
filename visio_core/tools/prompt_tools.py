"""
Prompt generation tools for Visio diagram creation
Handles template recommendation and prompt generation
"""
import json
import re
from typing import List, Dict, Any, Optional
from typing import Any as _Any

from ..templates.template_manager import TemplateManager
from ..utils.smart_matcher import SmartMatcher


class PromptTools:
    """Tools for template recommendation and prompt generation"""
    
    # List of all available Visio tools
    AVAILABLE_TOOLS = [
        "load_diagram", "show_visio_file", "create_new_diagram", "get_diagram_info",
        "preview_current_page_png", "preview_vsdx_png",
        "add_shape", "clone_shape", "replace_shape", "batch_replace_shapes",
        "update_shape_text", "update_text_by_match", "update_text_by_match_all",
        "batch_update_text_by_map", "fill_placeholders",
        "connect_shapes", "reconnect_shapes", "auto_route_connector",
        "get_shape_connections", "analyze_diagram_connections", "remove_shape", "find_shape_by_text",
        "list_shapes", "create_from_template_and_load", "save_diagram",
        "add_page", "switch_page", "get_log_summary",
        "align_shapes_horizontal", "align_shapes_vertical",
        "distribute_shapes_horizontal", "distribute_shapes_vertical",
        "center_drawing", "apply_professional_routing",
        "add_or_update_shape", "add_or_update_connector",
        "prune_untracked_shapes", "list_all_shape_keys",
        "debug_template_selection", "explain_template_selection",
        "preflight_check_plan", "preflight_check_prompt",
        "list_template_candidates", "proceed_with_plan",
        "set_session", "reset_session", "get_session_context",
        "get_template_info", "list_position"  # Template analysis tools
    ]
    
    def __init__(self, template_dir: str = "assets/templates",
                 template_library_path: str = "assets/indexes/template_library.json",
                 stencil_library_path: str = "assets/indexes/stencil_library.json"):
        """
        Initialize prompt tools
        
        Args:
            template_dir: Directory containing templates
            template_library_path: Path to template library JSON
            stencil_library_path: Path to stencil library JSON
        """
        self.template_manager = TemplateManager(template_dir)
        self.smart_matcher = SmartMatcher(template_library_path, stencil_library_path)
        self.model = None  # Will be set when needed
        
    
    def set_model(self, model: _Any):
        """Inject an LLM model for smart matching.

        The model must expose either ``.complete(prompt: str) -> str`` or
        the agno-style ``.response([msg]).content`` protocol. This is how
        the app / MCP layer wires the concrete LLM SDK in; the core
        library never imports agno.
        """
        self.model = model
    
    # ========== 6-Step Template Analysis Tools (Direct Wrappers) ==========
    # These tools provide direct access to Visio analysis functions
    # for detailed template examination during prompt generation
    
    def get_template_info(self, template_path: str) -> str:
        """
        步骤1/6：提取模板元数据
        Extract template metadata including name, category, and structure
        
        Args:
            template_path: 模板文件路径（相对于 assets/templates 目录）
            
        Returns:
            模板元数据信息（名称、类别、包含的形状等）
            
        Example:
            get_template_info("flowchart_basic.vsdx")
        """
        from ..tools.visio_tools import VisioTools
        visio_tools = VisioTools()
        return visio_tools.get_template_info(template_path)
    
    def load_template_for_analysis(self, template_path: str, output_path: str = None) -> str:
        """
        步骤2/6：加载模板进行深度分析
        Load template into memory for comprehensive examination
        
        Args:
            template_path: 模板文件路径
            output_path: 输出路径（可选，默认创建临时文件）
            
        Returns:
            加载状态信息
            
        Example:
            load_template_for_analysis("flowchart_basic.vsdx", "temp/analysis.vsdx")
        """
        from ..tools.visio_tools import VisioTools
        import os
        import tempfile
        
        visio_tools = VisioTools()
        
        if output_path is None:
            # Create temporary output path
            temp_dir = tempfile.gettempdir()
            output_path = os.path.join(temp_dir, f"temp_analysis_{os.path.basename(template_path)}")
        
        # Store for later cleanup
        self._temp_analysis_file = output_path
        
        return visio_tools.create_from_template_and_load(template_path, output_path)
    
    def get_diagram_info_from_loaded(self) -> str:
        """
        步骤3/6：获取已加载图表的详细信息
        Get comprehensive diagram properties, dimensions, and characteristics
        
        Must call load_template_for_analysis first!
        
        Returns:
            图表详细信息（页面尺寸、页数、单位等）
            
        Example:
            get_diagram_info_from_loaded()
        """
        from ..tools.visio_tools import VisioTools
        visio_tools = VisioTools()
        return visio_tools.get_diagram_info()
    
    def list_shapes_from_loaded(self, shape_type_filter: str = None) -> str:
        """
        步骤4/6：列举已加载图表中的所有形状
        Enumerate all shapes, their types, properties, and visual characteristics
        
        Must call load_template_for_analysis first!
        
        Args:
            shape_type_filter: 可选的形状类型过滤器（如"Rectangle", "Diamond"等）
            
        Returns:
            形状列表（ID、类型、文本、位置等）
            
        Example:
            list_shapes_from_loaded()
            list_shapes_from_loaded("Rectangle")
        """
        from ..tools.visio_tools import VisioTools
        visio_tools = VisioTools()
        return visio_tools.list_shapes(shape_type_filter)
    
    def analyze_connections_from_loaded(self) -> str:
        """
        步骤5/6：分析已加载图表的连接架构
        Analyze connection patterns, flow directions, and connectivity logic
        
        Must call load_template_for_analysis first!
        
        Returns:
            连接分析（拓扑结构、流向、关系模式等）
            
        Example:
            analyze_connections_from_loaded()
        """
        from ..tools.visio_tools import VisioTools
        visio_tools = VisioTools()
        return visio_tools.analyze_diagram_connections()
    
    def list_position_from_loaded(self) -> str:
        """
        步骤6/6：提取已加载图表的精确定位数据
        Extract precise positioning data: coordinates, spacing, alignment, and layout
        
        Must call load_template_for_analysis first!
        
        Returns:
            位置数据（坐标、间距、对齐、布局信息等）
            
        Example:
            list_position_from_loaded()
        """
        from ..tools.visio_tools import VisioTools
        visio_tools = VisioTools()
        return visio_tools.list_position()
    
    def cleanup_analysis_temp_files(self) -> str:
        """
        清理分析过程中创建的临时文件
        Clean up temporary files created during analysis
        
        Returns:
            清理状态信息
        """
        import os
        if hasattr(self, '_temp_analysis_file') and self._temp_analysis_file:
            try:
                if os.path.exists(self._temp_analysis_file):
                    os.remove(self._temp_analysis_file)
                    return f"✓ 已清理临时文件: {self._temp_analysis_file}"
                else:
                    return f"✓ 临时文件不存在，无需清理"
            except Exception as e:
                return f"⚠ 清理临时文件失败: {e}"
        return "✓ 没有需要清理的临时文件"
    
    # ========== End of 6-Step Analysis Tools ==========
    
    def search_templates_by_requirement(self, user_requirement: str, use_smart_match: bool = True) -> str:
        """
        根据用户需求搜索匹配的模板（支持智能匹配）
        Search for templates matching user requirements with smart matching
        
        Args:
            user_requirement: 用户的需求描述 (User requirement description)
            use_smart_match: 是否使用智能匹配（关键词筛选 + LLM评估）
            
        Returns:
            JSON string with matching templates (中文输出)
            
        Example:
            搜索模板("我想画一个用户登录的流程图")
            search_templates_by_requirement("I want to create a user login flowchart")
        """
        # Use smart matching if model is available and enabled
        if use_smart_match and self.model:
            try:
                result = self.smart_matcher.smart_match(
                    user_requirement,
                    self.model,
                    search_type="template",
                    top_k=5
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"⚠ 智能匹配失败，回退到基础匹配: {e}")
        
        # Fallback to basic keyword matching
        keywords = self._extract_keywords(user_requirement)
        results = self.template_manager.search_templates(keywords=keywords)
        
        if not results:
            # If no results, return all templates
            results = []
            for filename, info in self.template_manager.library.items():
                results.append({
                    'filename': filename,
                    **info
                })
        
        # Format results in Chinese
        output = {
            '用户需求': user_requirement,
            '提取的关键词': keywords,
            '匹配的模板': results,
            '找到结果数': len(results)
        }
        
        return json.dumps(output, ensure_ascii=False, indent=2)
    
    def rank_templates_for_requirement(self, user_requirement: str,
                                      candidate_templates_json: str) -> str:
        """
        对候选模板进行排序（简化版，基于关键词匹配度）
        Rank candidate templates for a requirement (simplified keyword-based)
        
        Args:
            user_requirement: 用户需求
            candidate_templates_json: 候选模板的JSON字符串
            
        Returns:
            Ranked templates as JSON string
        """
        try:
            candidates = json.loads(candidate_templates_json)
            if isinstance(candidates, dict) and 'matching_templates' in candidates:
                candidates = candidates['matching_templates']
        except:
            return json.dumps({'error': 'Invalid candidate templates JSON'})
        
        # Extract keywords from requirement
        keywords = self._extract_keywords(user_requirement)
        
        # Score each template
        scored = []
        for template in candidates:
            score = self._calculate_match_score(template, keywords)
            scored.append({
                **template,
                'match_score': score
            })
        
        # Sort by score (descending)
        scored.sort(key=lambda x: x['match_score'], reverse=True)
        
        return json.dumps({
            'requirement': user_requirement,
            'ranked_templates': scored[:5],  # Top 5
        }, ensure_ascii=False, indent=2)
    
    def generate_prompt_from_template(self, template_name: str,
                                     user_requirement: str,
                                     detail_level: str = "detailed") -> str:
        """
        生成详细的分步骤prompt
        Generate detailed step-by-step prompt from template
        
        Args:
            template_name: 模板名称或文件名
            user_requirement: 用户需求描述
            detail_level: 'detailed' (详细) or 'concise' (简洁)
            
        Returns:
            Generated prompt as string
            
        Example:
            生成提示词("try.vsdx", "创建一个用户登录流程图", "detailed")
        """
        # Get template info
        template_info = None
        for filename, info in self.template_manager.library.items():
            if filename == template_name or info.get('name') == template_name:
                template_info = info
                template_name = filename
                break
        
        if not template_info:
            return f"❌ 错误：未找到模板 '{template_name}'\nError: Template '{template_name}' not found"
        
        # Generate prompt based on detail level
        if detail_level == "detailed":
            prompt = self._generate_detailed_prompt(template_name, template_info, user_requirement)
        else:
            prompt = self._generate_concise_prompt(template_name, template_info, user_requirement)
        
        return prompt
    
    def validate_prompt_tools(self, generated_prompt: str) -> str:
        """
        验证prompt中的工具调用是否都存在
        Validate that all tool calls in prompt exist in available tools
        
        Args:
            generated_prompt: 生成的prompt文本
            
        Returns:
            Validation report as JSON string
        """
        # Extract tool names from prompt
        # Look for patterns like: tool_name(...) 
        tool_pattern = r'\b([a-z_]+)\s*\('
        found_tools = re.findall(tool_pattern, generated_prompt)
        
        # Remove duplicates and filter
        found_tools = list(set(found_tools))
        
        # Check which are valid
        valid_tools = []
        invalid_tools = []
        
        for tool in found_tools:
            if tool in self.AVAILABLE_TOOLS:
                valid_tools.append(tool)
            else:
                # Check if it might be a typo or similar
                invalid_tools.append(tool)
        
        report = {
            'total_tool_calls': len(found_tools),
            'valid_tools': valid_tools,
            'invalid_tools': invalid_tools,
            'validation_passed': len(invalid_tools) == 0,
        }
        
        if invalid_tools:
            report['suggestions'] = self._suggest_tool_corrections(invalid_tools)
        
        return json.dumps(report, ensure_ascii=False, indent=2)
    
    def get_available_visio_tools(self) -> str:
        """
        返回所有可用的Visio工具列表
        Get list of all available Visio tools
        
        Returns:
            Formatted string with tool categories and names
        """
        tools_by_category = {
            "文件操作 (File Operations)": [
                "load_diagram", "show_visio_file", "create_new_diagram",
                "create_from_template_and_load", "save_diagram", "get_diagram_info"
            ],
            "形状操作 (Shape Operations)": [
                "add_shape", "clone_shape", "replace_shape", "batch_replace_shapes",
                "remove_shape", "list_shapes", "find_shape_by_text"
            ],
            "文本更新 (Text Updates)": [
                "update_shape_text", "update_text_by_match", "update_text_by_match_all",
                "batch_update_text_by_map", "fill_placeholders"
            ],
            "连接与路由 (Connections & Routing)": [
                "connect_shapes", "reconnect_shapes", "auto_route_connector",
                "get_shape_connections", "analyze_diagram_connections", "apply_professional_routing"
            ],
            "布局对齐 (Layout & Alignment)": [
                "align_shapes_horizontal", "align_shapes_vertical",
                "distribute_shapes_horizontal", "distribute_shapes_vertical",
                "center_drawing"
            ],
            "幂等操作 (Idempotent Operations)": [
                "add_or_update_shape", "add_or_update_connector",
                "prune_untracked_shapes", "list_all_shape_keys"
            ],
            "预览渲染 (Preview & Rendering)": [
                "preview_current_page_png", "preview_vsdx_png"
            ],
            "页面管理 (Page Management)": [
                "add_page", "switch_page"
            ],
            "诊断工具 (Diagnostic Tools)": [
                "get_log_summary", "debug_template_selection",
                "explain_template_selection", "preflight_check_plan",
                "preflight_check_prompt", "list_template_candidates"
            ],
            "会话管理 (Session Management)": [
                "set_session", "reset_session", "get_session_context"
            ]
        }
        
        output = ["📚 可用的 Visio 工具列表 / Available Visio Tools\n"]
        output.append("=" * 60)
        
        for category, tools in tools_by_category.items():
            output.append(f"\n{category}:")
            for tool in tools:
                output.append(f"  - {tool}")
        
        output.append(f"\n{'=' * 60}")
        output.append(f"总计 / Total: {len(self.AVAILABLE_TOOLS)} 个工具")
        
        return "\n".join(output)
    
    def search_stencils_by_requirement(self, user_requirement: str, use_smart_match: bool = True) -> str:
        """
        根据用户需求搜索匹配的形状库（支持智能匹配）
        Search for stencils matching user requirements with smart matching
        
        Args:
            user_requirement: 用户的需求描述 (User requirement description)
            use_smart_match: 是否使用智能匹配（关键词筛选 + LLM评估）
            
        Returns:
            JSON string with matching stencils (中文输出)
            
        Example:
            搜索形状库("我需要云服务图标")
            search_stencils_by_requirement("I need cloud service icons")
        """
        # Use smart matching if model is available and enabled
        if use_smart_match and self.model:
            try:
                result = self.smart_matcher.smart_match(
                    user_requirement,
                    self.model,
                    search_type="stencil",
                    top_k=5
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"⚠ 智能匹配失败，回退到基础匹配: {e}")
        
        # Fallback to basic keyword matching
        keywords = self._extract_keywords(user_requirement)
        
        # Search in stencil library
        from ..templates.stencil_manager import StencilManager
        stencil_manager = StencilManager()
        results = stencil_manager.search_stencils(keywords=keywords)
        
        # Format results in Chinese
        output = {
            '用户需求': user_requirement,
            '提取的关键词': keywords,
            '匹配的形状库': results,
            '找到结果数': len(results)
        }
        
        return json.dumps(output, ensure_ascii=False, indent=2)
    
    def analyze_template_for_recommendation(self, template_path: str, cleanup: bool = True) -> str:
        """
        执行模板的完整分析流程，用于生成详细的模板推荐信息
        Execute complete template analysis workflow for detailed recommendations
        
        This automatically performs:
        1. Extract template metadata (name, category, structure)
        2. Load template for deep analysis
        3. Gather diagram info (dimensions, properties)
        4. List all shapes and elements
        5. Analyze connection architecture
        6. Extract positioning data
        
        Args:
            template_path: 模板文件路径 (相对于templates目录)
            cleanup: 分析后是否清理临时文件 (默认True)
            
        Returns:
            JSON string with comprehensive analysis results
            
        Example:
            analyze_template_for_recommendation("flowchart_basic.vsdx")
            analyze_template_for_recommendation("architecture_cloud.vsdx", cleanup=False)
        """
        from ..tools.visio_tools import VisioTools
        import os
        import tempfile
        
        analysis_result = {
            '模板路径': template_path,
            '分析状态': {},
            '元数据信息': {},
            '图表信息': {},
            '形状分析': {},
            '连接分析': {},
            '位置分析': {},
            '推荐依据': {}
        }
        
        # Create temporary VisioTools instance for analysis
        visio_tools = VisioTools()
        temp_output = None
        
        try:
            # Step 1: Get template metadata
            analysis_result['分析状态']['步骤1_元数据提取'] = '进行中'
            metadata_str = visio_tools.get_template_info(template_path)
            analysis_result['元数据信息'] = self._parse_template_info(metadata_str)
            analysis_result['分析状态']['步骤1_元数据提取'] = '完成'
            
            # Step 2: Load template for analysis (create temporary output)
            analysis_result['分析状态']['步骤2_加载模板'] = '进行中'
            temp_output = os.path.join(tempfile.gettempdir(), f"temp_analysis_{os.path.basename(template_path)}")
            load_result = visio_tools.create_from_template_and_load(template_path, temp_output)
            
            if '✓' not in load_result:
                analysis_result['分析状态']['步骤2_加载模板'] = f'失败: {load_result}'
                return json.dumps(analysis_result, ensure_ascii=False, indent=2)
            
            # CRITICAL: Reload the diagram to ensure proper initialization
            reload_result = visio_tools.load_diagram(temp_output)
            if '✓' not in reload_result:
                analysis_result['分析状态']['步骤2_重新加载'] = f'失败: {reload_result}'
                return json.dumps(analysis_result, ensure_ascii=False, indent=2)
            
            analysis_result['分析状态']['步骤2_加载模板'] = '完成'
            
            # Step 3: Get diagram info
            analysis_result['分析状态']['步骤3_图表信息'] = '进行中'
            diagram_info_str = visio_tools.get_diagram_info()
            analysis_result['图表信息'] = self._parse_diagram_info(diagram_info_str)
            analysis_result['分析状态']['步骤3_图表信息'] = '完成'
            
            # Step 4: List all shapes
            analysis_result['分析状态']['步骤4_形状列表'] = '进行中'
            shapes_str = visio_tools.list_shapes()
            analysis_result['形状分析'] = self._parse_shapes_info(shapes_str)
            analysis_result['分析状态']['步骤4_形状列表'] = '完成'
            
            # Step 5: Analyze connections
            analysis_result['分析状态']['步骤5_连接分析'] = '进行中'
            connections_str = visio_tools.analyze_diagram_connections()
            analysis_result['连接分析'] = self._parse_connections_info(connections_str)
            analysis_result['分析状态']['步骤5_连接分析'] = '完成'
            
            # Step 6: Extract positioning data
            analysis_result['分析状态']['步骤6_位置分析'] = '进行中'
            position_str = visio_tools.list_position()
            analysis_result['位置分析'] = self._parse_position_info(position_str)
            analysis_result['分析状态']['步骤6_位置分析'] = '完成'
            
            # Generate recommendation logic summary
            analysis_result['推荐依据'] = self._generate_recommendation_logic(
                analysis_result['形状分析'],
                analysis_result['连接分析'],
                analysis_result['位置分析']
            )
            
            analysis_result['分析状态']['总体状态'] = '成功完成'
            
        except Exception as e:
            analysis_result['分析状态']['错误'] = str(e)
            analysis_result['分析状态']['总体状态'] = '失败'
        
        finally:
            # Cleanup temporary files if requested
            if cleanup and temp_output and os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                    analysis_result['分析状态']['清理'] = '已清理临时文件'
                except:
                    pass
        
        return json.dumps(analysis_result, ensure_ascii=False, indent=2)
    
    # Helper methods
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text (Chinese and English)"""
        # Common keywords for diagram types
        keyword_map = {
            '流程图': ['flowchart', 'process', 'workflow', '流程'],
            '架构': ['architecture', 'structure', '架构'],
            '组织': ['organization', 'org', '组织'],
            '网络': ['network', '网络'],
            '时序': ['sequence', 'timeline', '时序'],
            '算法': ['algorithm', '算法'],
            '决策': ['decision', '决策'],
            '用户': ['user', 'login', 'registration', '用户'],
            '系统': ['system', '系统'],
            '数据': ['data', 'database', '数据'],
        }
        
        keywords = []
        text_lower = text.lower()
        
        # Extract keywords
        for key, synonyms in keyword_map.items():
            if key in text or any(syn in text_lower for syn in synonyms):
                keywords.append(key)
                keywords.extend(synonyms)
        
        # Also extract individual important words
        words = re.findall(r'\b[a-zA-Z\u4e00-\u9fff]{2,}\b', text)
        keywords.extend(words)
        
        return list(set(keywords))[:10]  # Limit to 10 keywords
    
    def _calculate_match_score(self, template: Dict[str, Any], keywords: List[str]) -> float:
        """Calculate match score between template and keywords"""
        score = 0.0
        
        # Check keywords field
        template_keywords = template.get('keywords', [])
        for kw in keywords:
            if any(kw.lower() in tk.lower() for tk in template_keywords):
                score += 2.0
        
        # Check name and description
        searchable = ' '.join([
            template.get('name', ''),
            template.get('description', ''),
            ' '.join(template.get('use_cases', []))
        ]).lower()
        
        for kw in keywords:
            if kw.lower() in searchable:
                score += 1.0
        
        return score
    
    def _generate_detailed_prompt(self, template_name: str, template_info: Dict[str, Any],
                                 requirement: str) -> str:
        """Generate detailed prompt in the style of transformer_flowchart_prompt.txt"""
        
        template_display_name = template_info.get('name', template_name)
        shapes_info = template_info.get('shapes', {})
        
        prompt = f"""# {requirement} - 使用 {template_display_name}

用途：基于模板 `{template_name}` 创建符合需求的 Visio 图表。

---

## 🎯 目标

- 根据需求：{requirement}
- 使用模板：{template_display_name}
- 模板包含形状：{', '.join([f'{k}({v})' for k, v in shapes_info.items()])}
- 保持模板样式与连线风格

---

## 🚀 步骤

### 1) 加载模板
```
create_from_template_and_load("{template_name}", "outputs/my_diagram.vsdx")
```

### 2) 查看现有形状（了解模板结构）
```
list_shapes()
```

### 3) 根据需求修改或添加形状

**方式A：仅修改文本（原位更新，推荐）**
```
update_text_by_match("原文本", "新文本", "contains")
```

**方式B：添加新形状**
```
add_shape("文本", "Rectangle", x, y, width, height)
```

**方式C：克隆现有形状**
```
clone_shape("shape_id", new_x, new_y)
```

### 4) 建立连接
```
connect_shapes("from_shape_id", "to_shape_id")
```

### 5) 专业布局与美化
```
apply_professional_routing("all")
align_shapes_vertical("id1,id2,id3", "center")
distribute_shapes_horizontal("id1,id2,id3", 1.0)
center_drawing()
```

### 6) 保存与预览
```
save_diagram("outputs/my_diagram.vsdx")
preview_current_page_png(2.0)
get_log_summary()
```

---

## 📌 提示

- 优先使用文本原位更新工具（update_text_by_match）修改文本
- 需要添加新元素时，优先克隆现有形状保持样式一致
- 连接线建议使用 apply_professional_routing 获得专业效果
- 坐标系统：单位英寸，原点左下，(x,y) 为形状中心
- 常用间距：0.8-1.0 英寸

---

## 🔧 可用的工具

此 prompt 严格使用以下 Visio 工具：
- create_from_template_and_load, load_diagram, save_diagram
- list_shapes, find_shape_by_text, add_shape, clone_shape
- update_shape_text, update_text_by_match, fill_placeholders
- connect_shapes, apply_professional_routing
- align_shapes_horizontal, align_shapes_vertical
- distribute_shapes_horizontal, distribute_shapes_vertical
- center_drawing, preview_current_page_png, get_log_summary

请根据具体需求调整上述步骤。
"""
        
        return prompt
    
    def _generate_concise_prompt(self, template_name: str, template_info: Dict[str, Any],
                                requirement: str) -> str:
        """Generate concise prompt with just tool calls"""
        
        prompt = f"""# {requirement}

create_from_template_and_load("{template_name}", "outputs/my_diagram.vsdx")
list_shapes()

# 根据需求修改形状和文本
# update_text_by_match("旧文本", "新文本", "contains")
# add_shape("文本", "Rectangle", x, y, w, h)
# connect_shapes("from_id", "to_id")

# 布局美化
apply_professional_routing("all")
center_drawing()

# 保存
save_diagram("outputs/my_diagram.vsdx")
preview_current_page_png(2.0)
get_log_summary()
"""
        
        return prompt
    
    def _suggest_tool_corrections(self, invalid_tools: List[str]) -> Dict[str, List[str]]:
        """Suggest corrections for invalid tool names"""
        suggestions = {}
        
        for invalid in invalid_tools:
            similar = []
            for valid in self.AVAILABLE_TOOLS:
                # Simple similarity check
                if invalid in valid or valid in invalid:
                    similar.append(valid)
                # Check Levenshtein distance (simple version)
                elif self._simple_similarity(invalid, valid) > 0.6:
                    similar.append(valid)
            
            if similar:
                suggestions[invalid] = similar[:3]  # Top 3 suggestions
        
        return suggestions
    
    def _simple_similarity(self, s1: str, s2: str) -> float:
        """Simple string similarity metric"""
        if not s1 or not s2:
            return 0.0
        
        # Count matching characters
        matches = sum(1 for a, b in zip(s1, s2) if a == b)
        return matches / max(len(s1), len(s2))
    
    def _parse_template_info(self, info_str: str) -> Dict[str, Any]:
        """Parse template info string into structured data"""
        result = {'原始信息': info_str[:200] + '...' if len(info_str) > 200 else info_str}
        try:
            # Extract key info from the string
            if '名称' in info_str or 'Name' in info_str:
                lines = info_str.split('\n')
                for line in lines:
                    if '名称' in line or 'Name' in line:
                        result['名称'] = line.split(':', 1)[-1].strip()
                    if '类别' in line or 'Category' in line:
                        result['类别'] = line.split(':', 1)[-1].strip()
                    if '复杂度' in line or 'Complexity' in line:
                        result['复杂度'] = line.split(':', 1)[-1].strip()
        except:
            pass
        return result
    
    def _parse_diagram_info(self, info_str: str) -> Dict[str, Any]:
        """Parse diagram info string into structured data"""
        result = {'提取状态': '成功'}
        try:
            lines = info_str.split('\n')
            for line in lines:
                if '页数' in line or 'Pages' in line:
                    result['页数'] = line.split(':', 1)[-1].strip()
                if '尺寸' in line or 'Size' in line:
                    result['页面尺寸'] = line.split(':', 1)[-1].strip()
                if '当前页' in line or 'Current page' in line:
                    result['当前页'] = line.split(':', 1)[-1].strip()
        except:
            result['提取状态'] = '部分失败'
        return result
    
    def _parse_shapes_info(self, shapes_str: str) -> Dict[str, Any]:
        """Parse shapes list into structured analysis"""
        result = {
            '形状总数': 0,
            '形状类型分布': {},
            '连接器数量': 0,
            '形状示例': []
        }
        
        try:
            # Count total shapes
            if '找到' in shapes_str or 'Found' in shapes_str:
                import re
                match = re.search(r'(\d+)\s*个形状', shapes_str)
                if not match:
                    match = re.search(r'Found\s+(\d+)\s+shapes', shapes_str)
                if match:
                    result['形状总数'] = int(match.group(1))
            
            # Analyze shape types
            lines = shapes_str.split('\n')
            for line in lines:
                if 'Type=' in line or '类型=' in line:
                    # Extract shape type
                    type_match = re.search(r'Type=([^,\s]+)', line)
                    if type_match:
                        shape_type = type_match.group(1)
                        result['形状类型分布'][shape_type] = result['形状类型分布'].get(shape_type, 0) + 1
                        
                        if shape_type == 'Connector':
                            result['连接器数量'] += 1
        except:
            pass
        
        return result
    
    def _parse_connections_info(self, connections_str: str) -> Dict[str, Any]:
        """Parse connection analysis into structured data"""
        result = {
            '连接总数': 0,
            '连接模式': '未知',
            '拓扑类型': [],
            '连接特征': []
        }
        
        try:
            if '连接总数' in connections_str or 'Total connections' in connections_str:
                import re
                match = re.search(r'(\d+)\s*个连接', connections_str)
                if not match:
                    match = re.search(r'Total[:\s]+(\d+)', connections_str)
                if match:
                    result['连接总数'] = int(match.group(1))
            
            # Detect topology patterns
            if '线性' in connections_str or 'linear' in connections_str.lower():
                result['拓扑类型'].append('线性流程')
            if '树状' in connections_str or 'tree' in connections_str.lower():
                result['拓扑类型'].append('树状结构')
            if '网状' in connections_str or 'mesh' in connections_str.lower():
                result['拓扑类型'].append('网状结构')
            if '分支' in connections_str or 'branch' in connections_str.lower():
                result['连接特征'].append('多分支')
            
            if not result['拓扑类型']:
                result['拓扑类型'].append('通用型')
                
        except:
            pass
        
        return result
    
    def _parse_position_info(self, position_str: str) -> Dict[str, Any]:
        """Parse positioning data into layout analysis"""
        result = {
            '布局模式': '未知',
            '对齐方式': [],
            '间距特征': {},
            '布局方向': '未知'
        }
        
        try:
            # Detect layout patterns from positioning
            if '垂直' in position_str or 'vertical' in position_str.lower():
                result['布局方向'] = '垂直布局'
            elif '水平' in position_str or 'horizontal' in position_str.lower():
                result['布局方向'] = '水平布局'
            else:
                result['布局方向'] = '混合布局'
            
            # Check for alignment
            if '对齐' in position_str or 'align' in position_str.lower():
                result['对齐方式'].append('规则对齐')
            
            # Detect spacing patterns
            import re
            spacing_matches = re.findall(r'spacing[:\s]+([\d.]+)', position_str, re.IGNORECASE)
            if spacing_matches:
                result['间距特征']['平均间距'] = sum(float(x) for x in spacing_matches) / len(spacing_matches)
        
        except:
            pass
        
        return result
    
    def _generate_recommendation_logic(self, shapes: Dict, connections: Dict, positions: Dict) -> Dict[str, Any]:
        """Generate recommendation criteria based on analysis"""
        logic = {
            '适合场景': [],
            '结构优势': [],
            '可扩展性': '中等',
            '复杂度评分': 0
        }
        
        try:
            # Shape compatibility
            shape_count = shapes.get('形状总数', 0)
            if shape_count < 5:
                logic['适合场景'].append('简单流程')
                logic['复杂度评分'] = 1
            elif shape_count < 15:
                logic['适合场景'].append('中等复杂度图表')
                logic['复杂度评分'] = 3
            else:
                logic['适合场景'].append('复杂系统架构')
                logic['复杂度评分'] = 5
            
            # Connection pattern matching
            topology = connections.get('拓扑类型', [])
            if '线性流程' in topology:
                logic['结构优势'].append('清晰的步骤流程')
                logic['适合场景'].append('业务流程')
            if '树状结构' in topology:
                logic['结构优势'].append('层级关系展示')
                logic['适合场景'].append('组织架构')
            if '网状结构' in topology:
                logic['结构优势'].append('复杂关系网络')
                logic['适合场景'].append('系统依赖图')
            
            # Layout appropriateness
            layout_dir = positions.get('布局方向', '')
            if '垂直' in layout_dir:
                logic['结构优势'].append('垂直流程展示')
            elif '水平' in layout_dir:
                logic['结构优势'].append('水平分层架构')
            
            # Extensibility
            if shape_count > 0 and connections.get('连接总数', 0) / max(shape_count, 1) < 1.5:
                logic['可扩展性'] = '高 - 易于添加元素'
            elif connections.get('连接总数', 0) / max(shape_count, 1) > 2.5:
                logic['可扩展性'] = '低 - 结构较为固定'
            
        except:
            pass
        
        return logic


def get_prompt_tools(prompt_tools_instance: 'PromptTools') -> List:
    """
    Get list of Agno-compatible tool functions for prompt generation
    
    Args:
        prompt_tools_instance: Instance of PromptTools
        
    Returns:
        List of tool functions
    """
    return [
        # Template search and recommendation
        prompt_tools_instance.search_templates_by_requirement,
        prompt_tools_instance.search_stencils_by_requirement,
        prompt_tools_instance.rank_templates_for_requirement,
        prompt_tools_instance.analyze_template_for_recommendation,
        
        # 6-step template analysis (for prompt generation)
        prompt_tools_instance.get_template_info,                # Step 1: Metadata
        prompt_tools_instance.load_template_for_analysis,       # Step 2: Load
        prompt_tools_instance.get_diagram_info_from_loaded,     # Step 3: Diagram info
        prompt_tools_instance.list_shapes_from_loaded,          # Step 4: Shapes
        prompt_tools_instance.analyze_connections_from_loaded,  # Step 5: Connections
        prompt_tools_instance.list_position_from_loaded,        # Step 6: Positions
        prompt_tools_instance.cleanup_analysis_temp_files,      # Cleanup
        
        # Prompt generation and validation
        prompt_tools_instance.generate_prompt_from_template,
        prompt_tools_instance.validate_prompt_tools,
        prompt_tools_instance.get_available_visio_tools,
    ]
