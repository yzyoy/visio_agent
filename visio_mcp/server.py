"""
MCP server scaffold (stdio transport; sse deferred).

- This module exposes the consolidated 16-tool surface through the MCP
  contract. Agno remains the top-level runtime shell — ``apps/agent_os.py``
  owns the HTTP and preview surface.
- The scaffold is self-contained: if the ``mcp`` SDK is installed,
  ``serve_stdio`` runs a real server. If not, the in-process registry is
  still usable from tests and from the agno adapter.
- ``apply_patches()`` runs explicitly at registry build time; no
  import-time side effects.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable, Dict, Optional

from visio_core.patches import apply_patches
from .contract import (
    MCP_TOOL_NAMES,
    MCP_TOOL_SPECS,
    ToolSpec,
    build_tool_registry,
)
from .errors import VisioToolError, ErrorCode


def _make_tool_pair(
    template_dir: Optional[str] = None,
    dialog_dir: Optional[str] = None,
    session_id: str = "mcp_default",
):
    """Instantiate ``VisioTools`` + ``PromptTools`` for the server process."""
    from visio_core.tools.visio_tools import VisioTools
    from visio_core.tools.prompt_tools import PromptTools

    template_dir = template_dir or os.environ.get("VISIO_TEMPLATE_DIR", "assets/templates")
    dialog_dir = dialog_dir or os.environ.get("VISIO_DIALOG_DIR", ".state/dialog")

    visio_tools = VisioTools(
        session_id=session_id,
        dialog_dir=dialog_dir,
        auto_restore=False,
        record_context=False,
    )
    prompt_tools = PromptTools(template_dir=template_dir)
    return visio_tools, prompt_tools


def build_server_registry(
    template_dir: Optional[str] = None,
    dialog_dir: Optional[str] = None,
    session_id: str = "mcp_default",
) -> Dict[str, Callable]:
    """Build the MCP tool registry for the server process.

    Applies patches explicitly, instantiates the tool classes, and returns
    a ``name -> callable`` map whose keys are exactly
    ``MCP_TOOL_NAMES``. This function is the single bridge between the
    declarative contract and the runtime.
    """
    apply_patches()
    visio_tools, prompt_tools = _make_tool_pair(
        template_dir=template_dir,
        dialog_dir=dialog_dir,
        session_id=session_id,
    )
    return build_tool_registry(visio_tools, prompt_tools)


def invoke(
    registry: Dict[str, Callable],
    tool_name: str,
    /,
    **kwargs: Any,
) -> Any:
    """Call a tool by name through the MCP registry.

    Raises ``VisioToolError`` for unknown tool names with a structured
    error envelope. All other exceptions propagate — the MCP SDK wraps
    them at the transport boundary.
    """
    fn = registry.get(tool_name)
    if fn is None:
        raise VisioToolError(
            code=ErrorCode.SELECTOR_NOT_FOUND,
            message=f"MCP tool '{tool_name}' not registered.",
            hint=f"Known tools: {sorted(MCP_TOOL_NAMES)}",
            recoverable=True,
        )
    return fn(**kwargs)


def serve_stdio() -> int:  # pragma: no cover — exercised manually
    """Run the MCP server over stdio, if the ``mcp`` SDK is available.

    Returns a process exit code. Kept small deliberately: the SDK handles
    framing, schema generation, and stdio orchestration. Our job is only
    to register the consolidated tools.
    """
    try:
        from mcp.server.fastmcp import FastMCP  # type: ignore
    except Exception as err:  # pragma: no cover
        print(
            f"[visio_mcp] mcp SDK not installed ({err}); run "
            "`pip install mcp[cli]` to enable stdio transport.",
            file=sys.stderr,
        )
        return 2

    registry = build_server_registry()
    server = FastMCP(name="visio_mcp")
    for spec in MCP_TOOL_SPECS:
        fn = registry[spec.name]
        server.add_tool(fn, name=spec.name, description=spec.summary)
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(serve_stdio())
