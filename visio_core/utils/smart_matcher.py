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

import hashlib
import json
import logging
import os
import re
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .library_cache import get_library_cache
from ..context.instruction_loader import get_instruction_loader

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Determinism knobs.
#
# ``recommend_template`` used to drift between runs because the underlying
# OpenAI-compatible model was called with default sampling (temperature ~1.0,
# no fixed seed). For a *recommendation* surface we explicitly want the same
# input to map to the same output, so we force greedy decoding and a fixed
# seed whenever the injected model exposes those attributes (agno's
# ``OpenAIChat`` does — see ``apps/agent_os.py``).
#
# These values are deliberately conservative: temperature=0 + top_p=1 +
# fixed seed is the standard recipe for "make this LLM call as deterministic
# as the provider allows" without destroying retries on transient failures.
# ---------------------------------------------------------------------------
_DETERMINISTIC_TEMPERATURE = 0.0
_DETERMINISTIC_TOP_P = 1.0
_DETERMINISTIC_SEED = 42

# Toggle the recommendation cache via env var for offline replay / debugging.
_CACHE_DISABLED_ENV = "VISIO_RECOMMENDATION_CACHE_DISABLED"
# Bound the in-memory cache so a long-lived agent process does not grow
# without limit. 256 distinct prompts is more than enough for interactive
# sessions; cache keys are normalized so semantically equivalent requirements
# collapse to the same entry.
_CACHE_MAX_ENTRIES = 256

_GENERIC_RECOMMENDATION_TERMS = {
    "architecture",
    "architecture diagram",
    "chart",
    "diagram",
    "flow",
    "flowchart",
    "layout",
    "process",
    "solution",
    "structure",
    "system",
    "template",
    "topology",
    "visio",
    "workflow",
    "业务流程",
    "图",
    "图表",
    "工作流",
    "架构",
    "架构图",
    "模板",
    "流程",
    "流程图",
    "示意图",
    "系统",
    "网络",
    "网络图",
    "组织",
    "组织图",
    "时序",
    "时序图",
}

_REQUEST_FILLER_PATTERNS: Tuple[str, ...] = (
    r"\bplease\b",
    r"\bneed\b",
    r"\bwant\b",
    r"\bhelp\b",
    r"\bmake\b",
    r"\bcreate\b",
    r"\bbuild\b",
    r"\bdraw\b",
    r"\bgenerate\b",
    r"\bshow\b",
    r"\bfind\b",
    r"\bsearch\b",
    r"\brecommend\b",
    r"帮我",
    r"帮忙",
    r"请帮",
    r"我想",
    r"我要",
    r"我需要",
    r"需要",
    r"想要",
    r"画个",
    r"画一个",
    r"做个",
    r"做一个",
    r"创建",
    r"生成",
    r"设计",
    r"推荐",
    r"搜索",
    r"查找",
)

_GENERIC_SUFFIXES: Tuple[str, ...] = (
    "流程图",
    "架构图",
    "网络图",
    "组织图",
    "时序图",
    "示意图",
    "图表",
    "模板",
    "流程",
    "架构",
    "网络",
    "组织",
    "系统",
    "方案",
    "场景",
    "图",
)


def _build_user_message(content: str) -> Any:
    """Build a user message accepted by agno's ``model.response([msg])``.

    Newer agno versions invoke ``message.log(metrics=False)`` and may rely on
    additional fields/methods on its own ``Message`` dataclass. Prefer the real
    class when available, and fall back to a duck-typed shim otherwise. The
    shim exposes ``log``/``to_dict`` no-ops so it stays compatible across
    minor agno upgrades without forcing this module to hard-depend on agno.
    """
    try:
        from agno.models.message import Message  # type: ignore

        return Message(role="user", content=content)
    except Exception:
        return _UserMessage(content)


class _UserMessage:
    """Minimal duck-typed message compatible with agno's ``model.response()``.

    Kept local so this module does not require ``import agno`` at import time.
    Includes ``log``/``to_dict`` no-ops because recent agno releases call
    ``message.log(metrics=False)`` on every input message before dispatch.
    """

    __slots__ = ("role", "content", "name", "tool_call_id", "tool_calls")

    def __init__(self, content: str):
        self.role = "user"
        self.content = content
        self.name = None
        self.tool_call_id = None
        self.tool_calls = None

    def log(self, *args: Any, **kwargs: Any) -> None:
        """No-op log hook used by agno's ``_log_messages``."""
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {"role": self.role, "content": self.content}


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
        response = model.response([_build_user_message(prompt)])
        return str(getattr(response, "content", response))
    raise TypeError(
        f"Unsupported LLM model of type {type(model).__name__}: expected "
        "either a .complete(prompt) -> str or a .response([msg]) -> obj "
        "with .content callable."
    )


@contextmanager
def _deterministic_sampling(model: Any):
    """Temporarily force greedy / fixed-seed sampling on ``model``.

    Many agno / OpenAI-compatible chat models expose ``temperature``,
    ``top_p`` and ``seed`` as plain attributes. We swap them to deterministic
    values for the duration of a recommendation call and restore the prior
    values on exit so we don't perturb other tools that rely on the same
    model instance (e.g. the planner).

    The context manager is silent when the attributes are not present —
    ``recommend_template`` still works with toy/test models that only
    implement ``complete()``.
    """
    if model is None:
        yield
        return

    saved: Dict[str, Any] = {}
    deterministic_values = {
        "temperature": _DETERMINISTIC_TEMPERATURE,
        "top_p": _DETERMINISTIC_TOP_P,
        "seed": _DETERMINISTIC_SEED,
    }

    for attr, value in deterministic_values.items():
        if hasattr(model, attr):
            try:
                saved[attr] = getattr(model, attr)
                setattr(model, attr, value)
            except Exception:  # pragma: no cover - defensive: read-only attr
                saved.pop(attr, None)

    try:
        yield
    finally:
        for attr, original in saved.items():
            try:
                setattr(model, attr, original)
            except Exception:  # pragma: no cover
                pass


