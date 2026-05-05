"""Tools for Visio diagram manipulation (pure library layer).

Primary export is the consolidated 16-tool surface (see ``consolidated.py``),
adapted and exposed by :mod:`visio_mcp` and :mod:`apps.visio_agent`.
"""
from .visio_tools import VisioTools

__all__ = [
    "VisioTools",
    "PromptTools",
    "CONSOLIDATED_TOOL_NAMES",
    "get_consolidated_tools",
    "get_agent_tools",
]


def __getattr__(name):
    if name == "PromptTools":
        from .prompt_tools import PromptTools
        return PromptTools
    if name == "CONSOLIDATED_TOOL_NAMES":
        from .consolidated import CONSOLIDATED_TOOL_NAMES
        return CONSOLIDATED_TOOL_NAMES
    if name == "get_consolidated_tools":
        from .consolidated import get_consolidated_tools
        return get_consolidated_tools
    if name == "get_agent_tools":
        from .consolidated import get_agent_tools
        return get_agent_tools
    raise AttributeError(f"module 'visio_core.tools' has no attribute {name!r}")
