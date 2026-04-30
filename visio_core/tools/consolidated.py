"""
Consolidated LLM-facing tool surface (15 canonical tools).

This module is the single source of truth for the LLM-visible tool
contract. It contains thin renames / adapters over methods of
:class:`visio_core.tools.visio_tools.VisioTools` and
:class:`visio_core.tools.prompt_tools.PromptTools`. No Visio operation
is re-implemented here.

Design rules (enforced by ``tests/test_consolidated_tool_surface.py``
and ``tests/test_mcp_contract.py``):

- Exactly 15 public names. Adding a name requires a matching update in
  ``refine/CORE_CAPABILITIES.md`` §2 and in ``visio_mcp/contract.py``.
- Idempotent key-based mutation only. Non-idempotent ``add_shape`` /
  ``connect_shapes`` and the 5-text-tool splat are intentionally absent.
- Diagnostic / session helpers
  (``cleanup_diagram_connectors``, ``validate_diagram_connectors``,
  ``get_log_summary``, ``ensure_all_shapes_have_keys``, ``set_session``,
  ``reset_session``, ``get_session_context``, ``layout_diagnostic``,
  ``quality_control``) are not exposed to the LLM. They remain on the
  underlying classes for internal use.
- The 6-step template-analysis facade collapses into a single atomic
  ``analyze_template`` call (diary 11/10).
- Geometry / style setters collapse into ``edit_shape(selector, patch)``.
"""
from __future__ import annotations

import functools
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .visio_tools import VisioTools
    from .prompt_tools import PromptTools


# ---------------------------------------------------------------------------
# rename helper
# ---------------------------------------------------------------------------

def _rename(method: Callable, new_name: str) -> Callable:
    """Return a wrapper around ``method`` exposed under ``new_name``.

    Agno's tool registrar uses ``__name__`` as the tool identifier so we
    deliberately rename the wrapper. The original callable is preserved
    as ``__wrapped__`` for introspection.
    """

    @functools.wraps(method)
    def _wrapper(*args, **kwargs):
        return method(*args, **kwargs)

    try:
        _wrapper.__name__ = new_name
        _wrapper.__qualname__ = new_name
    except (AttributeError, TypeError):
        pass
    return _wrapper


# ---------------------------------------------------------------------------
# composite adapters
# ---------------------------------------------------------------------------

