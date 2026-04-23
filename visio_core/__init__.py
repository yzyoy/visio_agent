"""
``visio_core`` — pure Python library for Visio document manipulation.

This is the canonical library: ``DiagramBuilder``, template and stencil
managers, shape-identity helpers, render, the vsdx patches, and the
``VisioTools`` façade the MCP layer adapts from.

Design invariants enforced by ``tests/test_visio_core_import_boundary.py``:
- ``import visio_core`` must succeed without ``agno`` installed.
- Any runtime LLM dependency (template recommendation, prompt ranking)
  is injected by the caller; nothing in this package imports ``agno``.

Usage::

    from visio_core import apply_patches, DiagramBuilder, VisioTools
    apply_patches()
    builder = DiagramBuilder()
"""
from __future__ import annotations

# Patches only touch the vsdx library and are safe to import at top level.
from .patches import apply_patches, patches_applied, applied_patch_names

__all__ = [
    "apply_patches",
    "patches_applied",
    "applied_patch_names",
    "DiagramBuilder",
    "TemplateManager",
    "StencilManager",
    "VisioTools",
    "PromptTools",
    "SmartMatcher",
    "get_shape_prop",
    "set_shape_prop",
]


def __getattr__(name: str):
    if name == "DiagramBuilder":
        from .utils.diagram_builder import DiagramBuilder
        return DiagramBuilder
    if name == "TemplateManager":
        from .templates.template_manager import TemplateManager
        return TemplateManager
    if name == "StencilManager":
        from .templates.stencil_manager import StencilManager
        return StencilManager
    if name == "VisioTools":
        from .tools.visio_tools import VisioTools
        return VisioTools
    if name == "PromptTools":
        from .tools.prompt_tools import PromptTools
        return PromptTools
    if name == "SmartMatcher":
        from .utils.smart_matcher import SmartMatcher
        return SmartMatcher
    if name == "get_shape_prop":
        from .utils.shape_identity import get_shape_prop
        return get_shape_prop
    if name == "set_shape_prop":
        from .utils.shape_identity import set_shape_prop
        return set_shape_prop
    raise AttributeError(f"module 'visio_core' has no attribute {name!r}")
