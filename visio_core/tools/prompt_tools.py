"""
Prompt generation tools for Visio diagram creation
Handles template recommendation and prompt generation
"""
import json
import os
import re
from pathlib import Path
from typing import List, Dict, Any, Optional
from typing import Any as _Any

from ..templates.template_manager import TemplateManager
from ..utils.smart_matcher import SmartMatcher
from ..utils.shape_identity import get_shape_prop


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

        We additionally apply *recommendation-friendly* sampling defaults
        (temperature=0, top_p=1, fixed seed) directly on the model when it
        exposes those attributes. ``SmartMatcher`` re-asserts these on every
        call via :func:`_deterministic_sampling`, so this is mostly an
        ergonomic hint — but it also means callers who reuse ``self.model``
        outside SmartMatcher inherit deterministic defaults rather than the
        provider's default sampling, which was the historical source of
        ``recommend_template`` jitter.
        """
        self.model = model
        # Best-effort: nudge the underlying chat client to greedy decoding
        # so the rest of the recommendation pipeline (and any downstream
        # tool that reuses the same model handle) is reproducible.
        for attr, value in (
            ("temperature", 0.0),
            ("top_p", 1.0),
            ("seed", 42),
        ):
            if hasattr(model, attr):
                try:
                    setattr(model, attr, value)
                except Exception:
                    # Read-only / pydantic frozen models — silently skip;
                    # SmartMatcher's per-call wrapper still enforces these.
                    pass

    def _preview_markdown(self, template_path: str) -> str:
        filename = os.path.basename(template_path)
        return f"[{filename}](http://localhost:7777/api/visio/preview?path={template_path})"

    def _build_basic_recommendations(
        self,
        items: List[Dict[str, Any]],
        search_type: str,
        top_k: int,
    ) -> List[Dict[str, Any]]:
        recommendations: List[Dict[str, Any]] = []
        base_dir = "assets/templates/library" if search_type == "template" else "assets/templates/stencils"

        for index, item in enumerate(items[:top_k], 1):
            path = item.get("path") or item.get("full_path") or ""
            if not path:
                path = f"{base_dir}/{item.get('filename', '')}".rstrip("/")

            recommendation = {
                "rank": index,
                "filename": item.get("filename", ""),
                "path": path,
                "score": round(float(item.get("llm_score", item.get("match_score", item.get("combined_score", 0))) or 0), 3),
                "description": item.get("structure_description", item.get("description", "")),
            }
            if search_type == "template":
                recommendation["preview"] = self._preview_markdown(path)
            recommendations.append(recommendation)

        return recommendations

    def _build_recommendation_payload(
        self,
        *,
        user_requirement: str,
        search_type: str,
        keywords: List[str],
        recommendations: List[Dict[str, Any]],
        warnings: List[str],
        fallback_used: bool,
        error_code: Optional[str],
    ) -> Dict[str, Any]:
        search_type_name = "模板" if search_type == "template" else "形状库"
        status = "ok"
        if error_code and not recommendations:
            status = "error"
        elif warnings or fallback_used:
            status = "warning"

        payload = {
            "status": status,
            "search_type": search_type,
            "requirement": user_requirement,
            "keywords": keywords,
            "recommendations": recommendations,
            "warnings": warnings,
            "fallback_used": fallback_used,
            "error_code": error_code,
            # Backward-compatible fields for existing chat flows.
            "搜索类型": search_type_name,
            "推荐列表": recommendations,
        }
        return payload

    def _keyword_fallback_payload(
        self,
        *,
        user_requirement: str,
        search_type: str,
        top_k: int,
        reason: str,
        error_code: Optional[str],
    ) -> Dict[str, Any]:
        fallback = self.smart_matcher.keyword_only_match(
            user_input=user_requirement,
            search_type=search_type,
            top_k=top_k,
            reason=reason,
            error_code=error_code,
        )
        if search_type == "template" and not fallback.get("recommendations"):
            template_count = len(getattr(self.template_manager, "library", {}) or {})
            if template_count == 0:
                fallback.setdefault("warnings", []).append("Template library is empty.")
                fallback["error_code"] = fallback.get("error_code") or "LIBRARY_EMPTY"
                fallback["status"] = "error"
        return fallback

    def _tool_call_status(self, result: str) -> Dict[str, Any]:
        message = result or ""
        stripped = message.lstrip()
        success = bool(stripped) and not stripped.startswith("✗")
        return {"success": success, "message": message}
    
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
    
    def recommend_template(self, requirement: str, top_k: int = 5) -> str:
        """Recommend templates from a natural-language requirement.

        This is the canonical LLM-facing recommendation surface used by the
        consolidated 16-tool contract. It prefers the SmartMatcher semantic
        path and degrades into a structured keyword fallback when the model is
        unavailable or the semantic path fails.

        Determinism notes:
          * ``SmartMatcher`` is invoked under deterministic sampling
            (temperature=0, fixed seed) and applies stable tiebreakers, so
            repeat calls with the same ``requirement`` produce identical
            output.
          * ``SmartMatcher`` also memoizes the resulting payload in a small
            in-memory LRU keyed on the *normalized* requirement, which makes
            short-term retries free and byte-stable. Set
            ``VISIO_RECOMMENDATION_CACHE_DISABLED=1`` to bypass the cache
            during reproducibility audits.
        """
        # Normalise trivially before forwarding so a stray space at the end
        # of the user prompt does not invalidate the cache. SmartMatcher
        # applies its own stricter normalisation when computing the key, but
        # this also keeps the value of ``requirement`` in the response stable.
        requirement = (requirement or "").strip()
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            top_k = 5
        top_k = max(1, min(top_k, 20))

        if self.model:
            try:
                result = self.smart_matcher.smart_match(
                    requirement,
                    self.model,
                    search_type="template",
                    top_k=top_k,
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            except Exception as exc:
                print(f"⚠ recommend_template semantic path failed, using fallback: {exc}")
                fallback = self._keyword_fallback_payload(
                    user_requirement=requirement,
                    search_type="template",
                    top_k=top_k,
                    reason=f"Semantic recommendation failed: {exc}",
                    error_code="MODEL_UNAVAILABLE",
                )
                return json.dumps(fallback, ensure_ascii=False, indent=2)

        fallback = self._keyword_fallback_payload(
            user_requirement=requirement,
            search_type="template",
            top_k=top_k,
            reason="No LLM model configured for semantic recommendation; using keyword fallback.",
            error_code="MODEL_UNAVAILABLE",
        )
        return json.dumps(fallback, ensure_ascii=False, indent=2)

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
        if use_smart_match:
            return self.recommend_template(user_requirement, top_k=5)

        fallback = self._keyword_fallback_payload(
            user_requirement=user_requirement,
            search_type="template",
            top_k=5,
            reason="Smart match disabled; using keyword fallback.",
            error_code=None,
        )
        return json.dumps(fallback, ensure_ascii=False, indent=2)
    
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
        import tempfile

        analysis_result: Dict[str, Any] = {
            "status": "ok",
            "partial": False,
            "template_path": template_path,
            "warnings": [],
            "error_code": None,
            "info": {},
            "shapes": [],
            "connections": [],
            "positions": [],
            "groups": [],
            "topology": {},
            # Backward-compatible fields for existing consumers.
            "模板路径": template_path,
            "分析状态": {},
            "元数据信息": {},
            "图表信息": {},
            "形状分析": {},
            "连接分析": {},
            "位置分析": {},
            "推荐依据": {},
        }

        visio_tools = VisioTools(auto_restore=False, record_context=False)
        temp_output = None

        try:
            metadata_str = visio_tools.get_template_info(template_path)
            metadata_status = self._tool_call_status(metadata_str)
            analysis_result["分析状态"]["步骤1_元数据提取"] = "完成" if metadata_status["success"] else metadata_status["message"]
            analysis_result["元数据信息"] = self._parse_template_info(metadata_str)

            temp_output = os.path.join(tempfile.gettempdir(), f"temp_analysis_{os.path.basename(template_path)}")
            load_result = visio_tools.create_from_template_and_load(template_path, temp_output)
            load_status = self._tool_call_status(load_result)
            analysis_result["分析状态"]["步骤2_加载模板"] = "完成" if load_status["success"] else load_status["message"]
            if not load_status["success"]:
                analysis_result["status"] = "error"
                analysis_result["partial"] = True
                analysis_result["error_code"] = "FILE_NOT_FOUND"
                analysis_result["warnings"].append(load_status["message"])
                return json.dumps(analysis_result, ensure_ascii=False, indent=2)

            reload_result = visio_tools.load_diagram(temp_output)
            reload_status = self._tool_call_status(reload_result)
            analysis_result["分析状态"]["步骤2_重新加载"] = "完成" if reload_status["success"] else reload_status["message"]
            if not reload_status["success"]:
                analysis_result["status"] = "error"
                analysis_result["partial"] = True
                analysis_result["error_code"] = "PARSE_FAILED"
                analysis_result["warnings"].append(reload_status["message"])
                return json.dumps(analysis_result, ensure_ascii=False, indent=2)

            builder = visio_tools.diagram_builder
            if not builder or not builder.current_page:
                analysis_result["status"] = "error"
                analysis_result["partial"] = True
                analysis_result["error_code"] = "PARSE_FAILED"
                analysis_result["warnings"].append("Template loaded but no active page was available for analysis.")
                return json.dumps(analysis_result, ensure_ascii=False, indent=2)

            diagram_info = builder.get_diagram_info()
            flat_shapes, group_tree = self._collect_shapes_and_groups(
                list(getattr(builder.current_page, "child_shapes", []) or [])
            )
            connections_analysis = builder.analyze_diagram_connections(include_connectors=True)

            analysis_result["info"] = {
                "template_path": template_path,
                "pages": diagram_info.get("pages", []),
                "current_page": diagram_info.get("current_page"),
                "shapes_count": len(flat_shapes),
                "connector_count": diagram_info.get("connector_count", 0),
                "metadata": analysis_result["元数据信息"],
            }
            analysis_result["shapes"] = flat_shapes
            analysis_result["positions"] = [
                {
                    "id": shape["id"],
                    "node_key": shape.get("node_key"),
                    "x": shape.get("x"),
                    "y": shape.get("y"),
                    "width": shape.get("width"),
                    "height": shape.get("height"),
                    "parent_group_id": shape.get("parent_group_id"),
                }
                for shape in flat_shapes
            ]
            analysis_result["groups"] = group_tree

            shapes_by_id = {shape["id"]: shape for shape in flat_shapes}
            if connections_analysis.get("error"):
                analysis_result["partial"] = True
                analysis_result["status"] = "warning"
                analysis_result["warnings"].append(
                    f"Connection analysis degraded: {connections_analysis['error']}"
                )
                analysis_result["error_code"] = "PARSE_FAILED"
            else:
                analysis_result["connections"] = self._canonicalize_connections(
                    connections_analysis.get("connectors", []),
                    shapes_by_id,
                )
                analysis_result["topology"] = {
                    "page_name": connections_analysis.get("page_name"),
                    "statistics": connections_analysis.get("statistics", {}),
                    "connection_graph": connections_analysis.get("connection_graph", {}),
                    "group_count": len(group_tree),
                    "has_groups": bool(group_tree),
                }

            if not analysis_result["shapes"]:
                analysis_result["partial"] = True
                analysis_result["status"] = "warning"
                analysis_result["warnings"].append("No shapes were detected in the analyzed template.")

            analysis_result["图表信息"] = {
                "页数": len(analysis_result["info"]["pages"]),
                "当前页": analysis_result["info"]["current_page"],
                "形状数量": analysis_result["info"]["shapes_count"],
                "连接器数量": analysis_result["info"]["connector_count"],
            }
            analysis_result["形状分析"] = {
                "形状总数": len(flat_shapes),
                "形状类型分布": self._count_shape_types(flat_shapes),
                "连接器数量": analysis_result["info"]["connector_count"],
                "分组数量": len(group_tree),
            }
            analysis_result["连接分析"] = {
                "连接总数": len(analysis_result["connections"]),
                "连接模式": "结构化分析",
                "拓扑类型": self._infer_topology_labels(analysis_result["topology"].get("statistics", {})),
                "连接特征": [],
            }
            analysis_result["位置分析"] = {
                "布局模式": "结构化分析",
                "对齐方式": [],
                "间距特征": {},
                "布局方向": self._infer_layout_direction(flat_shapes),
            }
            analysis_result["推荐依据"] = self._generate_recommendation_logic(
                analysis_result["形状分析"],
                analysis_result["连接分析"],
                analysis_result["位置分析"],
            )
            analysis_result["分析状态"]["总体状态"] = "成功完成" if analysis_result["status"] == "ok" else "部分完成"

        except Exception as exc:
            analysis_result["status"] = "error"
            analysis_result["partial"] = True
            analysis_result["error_code"] = "PARSE_FAILED"
            analysis_result["分析状态"]["错误"] = str(exc)
            analysis_result["分析状态"]["总体状态"] = "失败"
            analysis_result["warnings"].append(f"Analysis failed: {exc}")

        finally:
            if cleanup and temp_output and os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                    analysis_result["分析状态"]["清理"] = "已清理临时文件"
                except Exception as exc:
                    analysis_result["partial"] = True
                    if analysis_result["status"] == "ok":
                        analysis_result["status"] = "warning"
                    analysis_result["warnings"].append(f"Temporary cleanup failed: {exc}")

        return json.dumps(analysis_result, ensure_ascii=False, indent=2)

    def _shape_snapshot(self, shape: Any, parent_group_id: Optional[str] = None) -> Dict[str, Any]:
        shape_id = str(getattr(shape, "ID", ""))
        text = (getattr(shape, "text", "") or "").strip()
        shape_type = getattr(shape, "shape_type", "") or "Unknown"
        master = getattr(shape, "master", None)
        if shape_type == "Unknown" and master is not None:
            shape_type = getattr(master, "name", "") or "Unknown"

        x = getattr(shape, "x", None)
        y = getattr(shape, "y", None)
        width = getattr(shape, "width", None)
        height = getattr(shape, "height", None)
        return {
            "id": shape_id,
            "text": text,
            "node_key": get_shape_prop(shape, "NodeKey") or "",
            "type": shape_type,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "parent_group_id": parent_group_id,
            "is_group": bool(getattr(shape, "shape_type", "").lower() == "group" and hasattr(shape, "child_shapes")),
        }

    def _collect_shapes_and_groups(
        self,
        shapes: List[Any],
        parent_group_id: Optional[str] = None,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        flat_shapes: List[Dict[str, Any]] = []
        groups: List[Dict[str, Any]] = []

        for shape in shapes:
            snapshot = self._shape_snapshot(shape, parent_group_id=parent_group_id)
            flat_shapes.append(snapshot)
            if snapshot["is_group"]:
                child_flat, child_groups = self._collect_shapes_and_groups(
                    list(getattr(shape, "child_shapes", []) or []),
                    parent_group_id=snapshot["id"],
                )
                flat_shapes.extend(child_flat)
                groups.append(
                    {
                        "id": snapshot["id"],
                        "text": snapshot["text"],
                        "node_key": snapshot["node_key"],
                        "child_shape_ids": [
                            child["id"]
                            for child in child_flat
                            if child.get("parent_group_id") == snapshot["id"]
                        ],
                        "children": child_groups,
                    }
                )

        return flat_shapes, groups

    def _canonicalize_connections(
        self,
        connectors: List[Dict[str, Any]],
        shapes_by_id: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        canonical = []
        for connector in connectors:
            from_shape_id = connector.get("from_shape_id")
            to_shape_id = connector.get("to_shape_id")
            canonical.append(
                {
                    "connector_id": connector.get("connector_id"),
                    "label": connector.get("connector_text", ""),
                    "from_shape_id": from_shape_id,
                    "to_shape_id": to_shape_id,
                    "from_node_key": shapes_by_id.get(str(from_shape_id), {}).get("node_key", ""),
                    "to_node_key": shapes_by_id.get(str(to_shape_id), {}).get("node_key", ""),
                    "from_text": connector.get("from_shape_text", ""),
                    "to_text": connector.get("to_shape_text", ""),
                }
            )
        return canonical

    def _count_shape_types(self, flat_shapes: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for shape in flat_shapes:
            shape_type = shape.get("type", "Unknown") or "Unknown"
            counts[shape_type] = counts.get(shape_type, 0) + 1
        return counts

    def _infer_topology_labels(self, statistics: Dict[str, Any]) -> List[str]:
        labels: List[str] = []
        total_connections = statistics.get("total_connections", 0)
        isolated_shapes = statistics.get("isolated_shapes", 0)
        if total_connections == 0:
            labels.append("孤立节点")
        if statistics.get("shapes_with_both", 0):
            labels.append("线性流程")
        if isolated_shapes == 0 and total_connections:
            labels.append("连通结构")
        return labels or ["通用型"]

    def _infer_layout_direction(self, flat_shapes: List[Dict[str, Any]]) -> str:
        xs = [shape["x"] for shape in flat_shapes if isinstance(shape.get("x"), (int, float))]
        ys = [shape["y"] for shape in flat_shapes if isinstance(shape.get("y"), (int, float))]
        if len(xs) < 2 or len(ys) < 2:
            return "未知"
        x_span = max(xs) - min(xs)
        y_span = max(ys) - min(ys)
        if y_span > x_span * 1.25:
            return "垂直布局"
        if x_span > y_span * 1.25:
            return "水平布局"
        return "混合布局"
    
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
        except Exception as exc:
            result['parse_warning'] = str(exc)
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
        except Exception as exc:
            result['提取状态'] = '部分失败'
            result['parse_warning'] = str(exc)
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
        except Exception as exc:
            result['parse_warning'] = str(exc)
        
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
                
        except Exception as exc:
            result['parse_warning'] = str(exc)
        
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
        
        except Exception as exc:
            result['parse_warning'] = str(exc)
        
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
            
        except Exception as exc:
            logic['parse_warning'] = str(exc)
        
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
