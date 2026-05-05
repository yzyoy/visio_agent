"""
Consolidated LLM-facing tool surface (16 canonical tools).

This module is the single source of truth for the LLM-visible tool
contract. It contains thin renames / adapters over methods of
:class:`visio_core.tools.visio_tools.VisioTools` and
:class:`visio_core.tools.prompt_tools.PromptTools`. No Visio operation
is re-implemented here.

Design rules:

- Exactly 16 public names. Adding a name requires a matching update in
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
from html import escape as html_escape
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
          "text":     "single-line replacement text",
          "node_key": "stable-shape-key",
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

                - ``text`` replaces the shape's display text. Embedded
                  line breaks are normalized to spaces.
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
    """Expose page rendering as a single canonical tool.

    Pipeline-consistency note
    -------------------------
    Every preview surface in the system (the ``/api/visio/preview`` HTML
    viewer, the ``/api/visio/render`` raw PNG endpoint, and this tool) now
    funnels through :func:`render_and_cache_preview`. The cached PNG is
    rendered at a fixed high-quality scale (``VISIO_PREVIEW_RENDER_SCALE``,
    default 2.0 ≈ 192 DPI) so the *fit-window* CSS in the HTML viewer can
    downscale the natural image without ever cropping it. Returning the
    same PNG bytes (or the same canonical ``/api/visio/render?path=...``
    URL) from this tool guarantees that what the chat UI shows matches the
    interactive viewer pixel-for-pixel — no half-rendered titles, no
    blank-page fallbacks, no silent backend drift.
    """

    import os
    from urllib.parse import quote

    base_url = (
        os.getenv("VISIO_PREVIEW_BASE_URL")
        or "http://localhost:7777"
    ).rstrip("/")

    def _build_links(target: str, page: int, revision: Optional[str] = None) -> tuple[str, str]:
        encoded = quote(target, safe="/:")
        rev_suffix = f"&rev={quote(revision, safe='')}" if revision else ""
        png_url = f"{base_url}/api/visio/render?path={encoded}&page={page}{rev_suffix}"
        viewer_url = f"{base_url}/api/visio/preview?path={encoded}&page={page}{rev_suffix}"
        return png_url, viewer_url

    def render_page(
        page: int = 0,
        scale: float = 2.0,
        mode: str = "url",
        filepath: Optional[str] = None,
    ) -> str:
        """Render the current (or given) document page to a preview image.

        Returns a chat-ready response that contains **two** complete,
        fit-window viewable surfaces:

        1. An inline preview image rendered as chat-friendly HTML so agno
           keeps it inside the message viewport. The PNG is the identical,
           full-page, fit-window-ready image that the interactive viewer
           would display — never a cropped or half-rendered thumbnail.
        2. A markdown link to the interactive preview page
           (``[Open interactive preview](http://.../api/visio/preview?...)``).
           The link **must** be forwarded verbatim to the user so they
           can zoom, toggle fit/actual mode, and re-render on demand.

        Internally this funnels through
        :func:`visio_core.utils.visio_render.render_and_cache_preview`,
        the same pipeline used by ``/api/visio/preview``. This guarantees
        the chat preview is byte-identical to the viewer preview and
        plays nicely with the cache invalidation logic
        (``outputs/Preview_pngs``).

        Args:
            page: Zero-based page index.
            scale: Cache-miss render scale (1.0 ≈ 96 DPI; clamped to
                [0.5, 3.0]). Ignored on cache hit — zoom and fit/actual
                toggles are client-side concerns.
            mode: ``"url"`` (default, recommended) returns a revisioned
                ``/api/visio/render`` URL so repeated edits do not reuse a
                stale browser-cached preview.
                ``"data"`` inlines the PNG as a base64 data URI for
                offline / log replay; it auto-falls-back to URL mode when
                the payload would exceed the chat-friendly size cap.
            filepath: Optional path override; defaults to the currently
                loaded document.
        """
        from ..utils.visio_render import (
            png_to_data_uri,
            render_and_cache_preview,
        )

        target = filepath or visio_tools.current_file_path
        if not target:
            return "✗ No document open. Call open_document first."

        try:
            s = float(scale)
        except Exception:
            s = 2.0
        s = max(0.5, min(3.0, s))

        try:
            result = render_and_cache_preview(
                target, page=page, scale=s, allowed_extra_path=target
            )
        except Exception as exc:
            return f"✗ Render failed: {exc}"

        png_url, viewer_url = _build_links(target, page, result.get("key"))
        viewer_link = f"[Open interactive preview (fit window)]({viewer_url})"

        def _inline_preview_markup(src: str) -> str:
            safe_src = html_escape(src, quote=True)
            safe_viewer = html_escape(viewer_url, quote=True)
            return (
                '<a href="'
                f"{safe_viewer}"
                '" target="_blank" rel="noopener noreferrer">'
                '<img src="'
                f"{safe_src}"
                '" alt="Visio preview (fit window)" '
                'style="display:block; max-width:100%; max-height:70vh; '
                'width:auto; height:auto; object-fit:contain;" />'
                "</a>"
            )

        if mode == "data":
            png_bytes = result.get("bytes") or b""
            cap = getattr(visio_tools, "_max_inline_data_uri_chars", 120_000)
            data_uri = png_to_data_uri(png_bytes) if png_bytes else ""
            if data_uri and len(data_uri) <= cap:
                return (
                    "✓ Rendered (fit-window preview)\n\n"
                    f"{_inline_preview_markup(data_uri)}\n\n"
                    f"{viewer_link}"
                )
            # Data URI would blow the chat budget — fall back to the
            # canonical URL form. The interactive link is still returned
            # so the user retains full fit-window viewing.
            return (
                "✓ Rendered (data URI too large; using URL)\n\n"
                f"{_inline_preview_markup(png_url)}\n\n"
                f"{viewer_link}"
            )

        return (
            "✓ Rendered (fit-window preview)\n\n"
            f"{_inline_preview_markup(png_url)}\n\n"
            f"{viewer_link}"
        )

    return render_page


# ---------------------------------------------------------------------------
# primary consolidated surface (exactly 16 tools)
# ---------------------------------------------------------------------------

def get_consolidated_tools(
    visio_tools: "VisioTools",
    prompt_tools: "PromptTools",
) -> List[Callable]:
    """Return the canonical 16-tool LLM-facing surface.

    Contract (see refine/CORE_CAPABILITIES.md §2 and MCP_CONTRACT.md):
      1.  recommend_template
      2.  search_templates
      3.  analyze_template       (atomic 6-step bundle)
      4.  search_stencils
      5.  get_stencil
      6.  open_document
      7.  create_from_template
      8.  save_document
      9.  fit_page_to_drawing
      10. render_page
      11. upsert_shape            (idempotent, key-based)
      12. upsert_connector        (idempotent, edge-key based)
      13. update_text
      14. remove_shape            (smart reconnect; connector IDs auto-route)
      15. edit_shape              (position + size + style patch)
      16. insert_from_stencil
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
        _rename(visio_tools.fit_page_to_drawing, "fit_page_to_drawing"),
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
    "fit_page_to_drawing",
    "render_page",
    "upsert_shape",
    "upsert_connector",
    "update_text",
    "remove_shape",
    "edit_shape",
    "insert_from_stencil",
)
