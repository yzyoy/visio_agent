"""
``visio_mcp`` — MCP migration layer (Batch B Phase 4).

This package introduces the MCP boundary as a migration target, not a
replacement for agno. ``apps/agent_os.py`` keeps agno as the governing
runtime shell; this package simply exposes the same capability set
behind an MCP-shaped contract so that downstream clients (Cursor,
Claude Code, a future remote runner) can reach the Visio core through
a single, declarative surface.

Contract rules (see ``MCP_CONTRACT.md``):
1. The tool list is derived directly from
   ``visio_core.tools.consolidated.CONSOLIDATED_TOOL_NAMES``. The MCP
   layer must not add, rename, or remove tools relative to that tuple —
   it only chooses the transport and the error envelope.
2. Every tool handler is a thin adapter over ``VisioTools`` /
   ``PromptTools``. The actual implementation stays in ``visio_core``.
3. Errors flow through ``VisioToolError`` with a machine-readable
   ``code`` field (``FILE_NOT_FOUND``, ``DOC_NOT_OPEN``,
   ``DUPLICATE_KEY``, ``CONNECTOR_GLUE_INVALID``, ``SAVE_REQUIRES_RELOAD``,
   ``NODE_NOT_FOUND``, ``INVALID_TYPE``, ``PARSE_FAILED``,
   ``TEMPLATE_NOT_FOUND``, ``OUTPUT_EXISTS``, ``SELECTOR_NOT_FOUND``,
   ``INVALID_OOXML``, ``RENDER_FAILED``, ``LIBRARY_EMPTY``,
   ``MODEL_UNAVAILABLE``).
4. ``apply_patches()`` must run once before any tool handler executes.
"""
from __future__ import annotations

from .errors import VisioToolError, ErrorCode
from .contract import (
    MCP_TOOL_NAMES,
    MCP_TOOL_SPECS,
    ToolSpec,
    build_tool_registry,
)

__all__ = [
    "VisioToolError",
    "ErrorCode",
    "MCP_TOOL_NAMES",
    "MCP_TOOL_SPECS",
    "ToolSpec",
    "build_tool_registry",
]
