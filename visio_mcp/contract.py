"""
MCP tool contract — single source of truth for the server's capability set.

The ``MCP_TOOL_NAMES`` tuple is derived *directly* from
``visio_core.tools.consolidated.CONSOLIDATED_TOOL_NAMES``. A contract
test guards that parity so the MCP surface cannot drift independently
from the LLM-facing surface.

Each ``ToolSpec`` bundles the metadata the MCP SDK needs to register a
tool (name, summary, idempotency, error codes). The actual callable for
a tool is resolved at runtime by ``build_tool_registry(...)`` using the
same ``get_consolidated_tools(...)`` adapter that the agno agent uses.
This keeps the library implementation authoritative — the MCP layer is
a re-projection of the same functions over a new transport.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Tuple, TYPE_CHECKING

from visio_core.tools.consolidated import (
    CONSOLIDATED_TOOL_NAMES,
    get_consolidated_tools,
)

from .errors import ErrorCode

if TYPE_CHECKING:  # pragma: no cover
    from visio_core.tools.visio_tools import VisioTools
    from visio_core.tools.prompt_tools import PromptTools


# Exported so tests / external clients can compare without touching
# ``visio_core`` internals directly.
MCP_TOOL_NAMES: Tuple[str, ...] = CONSOLIDATED_TOOL_NAMES


@dataclass(frozen=True)
class ToolSpec:
    """Declarative metadata for an MCP tool."""
    name: str
    summary: str
    idempotent: bool
    mutates: bool
    error_codes: Tuple[str, ...]


# Metadata table. Keep parameter documentation out of this module — the
# SDK reads it directly from the wrapped function's signature /
# ``__doc__``. This table only captures cross-cutting contract facts.
_SPEC_TABLE: Dict[str, Dict[str, Any]] = {
    "recommend_template": dict(
        summary="Rank templates for a natural-language requirement.",
        idempotent=True, mutates=False,
        error_codes=(ErrorCode.LIBRARY_EMPTY.value, ErrorCode.MODEL_UNAVAILABLE.value),
    ),
    "search_templates": dict(
        summary="List or keyword-search templates in the curated library. "
                "Empty keywords returns the full index.",
        idempotent=True, mutates=False, error_codes=(),
    ),
    "analyze_template": dict(
        summary="Atomic 6-step structural analysis of a template or the "
                "currently-open document.",
        idempotent=True, mutates=False,
        error_codes=(ErrorCode.FILE_NOT_FOUND.value, ErrorCode.PARSE_FAILED.value),
    ),
    "search_stencils": dict(
        summary="List or keyword-search stencil collections. Empty keywords "
                "returns the full stencil index.",
        idempotent=True, mutates=False, error_codes=(),
    ),
    "get_stencil": dict(
        summary="Return stencil details including master list.",
        idempotent=True, mutates=False,
        error_codes=(ErrorCode.FILE_NOT_FOUND.value,),
    ),
    "open_document": dict(
        summary="Open an existing document; returns the session handle.",
        idempotent=True, mutates=False,
        error_codes=(ErrorCode.FILE_NOT_FOUND.value,),
    ),
    "create_from_template": dict(
        summary="Create a new document from a named template.",
        idempotent=True, mutates=True,
        error_codes=(ErrorCode.TEMPLATE_NOT_FOUND.value, ErrorCode.OUTPUT_EXISTS.value),
    ),
    "save_document": dict(
        summary="Save the current document to disk. Subsequent connector "
                "writes must be preceded by open_document.",
        idempotent=True, mutates=True,
        error_codes=(ErrorCode.DOC_NOT_OPEN.value, ErrorCode.INVALID_OOXML.value,
                     ErrorCode.SAVE_REQUIRES_RELOAD.value),
    ),
    "fit_page_to_drawing": dict(
        summary="Resize a page to fit the drawing content with a margin.",
        idempotent=True, mutates=True,
        error_codes=(ErrorCode.DOC_NOT_OPEN.value,),
    ),
    "render_page": dict(
        summary="Render a page to PNG (data URI or URL).",
        idempotent=True, mutates=False,
        error_codes=(ErrorCode.FILE_NOT_FOUND.value, ErrorCode.RENDER_FAILED.value),
    ),
    "upsert_shape": dict(
        summary="Create-or-update a shape by stable node_key. Idempotent.",
        idempotent=True, mutates=True,
        error_codes=(ErrorCode.DOC_NOT_OPEN.value, ErrorCode.INVALID_TYPE.value,
                     ErrorCode.DUPLICATE_KEY.value),
    ),
    "upsert_connector": dict(
        summary="Create-or-update a connector by stable edge_key. Idempotent.",
        idempotent=True, mutates=True,
        error_codes=(ErrorCode.NODE_NOT_FOUND.value,
                     ErrorCode.CONNECTOR_GLUE_INVALID.value,
                     ErrorCode.SAVE_REQUIRES_RELOAD.value),
    ),
    "update_text": dict(
        summary="Update text on a shape identified by id, key, or match.",
        idempotent=True, mutates=True,
        error_codes=(ErrorCode.SELECTOR_NOT_FOUND.value,),
    ),
    "remove_shape": dict(
        summary="Remove a shape with smart reconnection; connector IDs auto-route to connector deletion.",
        idempotent=True, mutates=True,
        error_codes=(ErrorCode.SELECTOR_NOT_FOUND.value,),
    ),
    "edit_shape": dict(
        summary="Apply a patch to a shape: {text, node_key, position, "
                "size, style}. Text is normalized to a single line; "
                "position can be absolute or relative; style supports "
                "line_width, line_color, and fill_color.",
        idempotent=True, mutates=True,
        error_codes=(ErrorCode.SELECTOR_NOT_FOUND.value,),
    ),
    "insert_from_stencil": dict(
        summary="Insert a master from a stencil at a position with text.",
        idempotent=True, mutates=True,
        error_codes=(ErrorCode.FILE_NOT_FOUND.value,),
    ),
}


MCP_TOOL_SPECS: Tuple[ToolSpec, ...] = tuple(
    ToolSpec(
        name=name,
        summary=_SPEC_TABLE[name]["summary"],
        idempotent=_SPEC_TABLE[name]["idempotent"],
        mutates=_SPEC_TABLE[name]["mutates"],
        error_codes=tuple(_SPEC_TABLE[name]["error_codes"]),
    )
    for name in CONSOLIDATED_TOOL_NAMES
)


def build_tool_registry(
    visio_tools: "VisioTools",
    prompt_tools: "PromptTools",
) -> Dict[str, Callable]:
    """Return a ``name -> callable`` registry for the MCP tool surface.

    The registry is built from the exact same consolidated functions that
    the agno agent is given, keyed by MCP tool name. No renaming happens
    here — parity with ``CONSOLIDATED_TOOL_NAMES`` is asserted by the
    contract test.
    """
    # Apply patches once on first registry build. Safe to call repeatedly.
    from visio_core.patches import apply_patches as _apply_patches
    _apply_patches()

    tools = get_consolidated_tools(visio_tools, prompt_tools)
    registry: Dict[str, Callable] = {}
    for fn in tools:
        name = getattr(fn, "__name__", None)
        if not name:
            continue
        registry[name] = fn

    missing = set(CONSOLIDATED_TOOL_NAMES) - set(registry)
    extra = set(registry) - set(CONSOLIDATED_TOOL_NAMES)
    if missing or extra:
        raise RuntimeError(
            "MCP tool registry drifted from CONSOLIDATED_TOOL_NAMES. "
            f"Missing: {sorted(missing)}. Unexpected: {sorted(extra)}."
        )
    return registry