def _build_edit_shape(visio_tools: "VisioTools") -> Callable:
    """Collapse position / size / style setters into one selector-based tool.

    ``patch`` schema (any subset)::

        {
          "position": {"x": float, "y": float, "relative": bool?},
          "size":     {"width": float, "height": float},
          "style":    {"line_width": float, "line_color": "#RRGGBB",
                       "fill_color": "#RRGGBB"}
        }
    """

    def edit_shape(
        shape_id: str,
        patch: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Update text, node_key, position, size and/or style of a shape.

        Args:
            shape_id: The target shape's ID.
            patch: A dict with any subset of
                ``{"text", "node_key", "position", "size", "style"}``.

                - ``text`` replaces the shape's display text.
                - ``node_key`` assigns a stable key so the shape can be
                  referenced by ``upsert_connector``.
                - ``position.relative=True`` applies the offset via
                  ``nudge_shape`` instead of absolute positioning.

        Returns:
            A single status line concatenating every sub-operation.
        """
        patch = patch or {}
        messages: List[str] = []

        text_val = patch.get("text")
        if text_val is not None:
            messages.append(visio_tools.update_shape_text(shape_id, str(text_val)))

        key_val = patch.get("node_key")
        if key_val:
            messages.append(visio_tools.set_node_key(shape_id, str(key_val)))

        pos = patch.get("position") or {}
        if pos:
            if pos.get("relative"):
                dx = float(pos.get("x", 0.0) or 0.0)
                dy = float(pos.get("y", 0.0) or 0.0)
                messages.append(visio_tools.nudge_shape(shape_id, dx, dy))
            elif "x" in pos or "y" in pos:
                messages.append(
                    visio_tools.set_shape_position(
                        shape_id,
                        float(pos.get("x", 0.0) or 0.0),
                        float(pos.get("y", 0.0) or 0.0),
                    )
                )

        size = patch.get("size") or {}
        if size and ("width" in size or "height" in size):
            messages.append(
                visio_tools.set_shape_size(
                    shape_id,
                    float(size.get("width", 0.0) or 0.0),
                    float(size.get("height", 0.0) or 0.0),
                )
            )

        style = patch.get("style") or {}
        if "line_width" in style and style["line_width"] is not None:
            messages.append(
                visio_tools.set_line_width(shape_id, float(style["line_width"]))
            )
        if style.get("line_color"):
            messages.append(
                visio_tools.set_line_color(shape_id, str(style["line_color"]))
            )
        if style.get("fill_color"):
            messages.append(
                visio_tools.set_fill_color(shape_id, str(style["fill_color"]))
            )

        if not messages:
            return "✗ edit_shape called with empty patch; nothing to do."
        return " | ".join(messages)

    return edit_shape


def _build_search_templates(visio_tools: "VisioTools") -> Callable:
    """Unified template search. Empty ``keywords`` lists the whole library."""

    def search_templates(keywords: Optional[List[str]] = None) -> str:
        """List or search templates in the curated library.

        Args:
            keywords: Optional list of keywords. Empty / ``None`` returns
                the full library listing.
        """
        kws = [k for k in (keywords or []) if k]
        if not kws:
            return visio_tools.list_library_templates()
        return visio_tools.search_library_templates(kws)

    return search_templates


def _build_search_stencils(visio_tools: "VisioTools") -> Callable:
    """Unified stencil search. Empty ``keywords`` lists the whole library."""

    def search_stencils(keywords: Optional[List[str]] = None) -> str:
        """List or search stencil collections.

        Args:
            keywords: Optional list of keywords. Empty / ``None`` returns
                the full stencil listing.
        """
        kws = [k for k in (keywords or []) if k]
        if not kws:
            return visio_tools.list_library_stencils()
        return visio_tools.search_library_stencils(kws)

    return search_stencils


def _build_render_page(visio_tools: "VisioTools") -> Callable:
    """Expose page rendering as a single canonical tool."""

    def render_page(
        page: int = 0,
        scale: float = 2.0,
        mode: str = "url",
        filepath: Optional[str] = None,
    ) -> str:
        """Render the current (or given) document page to a preview image.

        Returns a markdown image string (``![](<src>)``) suitable for inline
        display in chat UIs. Internally tries multiple rendering backends
        (Microsoft Visio COM, Aspose.Diagram, LibreOffice+Poppler) so that the
        tool works on Windows even when LibreOffice cannot render the VSDX.

        Args:
            page: Zero-based page index.
            scale: Render scale factor (1.0 ≈ 96 DPI; clamped to [0.5, 3.0]).
            mode: ``"url"`` (default) saves the PNG under ``outputs/static/visio``
                and returns a relative URL — recommended for any non-trivial
                diagram. ``"data"`` returns an inline base64 data URI and
                automatically falls back to URL mode if the payload would
                exceed the chat-friendly size cap.
            filepath: Optional path override; defaults to the currently
                loaded document.
        """
        from ..utils.visio_render import (
            render_and_save_png,
            render_vsdx_page_to_data_uri,
        )

        target = filepath or visio_tools.current_file_path
        if not target:
            return "✗ No document open. Call open_document first."

        try:
            if mode == "data":
                data_uri = render_vsdx_page_to_data_uri(
                    target, page, scale=scale, allowed_extra_path=target
                )
                cap = getattr(visio_tools, "_max_inline_data_uri_chars", 120_000)
                if data_uri and len(data_uri) > cap:
                    result = render_and_save_png(
                        target, page, scale=scale, allowed_extra_path=target
                    )
                    url = result.get("absolute_url") or result.get("url")
                    return f"✓ Rendered (data URI too large; using URL)\n\n![]({url})"
                return f"✓ Rendered\n\n![]({data_uri})"

            result = render_and_save_png(
                target, page, scale=scale, allowed_extra_path=target
            )
            url = result.get("absolute_url") or result.get("url")
            return f"✓ Rendered\n\n![]({url})"
        except Exception as exc:
            return f"✗ Render failed: {exc}"

    return render_page


# ---------------------------------------------------------------------------
# primary consolidated surface (exactly 15 tools)
# ---------------------------------------------------------------------------

def get_consolidated_tools(
    visio_tools: "VisioTools",
    prompt_tools: "PromptTools",
) -> List[Callable]:
    """Return the canonical 15-tool LLM-facing surface.

    Contract (see refine/CORE_CAPABILITIES.md §2 and MCP_CONTRACT.md):
      1.  recommend_template
      2.  search_templates
      3.  analyze_template       (atomic 6-step bundle)
      4.  search_stencils
      5.  get_stencil
      6.  open_document
      7.  create_from_template
      8.  save_document
      9.  render_page
      10. upsert_shape            (idempotent, key-based)
      11. upsert_connector        (idempotent, edge-key based)
      12. update_text
      13. remove_shape            (with smart reconnect)
      14. edit_shape              (position + size + style patch)
      15. insert_from_stencil
    """
    return [
        # --- discovery / recommendation ---
        _rename(prompt_tools.recommend_template, "recommend_template"),
        _rename(_build_search_templates(visio_tools), "search_templates"),
        _rename(prompt_tools.analyze_template_for_recommendation, "analyze_template"),
        # --- stencils ---
        _rename(_build_search_stencils(visio_tools), "search_stencils"),
        _rename(visio_tools.get_stencil_info, "get_stencil"),
        # --- document lifecycle ---
        _rename(visio_tools.load_diagram, "open_document"),
        _rename(visio_tools.create_from_template_and_load, "create_from_template"),
        _rename(visio_tools.save_diagram, "save_document"),
        _build_render_page(visio_tools),
        # --- mutation (idempotent only) ---
        _rename(visio_tools.add_or_update_shape, "upsert_shape"),
        _rename(visio_tools.add_or_update_connector, "upsert_connector"),
        _rename(visio_tools.update_shape_text, "update_text"),
        _rename(visio_tools.remove_shape_smart, "remove_shape"),
        _build_edit_shape(visio_tools),
        _rename(visio_tools.add_shape_from_stencil, "insert_from_stencil"),
    ]


def get_agent_tools(
    visio_tools: "VisioTools",
    prompt_tools: "PromptTools",
) -> List[Callable]:
    """Return the LLM-facing tool list for the agno Visio agent.

    Thin alias for :func:`get_consolidated_tools`. The deprecation alias
    band has been removed — all legacy names were retired in this
    refactor pass. If a legacy name is still required, add it back
    explicitly on the underlying class and register it here.
    """
    return get_consolidated_tools(visio_tools, prompt_tools)


CONSOLIDATED_TOOL_NAMES = (
    "recommend_template",
    "search_templates",
    "analyze_template",
    "search_stencils",
    "get_stencil",
    "open_document",
    "create_from_template",
    "save_document",
    "render_page",
    "upsert_shape",
    "upsert_connector",
    "update_text",
    "remove_shape",
    "edit_shape",
    "insert_from_stencil",
)