def _complete_deterministic(model: Any, prompt: str) -> str:
    """Deterministic wrapper around :func:`_complete`.

    Wraps the LLM invocation with :func:`_deterministic_sampling` so the
    same prompt yields the same response across runs whenever the provider
    honors the ``seed`` parameter (DeepSeek and OpenAI both do).
    """
    with _deterministic_sampling(model):
        return _complete(model, prompt)


def _normalize_requirement(text: str) -> str:
    """Canonical form used for cache keys.

    We collapse whitespace and strip punctuation noise so that semantically
    equivalent re-phrasings (extra spaces, trailing periods, mixed case for
    English fragments) collapse to the same cache entry.
    """
    if not text:
        return ""
    # Remove runs of whitespace; preserve CJK characters as-is.
    collapsed = re.sub(r"\s+", " ", text.strip())
    # Drop trailing punctuation that doesn't change intent.
    collapsed = collapsed.rstrip("。.!?！？,，;；:：")
    return collapsed.lower()


def _cache_key(requirement: str, search_type: str, top_k: int) -> str:
    payload = json.dumps(
        {
            "r": _normalize_requirement(requirement),
            "t": search_type,
            "k": int(top_k),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


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

        # Recommendation result cache. Keyed by a hash of
        # (normalized requirement, search_type, top_k); bounded LRU.
        # Disable via env var when reproducing intermittent issues.
        self._reco_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._reco_cache_disabled = bool(
            os.environ.get(_CACHE_DISABLED_ENV, "").strip()
        )

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

    def _dedupe_terms(self, items: List[str]) -> List[str]:
        """Return terms with order preserved."""
        seen = set()
        result: List[str] = []
        for item in items:
            term = self._clean_term(item)
            if not term:
                continue
            key = self._normalize_search_text(term)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(term)
        return result

    def _clean_term(self, value: Any) -> str:
        """Normalize a candidate term without losing semantic text."""
        if value is None:
            return ""
        term = str(value).strip().strip("'\"`[](){}")
        term = re.sub(r"\s+", " ", term)
        return term.strip()

    def _coerce_text_list(self, value: Any) -> List[str]:
        """Accept list / csv-like strings and return cleaned text items."""
        if value is None:
            return []
        if isinstance(value, list):
            raw_items = value
        elif isinstance(value, str):
            raw_items = re.split(r"[,，;/\n]+", value)
        else:
            raw_items = [value]
        return self._dedupe_terms([str(item) for item in raw_items])

    def _normalize_search_text(self, text: str) -> str:
        """Canonical text form used for containment matching."""
        if not text:
            return ""
        normalized = str(text).strip().lower()
        normalized = re.sub(r"[_/\\-]+", " ", normalized)
        normalized = re.sub(r"[^\w\u4e00-\u9fff\s]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _compact_search_text(self, text: str) -> str:
        """Compact searchable text by dropping spaces / punctuation noise."""
        return re.sub(r"[\W_]+", "", self._normalize_search_text(text))

    def _is_generic_term(self, term: str) -> bool:
        """Whether a term is too generic to act as a must-match gate."""
        normalized = self._normalize_search_text(term)
        compact = normalized.replace(" ", "")
        return normalized in _GENERIC_RECOMMENDATION_TERMS or compact in _GENERIC_RECOMMENDATION_TERMS

    def _term_in_user_input(self, term: str, user_input: str) -> bool:
        """Check whether a grounded term appears in the original user text."""
        normalized_term = self._normalize_search_text(term)
        normalized_input = self._normalize_search_text(user_input)
        if not normalized_term or not normalized_input:
            return False
        if normalized_term in normalized_input:
            return True
        return self._compact_search_text(normalized_term) in self._compact_search_text(normalized_input)

    def _trim_generic_suffixes(self, term: str) -> List[str]:
        """Derive tighter user-grounded variants by removing generic suffixes."""
        variants: List[str] = []
        cleaned = self._clean_term(term)
        for suffix in _GENERIC_SUFFIXES:
            if cleaned.endswith(suffix):
                trimmed = cleaned[: -len(suffix)].strip(" 的-_")
                if len(trimmed) >= 2 and not self._is_generic_term(trimmed):
                    variants.append(trimmed)
        return self._dedupe_terms(variants)

    def _heuristic_grounded_terms(self, user_input: str) -> List[str]:
        """Extract user-grounded domain phrases without inventing new terms."""
        text = self._clean_term(user_input)
        if not text:
            return []

        candidates: List[str] = []

        for quoted in re.findall(r"[\"“”'‘’「『](.+?)[\"“”'‘’」』]", text):
            if not self._is_generic_term(quoted):
                candidates.append(quoted)

        cleaned = text
        for pattern in _REQUEST_FILLER_PATTERNS:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

        english_phrases = re.findall(
            r"[A-Za-z0-9][A-Za-z0-9.+/_-]*(?:\s+[A-Za-z0-9][A-Za-z0-9.+/_-]*){0,3}",
            cleaned,
        )
        for phrase in english_phrases:
            cleaned_phrase = self._clean_term(phrase)
            cleaned_phrase = re.sub(r"^(a|an|the)\s+", "", cleaned_phrase, flags=re.IGNORECASE)
            cleaned_phrase = re.sub(
                r"\b(flowchart|workflow|process|diagram|chart|template)\b$",
                "",
                cleaned_phrase,
                flags=re.IGNORECASE,
            ).strip()
            if cleaned_phrase and not self._is_generic_term(cleaned_phrase):
                candidates.append(cleaned_phrase)

        segments = re.split(r"[，,。.!?；;：:\n/]+", cleaned)
        for segment in segments:
            segment = self._clean_term(segment)
            if not segment or not re.search(r"[\u4e00-\u9fff]", segment):
                continue
            segment = segment.strip(" 的")
            if not segment or self._is_generic_term(segment):
                continue
            candidates.append(segment)
            candidates.extend(self._trim_generic_suffixes(segment))

        return self._dedupe_terms(candidates)[:6]

    def _build_searchable_text(self, item_data: Dict[str, Any]) -> str:
        """Flatten template metadata into a single normalized search field."""
        searchable_parts = [
            item_data.get('filename', ''),
            item_data.get('name', ''),
            item_data.get('category', ''),
            ' '.join(item_data.get('keywords', [])),
            ' '.join(item_data.get('use_cases', [])),
            ' '.join(item_data.get('sample_texts', [])[:20]),
        ]

        if 'shape_types' in item_data:
            searchable_parts.append(' '.join(item_data.get('shape_types', [])))
        if 'master_names' in item_data:
            searchable_parts.append(' '.join(item_data.get('master_names', [])[:50]))

        return self._normalize_search_text(' '.join(searchable_parts))

    def _is_chinese_request(self, user_input: str) -> bool:
        """Return True when the original request contains CJK text."""
        return bool(re.search(r"[\u4e00-\u9fff]", user_input or ""))

    def _template_language_preference_score(
        self,
        item_data: Dict[str, Any],
        user_input: str,
        search_type: str = "template",
    ) -> float:
        """Prefer Chinese, blank, and generic templates for Chinese requests."""
        if search_type != "template" or not self._is_chinese_request(user_input):
            return 0.0

        filename = str(item_data.get("filename", ""))
        name = str(item_data.get("name", ""))
        category = str(item_data.get("category", ""))
        path = str(item_data.get("path", item_data.get("full_path", "")))
        keywords = " ".join(self._coerce_text_list(item_data.get("keywords")))
        use_cases = " ".join(self._coerce_text_list(item_data.get("use_cases")))
        sample_texts = self._coerce_text_list(item_data.get("sample_texts"))
        sample_blob = " ".join(sample_texts[:20])
        identity_text = " ".join([filename, name, category, path])
        searchable = self._normalize_search_text(
            " ".join([identity_text, keywords, use_cases, sample_blob])
        )

        score = 0.0
        if re.search(r"[\u4e00-\u9fff]", identity_text):
            score += 0.38
        if re.search(r"[\u4e00-\u9fff]", sample_blob):
            score += 0.18

        generic_terms = (
            "blank", "empty", "basic", "generic", "general", "simple",
            "standard", "common", "template", "flowchart", "workflow",
            "process", "diagram", "starter", "default",
            "空白", "通用", "基础", "基本", "标准", "简单", "流程",
            "流程图", "模板",
        )
        if any(term in searchable for term in generic_terms):
            score += 0.24

        non_empty_samples = [text for text in sample_texts if str(text).strip()]
        if not non_empty_samples:
            score += 0.16
        elif len(non_empty_samples) <= 4 and max((len(str(t)) for t in non_empty_samples), default=0) <= 24:
            score += 0.08

        english_industry_terms = (
            "property", "buying", "agent", "loan", "contract", "underwriting",
            "purchase", "mortgage", "inspection", "survey", "closing",
            "customer", "sales", "marketing", "invoice", "vendor", "supplier",
            "insurance", "banking", "recruiting", "hiring", "healthcare",
            "patient", "manufacturing", "warehouse", "shipping", "legal",
        )
        user_normalized = self._normalize_search_text(user_input)
        industry_hits = [
            term for term in english_industry_terms
            if term in searchable and term not in user_normalized
        ]
        has_cjk_metadata = bool(re.search(r"[\u4e00-\u9fff]", " ".join([identity_text, sample_blob])))
        if industry_hits and not has_cjk_metadata:
            score -= min(0.55, 0.22 + 0.07 * len(industry_hits))

        if sample_blob and not re.search(r"[\u4e00-\u9fff]", sample_blob):
            english_words = re.findall(r"[A-Za-z]{3,}", sample_blob)
            if len(english_words) >= 8 and not any(term in user_normalized for term in english_words[:12]):
                score -= 0.18

        return max(-0.65, min(0.85, score))

    def _evaluate_must_match_groups(
        self,
        item_data: Dict[str, Any],
        must_match_alias_groups: Optional[List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Evaluate whether an item satisfies all user-grounded core terms."""
        groups = list(must_match_alias_groups or [])
        if not groups:
            return {
                "passes": True,
                "match_count": 0,
                "coverage": 1.0,
                "matched_sources": [],
            }

        searchable_text = self._build_searchable_text(item_data)
        compact_searchable = self._compact_search_text(searchable_text)
        matched_sources: List[str] = []

        for group in groups:
            aliases = self._coerce_text_list(group.get("aliases", []))
            if not aliases:
                continue

            hit = False
            for alias in aliases:
                normalized_alias = self._normalize_search_text(alias)
                compact_alias = self._compact_search_text(alias)
                if not normalized_alias:
                    continue
                if normalized_alias in searchable_text or (compact_alias and compact_alias in compact_searchable):
                    hit = True
                    break

            if hit:
                matched_sources.append(group.get("source", ""))

        total_groups = len(groups)
        match_count = len(matched_sources)
        return {
            "passes": match_count == total_groups,
            "match_count": match_count,
            "coverage": (match_count / total_groups) if total_groups else 1.0,
            "matched_sources": [src for src in matched_sources if src],
        }

    def _build_requirement_profile(
        self,
        user_input: str,
        extracted_keywords: List[str],
        analysis: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Separate grounded core terms from broad recall / ranking keywords."""
        analysis = dict(analysis or {})

        heuristic_grounded_terms = self._heuristic_grounded_terms(user_input)
        grounded_terms = [
            term
            for term in self._coerce_text_list(analysis.get("grounded_terms")) + heuristic_grounded_terms
            if self._term_in_user_input(term, user_input) and not self._is_generic_term(term)
        ]
        grounded_terms = self._dedupe_terms(
            grounded_terms + [variant for term in grounded_terms for variant in self._trim_generic_suffixes(term)]
        )

        validated_groups: List[Dict[str, Any]] = []
        raw_groups = analysis.get("must_match_alias_groups") or []
        if isinstance(raw_groups, dict):
            raw_groups = [
                {"source": source, "aliases": aliases}
                for source, aliases in raw_groups.items()
            ]

        for raw_group in raw_groups:
            if not isinstance(raw_group, dict):
                continue

            source = self._clean_term(raw_group.get("source") or raw_group.get("term"))
            if not source or self._is_generic_term(source) or not self._term_in_user_input(source, user_input):
                continue

            aliases = self._coerce_text_list(raw_group.get("aliases"))
            aliases = self._dedupe_terms(
                [source]
                + self._trim_generic_suffixes(source)
                + [alias for alias in aliases if not self._is_generic_term(alias)]
            )
            if aliases:
                validated_groups.append({"source": source, "aliases": aliases})

        if not validated_groups:
            preferred_grounded_terms = [
                term
                for term in grounded_terms
                if not any(term.endswith(suffix) for suffix in _GENERIC_SUFFIXES)
            ]
            fallback_sources = (
                self._coerce_text_list(analysis.get("must_match_terms"))
                or preferred_grounded_terms
                or grounded_terms
            )
            for source in fallback_sources:
                if not source or self._is_generic_term(source) or not self._term_in_user_input(source, user_input):
                    continue
                aliases = self._dedupe_terms([source] + self._trim_generic_suffixes(source))
                if aliases:
                    validated_groups.append({"source": source, "aliases": aliases})

        validated_groups = validated_groups[:3]
        must_match_terms = [group["source"] for group in validated_groups]
        alias_terms = [alias for group in validated_groups for alias in group["aliases"]]

        llm_keywords = self._coerce_text_list(analysis.get("keywords"))
        supporting_keywords = self._coerce_text_list(analysis.get("supporting_keywords"))
        recall_keywords = self._dedupe_terms(alias_terms + extracted_keywords + llm_keywords + supporting_keywords)
        supporting_keywords = self._dedupe_terms(
            [kw for kw in extracted_keywords + llm_keywords + supporting_keywords if kw not in alias_terms]
        )

        analysis["grounded_terms"] = grounded_terms
        analysis["must_match_terms"] = must_match_terms
        analysis["must_match_alias_groups"] = validated_groups
        analysis["supporting_keywords"] = supporting_keywords

        return {
            "grounded_terms": grounded_terms,
            "must_match_terms": must_match_terms,
            "must_match_alias_groups": validated_groups,
            "supporting_keywords": supporting_keywords,
            "recall_keywords": recall_keywords,
            "analysis": analysis,
        }
    
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
        # 从 skill-backed loader 加载需求分析提示词
        prompt_template = self.instruction_loader.load_template('keyword_extraction')
        prompt = prompt_template.replace('{chinese_text}', chinese_text)
        
        try:
            result_text = _complete_deterministic(model, prompt).strip()

            # Parse JSON response
            if "```json" in result_text:
                result_text = result_text.split("```json")[1].split("```")[0].strip()
            elif "```" in result_text:
                result_text = result_text.split("```")[1].split("```")[0].strip()

            analysis = json.loads(result_text)
            
            # ``keywords`` remains the broad recall set. Grounded / must-match
            # terms are parsed separately downstream so generic words like
            # ``workflow`` cannot by themselves force a recommendation.
            keywords = self._coerce_text_list(analysis.get('keywords'))
            
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
            logger.exception(
                "Keyword extraction via LLM failed; falling back to heuristic extraction. "
                "input_len=%d error=%s",
                len(chinese_text or ""),
                e,
            )
            return {
                'keywords': self._fallback_keyword_extraction(chinese_text),
                'analysis': {}
            }
    
    def _fallback_keyword_extraction(self, text: str) -> List[str]:
        """备用关键词提取（不使用LLM）"""
        keyword_map = {
            '流程图': ['flowchart'],
            '流程': ['process'],
            '架构图': ['architecture diagram', 'architecture'],
            '架构': ['architecture'],
            '组织图': ['organization chart', 'org chart'],
            '组织': ['organization'],
            '网络图': ['network diagram', 'network'],
            '网络': ['network'],
            '云': ['cloud'],
            '时序图': ['sequence diagram', 'sequence'],
            '时序': ['sequence'],
            '数据': ['data', 'database'],
            '系统': ['system'],
            '基础设施': ['infrastructure'],
        }
        
        keywords = []
        for chinese_key, english_terms in keyword_map.items():
            if chinese_key in text:
                keywords.extend(english_terms)

        keywords.extend(self._heuristic_grounded_terms(text))
        english_terms = re.findall(
            r"[A-Za-z0-9][A-Za-z0-9.+/_-]*(?:\s+[A-Za-z0-9][A-Za-z0-9.+/_-]*){0,2}",
            text,
        )
        keywords.extend(english_terms)

        return self._dedupe_terms(keywords)[:10]
    
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
        
        # Sort by score (deterministic tiebreaker: lexicographic by filename).
        # Without the secondary key, dict-iteration order or score ties could
        # silently flip the ordering across runs, which is what callers
        # observed before this fix.
        results.sort(
            key=lambda x: (-x['keyword_match_score'], x.get('filename', ''))
        )

        print(f"✓ 关键词筛选: 找到 {len(results)} 个匹配项 (最小分数: {min_match_score})")
        return results
    
    def filter_by_keywords_and_structure(self, 
                                        keywords: List[str],
                                        requirement_analysis: Dict[str, Any],
                                        search_type: str = "template",
                                        keyword_threshold: float = 0.2,
                                        structure_threshold: float = 0.3,
                                        keyword_weight: float = 0.4,
                                        structure_weight: float = 0.6,
                                        must_match_alias_groups: Optional[List[Dict[str, Any]]] = None,
                                        require_must_match: bool = False,
                                        user_input: str = "") -> List[Dict[str, Any]]:
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
        
        must_match_alias_groups = list(must_match_alias_groups or [])

        for filename, item_data in library.items():
            core_match = self._evaluate_must_match_groups(item_data, must_match_alias_groups)
            if require_must_match and must_match_alias_groups and not core_match["passes"]:
                continue

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
                base_score = keyword_score * keyword_weight + structure_score * structure_weight
                template_preference_score = self._template_language_preference_score(
                    item_data,
                    user_input,
                    search_type=search_type,
                )
                final_score = max(0.0, min(1.0, base_score + template_preference_score * 0.18))
                
                result = {
                    'filename': filename,
                    'keyword_match_score': round(keyword_score, 3),
                    'structure_match_score': round(structure_score, 3),
                    'combined_score': round(final_score, 3),
                    'base_combined_score': round(base_score, 3),
                    'template_preference_score': round(template_preference_score, 3),
                    'matched_core_terms': core_match['matched_sources'],
                    'must_match_passed': core_match['passes'],
                    'core_term_match_ratio': round(core_match['coverage'], 3),
                    **item_data
                }
                results.append(result)
                passed_count += 1
        
        # 5. 按综合分数排序（稳定 + 字典序 tiebreaker，保证多次运行结果一致）
        results.sort(
            key=lambda x: (
                -float(x.get('must_match_passed', False)),
                -float(x.get('core_term_match_ratio', 0) or 0),
                -float(x.get('template_preference_score', 0) or 0),
                -x['combined_score'],
                -x['structure_match_score'],
                -x['keyword_match_score'],
                x.get('filename', ''),
            )
        )
        
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

        searchable_text = self._build_searchable_text(item_data)
        compact_searchable = self._compact_search_text(searchable_text)

        # Generic words remain useful for broad recall, but they should not
        # dominate scoring over user-grounded business / domain terms.
        weighted_matches = 0.0
        total_weight = 0.0
        for keyword in keywords:
            normalized_keyword = self._normalize_search_text(keyword)
            compact_keyword = self._compact_search_text(keyword)
            if not normalized_keyword:
                continue

            weight = 0.35 if self._is_generic_term(normalized_keyword) else 1.0
            total_weight += weight
            if normalized_keyword in searchable_text or (compact_keyword and compact_keyword in compact_searchable):
                weighted_matches += weight

        return (weighted_matches / total_weight) if total_weight else 0.0
    
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
                         confidence_score: float = 0.5,
                         requirement_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
            Structured evaluation result with ``results`` plus warning/fallback metadata.
        """
        if not candidates:
            return {
                "results": [],
                "warnings": ["No candidates available for LLM evaluation."],
                "fallback_used": False,
                "error_code": None,
            }
        
        # Limit candidates to avoid token overflow.
        # Step 2 now caps candidates at _TARGET_MAX_CANDIDATES (default 10),
        # so 10 is the natural ceiling here as well.
        llm_cap = max(self._TARGET_MAX_CANDIDATES, 10)
        candidates_for_eval = candidates[:llm_cap]
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
        
        # 从 skill-backed loader 加载模板评估提示词
        prompt_template = self.instruction_loader.load_template('template_evaluation')
        prompt = prompt_template.replace('{user_requirement}', user_requirement)
        prompt = prompt.replace('{requirement_analysis}', analysis_text)
        prompt = prompt.replace('{candidates_text}', candidates_text)
        prompt = prompt.replace('{top_k}', str(top_k))
        
        core_term_text = self._format_core_term_constraints(requirement_profile or {})
        if core_term_text:
            prompt += f"\n\n## 用户原话核心词门禁\n\n{core_term_text}"

        # 如果有评分策略说明，添加到prompt中
        if scoring_strategy:
            prompt += f"\n\n## 评分权重策略\n\n{scoring_strategy}"
        
        try:
            result_text = _complete_deterministic(model, prompt).strip()

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

                    # Blend LLM score with the deterministic structural score
                    # so that small LLM-side fluctuations cannot reorder
                    # near-tied candidates. The LLM still drives the headline
                    # ranking (70%), but the structural score (already stable)
                    # acts as an anchor that keeps repeat runs identical.
                    llm_score_raw = float(rec.get('llm_score', 0) or 0)
                    combined_score = float(original.get('combined_score', 0) or 0)
                    template_preference_score = float(original.get('template_preference_score', 0) or 0)
                    final_score = round(
                        0.68 * llm_score_raw
                        + 0.30 * (combined_score * 10.0)
                        + 0.55 * template_preference_score,
                        3,
                    )

                    merged = {
                        **original,
                        'llm_score': llm_score_raw,
                        'final_score': final_score,
                        'template_preference_score': round(template_preference_score, 3),
                        'template_path': template_path,  # 使用确保正确的路径
                        'structure_description': rec.get('structure_description', ''),
                        'dimension_scores': rec.get('dimension_scores', {}),
                        'final_rank': len(final_results) + 1,
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
            
            # Deterministic re-sort: blended ``final_score`` then stable
            # tiebreakers. Without this, two candidates with identical
            # ``llm_score`` (which DeepSeek often returns for close calls)
            # would keep whatever order the LLM emitted them in — and that
            # order is *not* stable across runs even with seed=0.
            final_results.sort(
                key=lambda r: (
                    -float(r.get('final_score', 0) or 0),
                    -float(r.get('llm_score', 0) or 0),
                    -float(r.get('template_preference_score', 0) or 0),
                    -float(r.get('combined_score', 0) or 0),
                    r.get('filename', ''),
                )
            )
            for idx, item in enumerate(final_results, 1):
                item['final_rank'] = idx

            warnings: List[str] = []
            if match_failures:
                warnings.append(
                    "Some LLM recommendations could not be matched back to candidates: "
                    + ", ".join(match_failures)
                )

            print(f"✓ 大模型评估完成: 推荐 {len(final_results)} 个最佳匹配")
            return {
                "results": final_results,
                "warnings": warnings,
                "fallback_used": False,
                "error_code": None,
            }
        
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
            logger.error(
                "LLM evaluation returned invalid JSON; using keyword-ranked fallback. "
                "candidates=%d top_k=%d error=%s snippet=%r",
                len(candidates),
                top_k,
                e,
                (e.doc[max(0, e.pos - 50):e.pos + 50] if hasattr(e, "doc") else None),
            )
            fallback_results = candidates[:top_k]
            print(f"⚠️ 【重要】触发FALLBACK: 返回基于关键词排序的前 {len(fallback_results)} 个结果")
            print(f"   这可能导致推荐数量与预期不符！\n")
            return {
                "results": fallback_results,
                "warnings": [
                    "LLM returned invalid JSON; used keyword-ranked fallback candidates instead."
                ],
                "fallback_used": True,
                "error_code": "PARSE_FAILED",
            }
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"❌ 大模型评估失败: {type(e).__name__}")
            print(f"{'='*60}")
            print(f"错误信息: {e}")
            import traceback
            print(f"错误堆栈:\n{traceback.format_exc()}")
            print(f"{'='*60}\n")
            logger.exception(
                "LLM evaluation failed (%s); using keyword-ranked fallback. "
                "candidates=%d top_k=%d",
                type(e).__name__,
                len(candidates),
                top_k,
            )
            fallback_results = candidates[:top_k]
            print(f"⚠️ 【重要】触发FALLBACK: 返回基于关键词排序的前 {len(fallback_results)} 个结果")
            print(f"   这可能导致推荐数量与预期不符！\n")
            return {
                "results": fallback_results,
                "warnings": [
                    f"LLM evaluation failed ({type(e).__name__}); used keyword-ranked fallback candidates instead."
                ],
                "fallback_used": True,
                "error_code": "MODEL_UNAVAILABLE",
            }
    
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

        grounded_terms = self._coerce_text_list(analysis.get('grounded_terms'))
        if grounded_terms:
            lines.append(f"- **用户原话核实词**: {'、'.join(grounded_terms[:5])}")

        must_match_terms = self._coerce_text_list(analysis.get('must_match_terms'))
        if must_match_terms:
            lines.append(f"- **必须命中的核心词**: {'、'.join(must_match_terms[:5])}")
        
        # 具体要求
        requirements = analysis.get('specific_requirements', [])
        if requirements:
            req_text = '、'.join(requirements[:5])
            lines.append(f"- **具体要求**: {req_text}")
        
        return '\n'.join(lines)

    def _format_core_term_constraints(self, requirement_profile: Dict[str, Any]) -> str:
        """Format grounded core-term gates for the evaluation prompt."""
        groups = list((requirement_profile or {}).get("must_match_alias_groups") or [])
        if not groups:
            return ""

        lines = [
            "以下核心词来自用户原话，属于硬门禁。",
            "只有命中这些核心词（或对应别名）的候选，才可以进入正式推荐。",
            "像 flowchart / process / workflow / architecture 这类泛词只能辅助排序，不能单独支撑入选。",
        ]
        for group in groups:
            source = group.get("source", "")
            aliases = self._coerce_text_list(group.get("aliases"))
            if not source or not aliases:
                continue
            lines.append(f"- `{source}` -> {', '.join(aliases)}")
        return "\n".join(lines)
    
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

    # 阈值阶梯：(keyword_threshold, structure_threshold)
    # 从最宽松（level 0）到最严格（level 6），用于步骤 2 自适应收紧
    _THRESHOLD_LADDER: List[tuple] = [
        (0.00, 0.00),  # 0 - 完全放开（最后兜底）
        (0.02, 0.30),  # 1 - 极宽松
        (0.05, 0.40),  # 2 - 较宽松
        (0.08, 0.50),  # 3 - 标准（原默认）
        (0.15, 0.60),  # 4 - 偏严
        (0.25, 0.70),  # 5 - 严格
        (0.40, 0.80),  # 6 - 极严格
    ]

    # 候选数量目标区间
    _TARGET_MIN_CANDIDATES = 1
    _TARGET_MAX_CANDIDATES = 10

    def _baseline_threshold_level(self, confidence_score: float) -> int:
        """根据置信度选择起步阶梯（作为收紧/放宽的起点）。"""
        if confidence_score < 0.4:
            return 1  # 低置信度从极宽松开始
        elif confidence_score < 0.7:
            return 2  # 中置信度从较宽松开始
        else:
            return 3  # 高置信度从标准阈值开始

    def adaptive_filter(self,
                        keywords: List[str],
                        analysis: Dict[str, Any],
                        search_type: str,
                        confidence_score: float,
                        must_match_alias_groups: Optional[List[Dict[str, Any]]] = None,
                        require_must_match: bool = False,
                        user_input: str = "") -> tuple:
        """
        步骤 2 自适应筛选：逐渐提升阈值等级，确保候选数 ∈ [1, 10]。
        
        策略：
        1. 从置信度对应的起步阶梯开始评估候选数。
        2. 若候选 > MAX：逐级升高阈值，直到落入 [MIN, MAX]；
           若再升一级会导致 0，则停在当前级别。
        3. 若候选 < MIN：逐级降低阈值，直到 >= MIN 或到达 level 0。
        
        Returns:
            (candidates, ladder_trace) 元组，ladder_trace 用于诊断/告警。
        """
        ladder = self._THRESHOLD_LADDER
        baseline = self._baseline_threshold_level(confidence_score)
        trace: List[Dict[str, Any]] = []

        def run_level(level: int) -> List[Dict[str, Any]]:
            kt, st = ladder[level]
            print(f"  ↳ 尝试阈值等级 L{level} (关键词≥{kt}, 结构≥{st})")
            cands = self.filter_by_keywords_and_structure(
                keywords,
                analysis,
                search_type=search_type,
                keyword_threshold=kt,
                structure_threshold=st,
                must_match_alias_groups=must_match_alias_groups,
                require_must_match=require_must_match,
                user_input=user_input,
            )
            trace.append({"level": level, "kt": kt, "st": st, "count": len(cands)})
            return cands

        candidates = run_level(baseline)

        if len(candidates) > self._TARGET_MAX_CANDIDATES:
            # 候选过多：向上收紧
            level = baseline
            best = candidates
            while level + 1 < len(ladder):
                level += 1
                next_cands = run_level(level)
                if len(next_cands) < self._TARGET_MIN_CANDIDATES:
                    print(f"  ⚠ L{level} 收紧过度（{len(next_cands)} 个），回退到 L{level - 1}")
                    break
                best = next_cands
                if len(best) <= self._TARGET_MAX_CANDIDATES:
                    break
            candidates = best
        elif len(candidates) < self._TARGET_MIN_CANDIDATES:
            # 候选过少（通常为 0）：向下放宽
            level = baseline
            while level > 0 and len(candidates) < self._TARGET_MIN_CANDIDATES:
                level -= 1
                candidates = run_level(level)

        # 截断到上限（仍按综合分排序后保留前 N）
        if len(candidates) > self._TARGET_MAX_CANDIDATES:
            print(f"  ↳ 候选 {len(candidates)} 超出上限，截断到 {self._TARGET_MAX_CANDIDATES}")
            candidates = candidates[: self._TARGET_MAX_CANDIDATES]

        return candidates, trace
    
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
            if search_preference := item.get('template_preference_score'):
                lines.append(f"   中文/通用模板偏好分: {search_preference}")
            
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

    def keyword_only_match(
        self,
        user_input: str,
        search_type: str = "template",
        top_k: int = 5,
        reason: Optional[str] = None,
        error_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Deterministic fallback recommendation without any LLM calls."""
        extracted_keywords = self._fallback_keyword_extraction(user_input)
        requirement_profile = self._build_requirement_profile(
            user_input,
            extracted_keywords,
            analysis={},
        )
        analysis = requirement_profile["analysis"]
        keywords = requirement_profile["recall_keywords"]
        must_match_alias_groups = requirement_profile["must_match_alias_groups"]

        complexity_assessment = self._assess_input_complexity(user_input, analysis)
        confidence_score = complexity_assessment['confidence_score']
        warnings = [reason] if reason else []

        strict_candidates, _ = self.adaptive_filter(
            keywords=keywords,
            analysis=analysis,
            search_type=search_type,
            confidence_score=confidence_score,
            must_match_alias_groups=must_match_alias_groups,
            require_must_match=bool(must_match_alias_groups),
            user_input=user_input,
        )

        alternatives: List[Dict[str, Any]] = []
        final_results = strict_candidates[:top_k]

        if must_match_alias_groups and not final_results:
            warnings.append(
                "No candidate satisfied all user-grounded core terms; strict recommendations were withheld."
            )
            relaxed_candidates, _ = self.adaptive_filter(
                keywords=keywords,
                analysis=analysis,
                search_type=search_type,
                confidence_score=confidence_score,
                must_match_alias_groups=must_match_alias_groups,
                require_must_match=False,
                user_input=user_input,
            )
            alternatives = relaxed_candidates[:top_k]

        return self._format_chinese_output(
            user_input,
            keywords,
            final_results,
            search_type,
            complexity_assessment,
            analysis,
            warnings=warnings,
            fallback_used=True,
            error_code=error_code,
            grounded_terms=requirement_profile["grounded_terms"],
            must_match_terms=requirement_profile["must_match_terms"],
            alternatives=alternatives,
        )
    
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

        # Step 0: cache lookup. Repeated calls with the same requirement
        # short-circuit to the previously computed payload so the user sees
        # truly identical recommendations on retries.
        cache_key = _cache_key(user_input, search_type, top_k)
        if not self._reco_cache_disabled and cache_key in self._reco_cache:
            cached = self._reco_cache[cache_key]
            self._reco_cache.move_to_end(cache_key)
            print(f"⚡ 命中推荐缓存 (key={cache_key[:10]}…)，复用上次结果")
            # Return a defensive deep copy so callers can mutate freely.
            return json.loads(json.dumps(cached, ensure_ascii=False))

        warnings: List[str] = []
        fallback_used = False
        error_code: Optional[str] = None

        # Step 1: Extract English keywords and requirement analysis from input
        print("\n📝 步骤 1: 提取英文关键词和需求分析...")
        extraction_result = self.extract_english_keywords(user_input, model)
        requirement_profile = self._build_requirement_profile(
            user_input,
            extraction_result['keywords'],
            extraction_result['analysis'],
        )
        keywords = requirement_profile['recall_keywords']
        analysis = requirement_profile['analysis']
        must_match_alias_groups = requirement_profile['must_match_alias_groups']
        if requirement_profile['grounded_terms']:
            print(f"✓ 用户原话核实词: {', '.join(requirement_profile['grounded_terms'])}")
        if requirement_profile['must_match_terms']:
            print(f"✓ 核心词门禁: {', '.join(requirement_profile['must_match_terms'])}")
        
        if not keywords:
            print("⚠ 警告: 未能提取关键词，使用备用方案")
            keywords = self._fallback_keyword_extraction(user_input)
            warnings.append("Keyword extraction returned no keywords; used fallback keyword extraction.")
        
        # Assess input complexity for dynamic matching
        print("\n🎯 步骤 1.5: 评估输入复杂度...")
        complexity_assessment = self._assess_input_complexity(user_input, analysis)
        confidence_score = complexity_assessment['confidence_score']
        print(f"✓ 输入复杂度: {complexity_assessment['complexity_level']}")
        print(f"✓ 匹配置信度: {confidence_score:.2f}")
        
        # Step 2: Adaptive filtering — escalate thresholds to land in [MIN, MAX]
        print("\n🔎 步骤 2: 关键词+结构自适应筛选（阶梯阈值）...")
        print(
            f"✓ 目标候选数: [{self._TARGET_MIN_CANDIDATES}, {self._TARGET_MAX_CANDIDATES}]，"
            f"起步等级 L{self._baseline_threshold_level(confidence_score)}"
        )

        candidates, ladder_trace = self.adaptive_filter(
            keywords=keywords,
            analysis=analysis,
            search_type=search_type,
            confidence_score=confidence_score,
            must_match_alias_groups=must_match_alias_groups,
            require_must_match=bool(must_match_alias_groups),
            user_input=user_input,
        )
        print(f"✓ 自适应筛选完成: 最终 {len(candidates)} 个候选 (阶梯轨迹: {ladder_trace})")

        alternatives: List[Dict[str, Any]] = []
        if must_match_alias_groups and not candidates:
            warnings.append(
                "No candidate satisfied all user-grounded core terms; formal recommendations were withheld."
            )
            relaxed_candidates, relaxed_trace = self.adaptive_filter(
                keywords=keywords,
                analysis=analysis,
                search_type=search_type,
                confidence_score=confidence_score,
                must_match_alias_groups=must_match_alias_groups,
                require_must_match=False,
                user_input=user_input,
            )
            print(f"✓ 放宽后备选候选数: {len(relaxed_candidates)} 个 (阶梯轨迹: {relaxed_trace})")
            alternatives = relaxed_candidates[:top_k]

        if not candidates:
            warnings.append(
                "Adaptive filter could not find any candidates even at the loosest level."
            )
        elif len(candidates) < self._TARGET_MIN_CANDIDATES:
            warnings.append(
                f"Adaptive filter produced fewer than {self._TARGET_MIN_CANDIDATES} candidate(s)."
            )

        # Step 3: Evaluate with LLM (using full library and requirement analysis)
        print(f"\n🤖 步骤 3: 大模型评估（{len(candidates)} 个候选 → LLM 排序）...")
        if candidates:
            llm_eval = self.evaluate_with_llm(
                candidates,
                user_input,
                analysis,  # Pass requirement analysis
                model,
                top_k=top_k,
                search_type=search_type,
                confidence_score=confidence_score,  # Pass confidence score for dynamic scoring
                requirement_profile=requirement_profile,
            )
            final_results = llm_eval["results"]
            warnings.extend(llm_eval.get("warnings", []))
            fallback_used = llm_eval.get("fallback_used", False)
            error_code = llm_eval.get("error_code")
        else:
            final_results = []
            warnings.append("No candidates were available for recommendation after relaxed filtering.")
        
        # Step 4: Format output in Chinese
        print("\n📊 步骤 4: 生成中文输出...")
        output = self._format_chinese_output(
            user_input,
            keywords,
            final_results,
            search_type,
            complexity_assessment,  # Pass complexity assessment
            analysis,  # Pass analysis
            warnings=warnings,
            fallback_used=fallback_used,
            error_code=error_code,
            grounded_terms=requirement_profile["grounded_terms"],
            must_match_terms=requirement_profile["must_match_terms"],
            alternatives=alternatives,
        )
        
        print(f"\n{'='*60}")
        print(f"✅ 智能匹配完成")
        print(f"{'='*60}\n")

        # Cache successful (non-error) results so subsequent identical
        # requests are byte-identical. Errors are intentionally not cached:
        # the next call should re-attempt the LLM rather than memoize a
        # transient failure.
        if (
            not self._reco_cache_disabled
            and output.get("status") != "error"
            and output.get("recommendations")
        ):
            self._reco_cache[cache_key] = json.loads(
                json.dumps(output, ensure_ascii=False)
            )
            self._reco_cache.move_to_end(cache_key)
            while len(self._reco_cache) > _CACHE_MAX_ENTRIES:
                self._reco_cache.popitem(last=False)

        return output

    # Public testing/debugging helper.
    def clear_recommendation_cache(self) -> None:
        """Drop the in-memory recommendation cache. Used by tests / admins."""
        self._reco_cache.clear()
    
    def _format_chinese_output(self, user_input: str, keywords: List[str],
                              results: List[Dict[str, Any]], 
                              search_type: str,
                              complexity_assessment: Optional[Dict[str, Any]] = None,
                              analysis: Optional[Dict[str, Any]] = None,
                              warnings: Optional[List[str]] = None,
                              fallback_used: bool = False,
                              error_code: Optional[str] = None,
                              grounded_terms: Optional[List[str]] = None,
                              must_match_terms: Optional[List[str]] = None,
                              alternatives: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
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
        warnings = list(warnings or [])
        grounded_terms = self._coerce_text_list(grounded_terms)
        must_match_terms = self._coerce_text_list(must_match_terms)
        alternatives = list(alternatives or [])
        
        output = {
            "status": "ok",
            "search_type": search_type,
            "requirement": user_input,
            "keywords": keywords,
            "analysis": analysis or {},
            "complexity_assessment": complexity_assessment or {},
            "grounded_terms": grounded_terms,
            "must_match_terms": must_match_terms,
            "recommendations": [],
            "alternatives": [],
            "warnings": warnings,
            "fallback_used": fallback_used,
            "error_code": error_code,
            "搜索类型": type_name,
            "推荐列表": [],
            "备选列表": [],
        }
        
        def build_compact_entry(item: Dict[str, Any], rank: int) -> Dict[str, Any]:
            # 获取或构建完整路径
            template_path = item.get('template_path', item.get('path', item.get('full_path', '')))
            if not template_path:
                # 根据文件名构建默认路径
                template_path = f"assets/templates/library/{item['filename']}"
            elif search_type == "template":
                normalized_path = str(Path(template_path).as_posix())
                if not normalized_path.startswith("assets/templates/library/"):
                    warnings.append(
                        f"Recommended template path is outside the curated library: {template_path}"
                    )
            
            # 核心信息：路径、得分、描述
            # ``final_score`` is the blended LLM+structure score that drives
            # the deterministic ranking. Fall back gracefully for older code
            # paths (keyword fallback / direct callers) that only have one
            # of the legacy scores.
            score_value = item.get(
                'final_score',
                item.get('llm_score', item.get('combined_score', 0)),
            )
            recommendation = {
                "rank": rank,
                "filename": item.get('filename', ''),
                "path": template_path,
                "score": round(float(score_value or 0), 1),
                "description": item.get('structure_description', ''),
            }
            matched_core_terms = self._coerce_text_list(item.get("matched_core_terms"))
            if matched_core_terms:
                recommendation["matched_core_terms"] = matched_core_terms
            
            # 添加预览URL（模板）或形状数（形状库）
            if search_type == "template":
                # 使用Markdown链接格式避免URL因空格被拆分
                filename = os.path.basename(template_path)
                recommendation["preview"] = f"[{filename}](http://localhost:7777/api/visio/preview?path={template_path})"

            return recommendation

        # 格式化推荐列表（仅保留核心字段）
        for i, item in enumerate(results, 1):
            recommendation = build_compact_entry(item, i)
            output["recommendations"].append(recommendation)
            output["推荐列表"].append(recommendation)

        for i, item in enumerate(alternatives, 1):
            alternative = build_compact_entry(item, i)
            output["alternatives"].append(alternative)
            output["备选列表"].append(alternative)
        
        if error_code and not output["recommendations"]:
            output["status"] = "error"
        elif warnings or fallback_used:
            output["status"] = "warning"
        
        print(f"✅ 最终生成推荐列表: {len(output['recommendations'])} 项\n")
        
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
