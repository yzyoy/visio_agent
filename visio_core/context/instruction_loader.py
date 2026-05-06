"""
Skill-backed instruction loader.

The runtime model context is assembled from ``skills/<name>/SKILL.md``.
``load_template`` is kept as a compatibility API for callers that still use
the old instruction-template names.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


class InstructionLoader:
    """Load and compose model instructions from Agent Skill files."""

    def __init__(
        self,
        skills_dir: Optional[str] = None,
        templates_dir: Optional[str] = None,
    ):
        """
        Initialize the skill-backed instruction loader.

        Args:
            skills_dir: Directory containing skill folders. Defaults to
                ``<repo>/skills``.
            templates_dir: Deprecated compatibility argument. It is ignored;
                instructions are no longer loaded from txt templates.
        """
        del templates_dir
        if skills_dir is None:
            repo_root = Path(__file__).resolve().parents[2]
            skills_dir = str(repo_root / "skills")

        self.skills_dir = Path(skills_dir)

        self.available_skills = {
            "visio": "visio",
            "visio_core_execution": "visio-core-execution",
            "visio_prompt_generation": "visio-prompt-generation",
            "visio_requirement_analysis": "visio-requirement-analysis",
            "visio_template_evaluation": "visio-template-evaluation",
        }

        # Backward-compatible names used by older code paths.
        self.template_to_skill = {
            "core": "visio-core-execution",
            "visio_basics": "visio-core-execution",
            "constraints": "visio-core-execution",
            "chinese_mapping": "visio-core-execution",
            "workflows": "visio-core-execution",
            "prompt_generation": "visio-prompt-generation",
            "keyword_extraction": "visio-requirement-analysis",
            "requirement_analysis": "visio-requirement-analysis",
            "template_evaluation": "visio-template-evaluation",
        }
        self.available_templates = dict(self.template_to_skill)
        self._cache: Dict[str, Tuple[int, str]] = {}

    def load_skill(self, skill_name: str) -> str:
        """
        Load one skill file by folder name or registry key.

        Args:
            skill_name: Skill key or folder name, such as
                ``visio-core-execution``.

        Returns:
            The raw ``SKILL.md`` content.
        """
        folder_name = self.available_skills.get(skill_name, skill_name)
        cache_key = f"skill:{folder_name}"
        filepath = self.skills_dir / folder_name / "SKILL.md"
        try:
            mtime_ns = filepath.stat().st_mtime_ns
            cached = self._cache.get(cache_key)
            if cached and cached[0] == mtime_ns:
                return cached[1]

            content = filepath.read_text(encoding="utf-8").strip()
            self._cache[cache_key] = (mtime_ns, content)
            return content
        except Exception as e:
            print(f"❌ 加载 Skill 失败 '{folder_name}': {e}")
            return ""

    def load_template(self, template_name: str) -> str:
        """
        Compatibility shim for the old txt instruction-template API.

        The returned content is derived from skill files. Internal LLM prompts
        keep the old placeholder contract used by ``SmartMatcher``.
        """
        skill_name = self.template_to_skill.get(template_name)
        if not skill_name:
            print(f"⚠️ 警告: 未知的指令名称 '{template_name}'")
            return ""

        content = self.load_skill(skill_name)
        if not content:
            return ""

        if template_name in {"keyword_extraction", "requirement_analysis"}:
            content = self._build_requirement_analysis_prompt(content)
        elif template_name == "template_evaluation":
            content = self._build_template_evaluation_prompt(content)

        return content

    def build_instructions(
        self,
        profile: str = "default",
        include_chinese: bool = True,
        include_workflows: bool = False,
        include_prompt_gen: bool = True,
        library_stats: Optional[Dict[str, Any]] = None,
        template_list_preview: Optional[str] = None,
    ) -> List[str]:
        """
        Build the model instruction list from skills.

        The legacy switches are preserved for callers, but the core execution
        skill already contains Chinese mapping, constraints, and workflows.
        """
        del include_chinese, include_workflows
        skill_names = ["visio-core-execution"]

        if profile == "full":
            skill_names.append("visio")

        if include_prompt_gen:
            skill_names.append("visio-prompt-generation")

        instructions: List[str] = []
        seen = set()
        for skill_name in skill_names:
            if skill_name in seen:
                continue
            content = self.load_skill(skill_name)
            if content:
                instructions.append(content)
                seen.add(skill_name)

        if library_stats:
            instructions.append(self._format_library_stats(library_stats))

        if template_list_preview:
            instructions.append("\n" + "=" * 80)
            instructions.append("📚 当前可用模板（部分预览）：")
            instructions.append("=" * 80)
            instructions.append(template_list_preview)

        return instructions

    def _build_requirement_analysis_prompt(self, skill_content: str) -> str:
        return (
            f"{skill_content}\n\n"
            "## 本次用户需求\n"
            "用户需求描述：{chinese_text}\n\n"
            "请立即分析上述需求，并只返回一个可被 json.loads 解析的 JSON 对象；"
            "不要添加解释文字，不要使用 Markdown 代码块。"
        )

    def _build_template_evaluation_prompt(self, skill_content: str) -> str:
        return (
            f"{skill_content}\n\n"
            "## 用户需求信息\n\n"
            "**原始需求描述**：\n{user_requirement}\n\n"
            "**需求分析结果**：\n{requirement_analysis}\n\n"
            "## 候选模板列表\n\n"
            "{candidates_text}\n\n"
            "请按照上面的评分标准排序，返回前 {top_k} 个推荐。"
            "只返回一个可被 json.loads 解析的 JSON 对象；不要添加解释文字，"
            "不要使用 Markdown 代码块。"
        )

    def _format_library_stats(self, stats: Dict[str, Any]) -> str:
        """格式化模板库统计信息"""
        lines = [
            "📊 模板库统计：",
            f"  - 总模板数：{stats.get('total_templates', 0)}",
        ]

        if "by_category" in stats and stats["by_category"]:
            categories = ", ".join(
                f"{k}({v})" for k, v in list(stats["by_category"].items())[:5]
            )
            lines.append(f"  - 分类：{categories}")

        if "by_complexity" in stats and stats["by_complexity"]:
            complexity = ", ".join(
                f"{k}({v})" for k, v in stats["by_complexity"].items()
            )
            lines.append(f"  - 复杂度：{complexity}")

        return "\n".join(lines)

    def get_minimal_instructions(self, include_chinese: bool = True) -> List[str]:
        """获取最小化 skill 指令集"""
        return self.build_instructions(
            profile="minimal",
            include_chinese=include_chinese,
            include_workflows=False,
            include_prompt_gen=False,
        )

    def get_default_instructions(
        self,
        include_chinese: bool = True,
        library_stats: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """获取默认 skill 指令集"""
        return self.build_instructions(
            profile="default",
            include_chinese=include_chinese,
            include_workflows=False,
            include_prompt_gen=True,
            library_stats=library_stats,
        )

    def get_full_instructions(
        self,
        library_stats: Optional[Dict[str, Any]] = None,
        template_list_preview: Optional[str] = None,
    ) -> List[str]:
        """获取完整 skill 指令集"""
        return self.build_instructions(
            profile="full",
            include_chinese=True,
            include_workflows=True,
            include_prompt_gen=True,
            library_stats=library_stats,
            template_list_preview=template_list_preview,
        )

    def clear_cache(self):
        """清除缓存"""
        self._cache.clear()


# 全局实例（单例模式）
_global_loader: Optional[InstructionLoader] = None


def get_instruction_loader() -> InstructionLoader:
    """获取全局指令加载器实例"""
    global _global_loader
    if _global_loader is None:
        _global_loader = InstructionLoader()
    return _global_loader

