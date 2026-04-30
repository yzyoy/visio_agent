from typing import Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response, HTMLResponse, FileResponse, JSONResponse

from ..utils.visio_render import render_and_cache_preview
from ..utils.exceptions import FileError, VisioError


router = APIRouter()


def _map_visio_error(exc: VisioError) -> HTTPException:
    msg = str(exc)
    status = 501 if "missing dependency" in msg.lower() else 500
    return HTTPException(status_code=status, detail=msg)


def _map_file_error(exc: FileError) -> HTTPException:
    msg = str(exc)
    status = 404 if "not found" in msg.lower() else 400
    return HTTPException(status_code=status, detail=msg)


@router.get("/render", response_class=Response)
def render(
    request: Request,
    path: str = Query(..., description="Path to .vsdx under assets/, outputs/, or tests/"),
    page: int = Query(0, ge=0, description="0-based page index"),
    scale: float = Query(
        2.0,
        gt=0,
        description=(
            "Render scale used only on cache miss; subsequent zooms reuse "
            "the cached PNG and are handled client-side via CSS."
        ),
    ),
    nocache: bool = Query(False, description="Force re-render and overwrite the cached PNG"),
):
    """Serve the cached preview PNG.

    Behaviour:
    - First request for a given ``(path, page)`` renders the VSDX at
      ``scale`` and caches the result under ``outputs/Preview_pngs/``.
    - Subsequent requests reuse the cached PNG (regardless of ``scale``)
      so that zooming or toggling fit/actual view does not trigger a
      re-render. Cache invalidates automatically when the source file
      is modified.
    """
    try:
        result = render_and_cache_preview(
            path, page=page, scale=scale, force=nocache
        )
    except FileError as e:
        raise _map_file_error(e)
    except VisioError as e:
        raise _map_visio_error(e)

    etag = f'W/"{result["key"]}-{result["mtime"]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})

    return Response(
        content=result["bytes"],
        media_type="image/png",
        headers={
            "ETag": etag,
            # Cache for 5 min on the browser, but always revalidate so
            # fresh edits to the source file are picked up promptly.
            "Cache-Control": "public, max-age=300, must-revalidate",
            "X-Visio-Cache": "HIT" if result["cached"] else "MISS",
            "X-Visio-Cache-File": Path(result["file"]).name,
        },
    )


@router.get("/render/info")
def render_info(
    path: str = Query(..., description="Path to .vsdx under assets/, outputs/, or tests/"),
    page: int = Query(0, ge=0),
    scale: float = Query(2.0, gt=0),
):
    """Return metadata for the cached preview without streaming the PNG.

    Useful for clients that want to know whether the next ``/render`` call
    will hit the cache or trigger a render.
    """
    try:
        result = render_and_cache_preview(path, page=page, scale=scale)
    except FileError as e:
        raise _map_file_error(e)
    except VisioError as e:
        raise _map_visio_error(e)

    return JSONResponse(
        {
            "key": result["key"],
            "file": result["file"],
            "size": len(result["bytes"]),
            "cached": result["cached"],
            "mtime": result["mtime"],
            "src_mtime": result["src_mtime"],
            "etag": f'W/"{result["key"]}-{result["mtime"]}"',
        }
    )


@router.get("/preview", response_class=HTMLResponse)
def preview_page(
    path: Optional[str] = None,
    file: Optional[str] = None,  # Support 'file' parameter for backward compatibility
    page: int = 0,
    scale: float = 1.0,
):
    # Modern self-contained HTML preview.
    #
    # Performance / UX notes:
    # - The PNG is fetched once and reused; the backend caches the rendered
    #   image under outputs/Preview_pngs/.
    # - Zoom and fit/actual toggles are handled client-side. Zooming
    #   *preserves* the current view mode rather than auto-switching to
    #   actual_size — the slider scales the fitted size in fit mode and the
    #   natural size in actual mode.
    safe_path = path or file or "tests/fixtures/transformer_architecture.vsdx"
    html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Visio Preview</title>
  <style>
    :root {{
      --bg: #f5f7fa;
      --surface: #ffffff;
      --surface-2: #fafbfc;
      --border: #e4e7eb;
      --border-strong: #cbd2d9;
      --text: #1f2937;
      --text-muted: #6b7280;
      --text-faint: #9ca3af;
      --primary: #2563eb;
      --primary-hover: #1d4ed8;
      --primary-soft: #eff6ff;
      --success: #059669;
      --success-soft: #ecfdf5;
      --warning: #d97706;
      --warning-soft: #fffbeb;
      --danger: #dc2626;
      --shadow-sm: 0 1px 2px rgba(15,23,42,0.05);
      --shadow-md: 0 4px 12px rgba(15,23,42,0.06);
      --radius: 10px;
      --radius-sm: 6px;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, "Helvetica Neue", Arial, sans-serif;
      font-size: 14px;
      color: var(--text);
      background: var(--bg);
      -webkit-font-smoothing: antialiased;
    }}

    .app {{
      display: flex;
      flex-direction: column;
      min-height: 100vh;
      padding: 20px;
      gap: 14px;
      max-width: 1600px;
      margin: 0 auto;
    }}

    /* ---------- Header ---------- */
    .header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }}
    .title {{
      font-size: 18px;
      font-weight: 600;
      letter-spacing: -0.01em;
      color: var(--text);
      margin: 0;
    }}
    .subtitle {{
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 2px;
    }}
    .header-meta {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 4px 10px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      background: #eef2f7;
      color: #4b5563;
      letter-spacing: 0.02em;
      border: 1px solid transparent;
    }}
    .badge .dot {{
      width: 6px; height: 6px; border-radius: 50%;
      background: currentColor; opacity: 0.6;
    }}
    .badge.hit {{ background: var(--success-soft); color: var(--success); border-color: #a7f3d0; }}
    .badge.miss {{ background: var(--warning-soft); color: var(--warning); border-color: #fde68a; }}

    /* ---------- Controls Card ---------- */
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow-sm);
    }}
    .controls {{
      padding: 14px 16px;
      display: grid;
      grid-template-columns: minmax(280px, 1fr) auto auto auto auto;
      gap: 12px;
      align-items: center;
    }}
    @media (max-width: 900px) {{
      .controls {{ grid-template-columns: 1fr 1fr; }}
      .controls .field-path {{ grid-column: span 2; }}
      .controls .field-zoom {{ grid-column: span 2; }}
    }}

    .field {{ display: flex; flex-direction: column; gap: 4px; min-width: 0; }}
    .label {{
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--text-faint);
    }}
    .input {{
      width: 100%;
      padding: 8px 10px;
      font-size: 13px;
      color: var(--text);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      outline: none;
      transition: border-color 0.15s, box-shadow 0.15s;
    }}
    .input:hover {{ border-color: var(--border-strong); }}
    .input:focus {{
      border-color: var(--primary);
      box-shadow: 0 0 0 3px rgba(37,99,235,0.12);
    }}
    .field-page {{ width: 90px; }}
    .field-page .input {{ text-align: center; }}

    /* Smart slider */
    .field-zoom {{ min-width: 220px; }}
    .zoom-row {{
      display: flex; align-items: center; gap: 10px;
      padding: 6px 10px;
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--surface);
      transition: border-color 0.15s, box-shadow 0.15s, opacity 0.15s;
    }}
    .zoom-row:hover {{ border-color: var(--border-strong); }}
    .zoom-row.is-disabled {{ opacity: 0.55; }}
    .slider {{
      -webkit-appearance: none; appearance: none;
      flex: 1;
      height: 4px;
      background: linear-gradient(to right, var(--primary) 0%, var(--primary) var(--fill,40%), #e5e7eb var(--fill,40%), #e5e7eb 100%);
      border-radius: 999px;
      outline: none;
      cursor: pointer;
    }}
    .slider::-webkit-slider-thumb {{
      -webkit-appearance: none; appearance: none;
      width: 16px; height: 16px;
      border-radius: 50%;
      background: #fff;
      border: 2px solid var(--primary);
      box-shadow: 0 1px 3px rgba(15,23,42,0.15);
      cursor: grab;
      transition: transform 0.1s ease, box-shadow 0.15s;
    }}
    .slider::-webkit-slider-thumb:hover {{ transform: scale(1.1); }}
    .slider:active::-webkit-slider-thumb {{ cursor: grabbing; transform: scale(1.15); box-shadow: 0 0 0 6px rgba(37,99,235,0.15); }}
    .slider::-moz-range-thumb {{
      width: 16px; height: 16px;
      border-radius: 50%;
      background: #fff;
      border: 2px solid var(--primary);
      box-shadow: 0 1px 3px rgba(15,23,42,0.15);
      cursor: grab;
    }}
    .zoom-value {{
      min-width: 52px;
      text-align: right;
      font-variant-numeric: tabular-nums;
      font-weight: 600;
      font-size: 13px;
      color: var(--text);
    }}

    /* Pill toggle (Fit / Actual) */
    .toggle {{
      display: inline-flex;
      padding: 3px;
      background: #f1f3f7;
      border: 1px solid var(--border);
      border-radius: 999px;
      gap: 2px;
    }}
    .toggle button {{
      border: none;
      background: transparent;
      color: var(--text-muted);
      padding: 6px 14px;
      font-size: 13px;
      font-weight: 500;
      border-radius: 999px;
      cursor: pointer;
      transition: background 0.15s, color 0.15s, box-shadow 0.15s;
    }}
    .toggle button:hover {{ color: var(--text); }}
    .toggle button.active {{
      background: var(--surface);
      color: var(--primary);
      box-shadow: var(--shadow-sm);
    }}

    /* Buttons */
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 8px 14px;
      font-size: 13px;
      font-weight: 500;
      color: var(--text);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      cursor: pointer;
      transition: background 0.15s, border-color 0.15s, color 0.15s;
      white-space: nowrap;
    }}
    .btn:hover {{ background: var(--surface-2); border-color: var(--border-strong); }}
    .btn-primary {{
      color: #fff; background: var(--primary); border-color: var(--primary);
    }}
    .btn-primary:hover {{ background: var(--primary-hover); border-color: var(--primary-hover); }}

    /* ---------- Status / hint ---------- */
    .status-row {{
      display: flex; align-items: center; gap: 10px;
      padding: 0 4px;
      font-size: 12px;
      color: var(--text-muted);
      flex-wrap: wrap;
    }}
    .status {{
      display: inline-flex; align-items: center; gap: 6px;
      font-weight: 500;
      color: var(--success);
    }}
    .status.is-error {{ color: var(--danger); }}
    .status.is-loading {{ color: var(--text-muted); }}
    .status.is-loading::before {{
      content: ""; width: 10px; height: 10px;
      border: 2px solid #d1d5db;
      border-top-color: var(--primary);
      border-radius: 50%;
      animation: spin 0.7s linear infinite;
    }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    code {{
      font-family: "SF Mono", Menlo, Consolas, monospace;
      font-size: 11.5px;
      background: var(--surface-2);
      padding: 1px 5px;
      border-radius: 4px;
      border: 1px solid var(--border);
      color: var(--text);
    }}

    /* ---------- Canvas ---------- */
    .canvas {{
      flex: 1;
      min-height: 360px;
      background: var(--surface-2);
      background-image:
        linear-gradient(45deg, #ececf2 25%, transparent 25%),
        linear-gradient(-45deg, #ececf2 25%, transparent 25%),
        linear-gradient(45deg, transparent 75%, #ececf2 75%),
        linear-gradient(-45deg, transparent 75%, #ececf2 75%);
      background-size: 18px 18px;
      background-position: 0 0, 0 9px, 9px -9px, -9px 0;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      overflow: auto;
      padding: 20px;
      display: flex;
      align-items: flex-start;
      justify-content: center;
      box-shadow: var(--shadow-sm) inset;
    }}
    .canvas.is-fit {{ align-items: center; padding: 16px; }}
    #img {{
      display: block;
      background: #fff;
      box-shadow: var(--shadow-md);
      border-radius: 4px;
      transition: width 0.08s ease-out;
    }}
    #img.fit-window {{ max-width: 100%; max-height: calc(100vh - 240px); height: auto; width: auto; }}
    #img.actual-size {{ max-width: none; }}
    #img:not([src]) {{ display: none; }}
  </style>
</head>
<body>
  <div class=\"app\">
    <div class=\"header\">
      <div>
        <h1 class=\"title\">Visio Preview</h1>
        <div class=\"subtitle\">Allowed roots: <code>assets/</code> · <code>outputs/</code> · <code>tests/</code></div>
      </div>
      <div class=\"header-meta\">
        <span id=\"cacheBadge\" class=\"badge\" style=\"display:none;\"><span class=\"dot\"></span><span id=\"cacheBadgeText\"></span></span>
      </div>
    </div>

    <div class=\"card\">
      <div class=\"controls\">
        <div class=\"field field-path\">
          <label class=\"label\" for=\"path\">File</label>
          <input id=\"path\" class=\"input\" type=\"text\" value=\"{safe_path}\" spellcheck=\"false\" autocomplete=\"off\" onchange=\"loadImage(false)\" />
        </div>
        <div class=\"field field-page\">
          <label class=\"label\" for=\"page\">Page</label>
          <input id=\"page\" class=\"input\" type=\"number\" min=\"0\" value=\"{page}\" onchange=\"loadImage(false)\" />
        </div>
        <div class=\"field field-zoom\">
          <label class=\"label\" for=\"zoomSlider\">Zoom</label>
          <div id=\"zoomRow\" class=\"zoom-row\">
            <input id=\"zoomSlider\" class=\"slider\" type=\"range\" min=\"0.25\" max=\"4\" step=\"0.05\" value=\"1\"
                   oninput=\"onSliderInput(this.value)\" aria-label=\"Zoom level\" />
            <span id=\"zoomValue\" class=\"zoom-value\">100%</span>
          </div>
        </div>
        <div class=\"field\">
          <label class=\"label\">Display</label>
          <div class=\"toggle\" role=\"tablist\" aria-label=\"Display mode\">
            <button id=\"fitBtn\" class=\"active\" role=\"tab\" aria-selected=\"true\" onclick=\"setViewMode('fit')\">Fit Window</button>
            <button id=\"actualBtn\" role=\"tab\" aria-selected=\"false\" onclick=\"setViewMode('actual')\">Actual Size</button>
          </div>
        </div>
        <div class=\"field\">
          <label class=\"label\">&nbsp;</label>
          <button class=\"btn\" onclick=\"loadImage(true)\" title=\"Re-render the source VSDX and overwrite the cached PNG\">Re-render</button>
        </div>
      </div>
    </div>

    <div class=\"status-row\">
      <span id=\"status\" class=\"status\"></span>
    </div>

    <div id=\"canvas\" class=\"canvas is-fit\">
      <img id=\"img\" alt=\"Visio page preview\" />
    </div>
  </div>

  <script>
    // Default to fit_window on initial load. Zooming preserves the current
    // view mode: in fit mode the slider scales the *fitted* size; in actual
    // mode it scales the *natural* size. Only path/page changes trigger a
    // re-fetch of the cached PNG; everything else is client-side layout.
    let viewMode = 'fit';
    let zoom = 1.0;
    let lastPath = null;
    let lastPage = null;

    const $ = (id) => document.getElementById(id);

    function buildSrc(path, page) {{
      return `/api/visio/render?path=${{encodeURIComponent(path)}}&page=${{page}}`;
    }}

    function clamp(v, lo, hi) {{ return Math.max(lo, Math.min(hi, v)); }}

    function updateSliderFill(value) {{
      const slider = $('zoomSlider');
      const min = parseFloat(slider.min), max = parseFloat(slider.max);
      const pct = ((parseFloat(value) - min) / (max - min)) * 100;
      slider.style.setProperty('--fill', pct + '%');
    }}

    function updateZoomDisplay(value) {{
      $('zoomValue').textContent = Math.round(parseFloat(value) * 100) + '%';
      updateSliderFill(value);
    }}

    // Compute the width the image would have under the canonical fit-window
    // CSS (`max-width: 100%`, `max-height: calc(100vh - 240px)`), preserving
    // the natural aspect ratio. Used as the baseline when the user zooms
    // *while staying in fit mode*.
    function getFitBaseWidth() {{
      const img = $('img');
      if (!img.naturalWidth || !img.naturalHeight) return 0;
      const canvas = $('canvas');
      const cs = window.getComputedStyle(canvas);
      const padX = (parseFloat(cs.paddingLeft) || 0)
                 + (parseFloat(cs.paddingRight) || 0);
      const availW = Math.max(1, canvas.clientWidth - padX);
      const availH = Math.max(1, window.innerHeight - 240);
      const natW = img.naturalWidth;
      const natH = img.naturalHeight;
      const ratio = natW / Math.max(1, natH);
      let w = Math.min(natW, availW);
      if (w / ratio > availH) w = availH * ratio;
      return Math.max(1, w);
    }}

    function applyZoom() {{
      const img = $('img');
      const canvas = $('canvas');
      if (!img.naturalWidth) return;

      const isUnitFit = Math.abs(zoom - 1.0) < 0.001;

      if (viewMode === 'fit' && isUnitFit) {{
        // Pure CSS fit — keep the existing default behaviour intact.
        img.classList.remove('actual-size');
        img.classList.add('fit-window');
        canvas.classList.add('is-fit');
        img.style.width = '';
        img.style.height = '';
        return;
      }}

      // Anything else (actual mode at any zoom, or fit mode with zoom != 1)
      // is rendered with an explicit pixel width so the canvas can scroll.
      // The mode is *preserved*; only the baseline differs.
      const baseWidth = (viewMode === 'fit')
        ? getFitBaseWidth()
        : img.naturalWidth;

      img.classList.remove('fit-window');
      img.classList.add('actual-size');
      canvas.classList.remove('is-fit');
      img.style.width = (baseWidth * zoom) + 'px';
      img.style.height = 'auto';
    }}

    function setStatus(text, kind) {{
      const el = $('status');
      el.textContent = text || '';
      el.className = 'status' + (kind ? ' is-' + kind : '');
    }}

    function setCacheBadge(status) {{
      const badge = $('cacheBadge');
      if (!status) {{ badge.style.display = 'none'; return; }}
      $('cacheBadgeText').textContent = 'cache · ' + status.toLowerCase();
      badge.className = 'badge ' + (status === 'HIT' ? 'hit' : status === 'MISS' ? 'miss' : '');
      badge.style.display = 'inline-flex';
    }}

    function loadImage(force) {{
      const path = $('path').value.trim();
      const page = $('page').value;
      const img = $('img');

      const sourceChanged = (path !== lastPath) || (page !== lastPage);
      if (!force && !sourceChanged && img.src) {{
        applyZoom();
        return;
      }}

      lastPath = path;
      lastPage = page;
      let url = buildSrc(path, page);
      if (force) url += `&nocache=true&t=${{Date.now()}}`;

      setStatus('Loading preview…', 'loading');
      setCacheBadge(null);

      const t0 = performance.now();
      img.onload = function() {{
        const dt = (performance.now() - t0).toFixed(0);
        setStatus(`Loaded ${{img.naturalWidth}} × ${{img.naturalHeight}} px in ${{dt}} ms`);
        applyZoom();
        fetch(url, {{ method: 'GET', cache: 'no-store' }})
          .then(r => setCacheBadge(r.headers.get('X-Visio-Cache') || 'UNKNOWN'))
          .catch(() => {{}});
      }};
      img.onerror = function() {{
        setStatus(`Failed to load: ${{path}}`, 'error');
        fetch(url)
          .then(r => {{
            if (!r.ok) return r.text().then(t => setStatus(`Error ${{r.status}}: ${{t.substring(0, 200)}}`, 'error'));
          }})
          .catch(() => setStatus(`Network error. Check that "${{path}}" is under assets/, outputs/, or tests/`, 'error'));
      }};
      img.src = url;
    }}

    function setViewMode(mode) {{
      viewMode = mode;
      const fitBtn = $('fitBtn');
      const actualBtn = $('actualBtn');
      const zoomRow = $('zoomRow');

      const isFit = (mode === 'fit');
      fitBtn.classList.toggle('active', isFit);
      actualBtn.classList.toggle('active', !isFit);
      fitBtn.setAttribute('aria-selected', isFit ? 'true' : 'false');
      actualBtn.setAttribute('aria-selected', isFit ? 'false' : 'true');

      // Slider is always active — zoom now works in both modes by scaling
      // the appropriate baseline (fit width vs. natural width).
      zoomRow.classList.remove('is-disabled');

      // Layout (CSS classes + inline width/height) is owned by applyZoom().
      applyZoom();
    }}

    function onSliderInput(value) {{
      zoom = clamp(parseFloat(value) || 1.0, 0.25, 4.0);
      updateZoomDisplay(zoom);
      // Preserve the current view mode — zooming no longer forces a switch
      // to actual_size. The zoom baseline differs by mode (fit width vs.
      // natural width) and is handled inside applyZoom().
      applyZoom();
    }}

    // Convenience: Ctrl/Cmd + scroll over the canvas adjusts zoom.
    function onCanvasWheel(e) {{
      if (!(e.ctrlKey || e.metaKey)) return;
      e.preventDefault();
      const slider = $('zoomSlider');
      const step = parseFloat(slider.step) || 0.05;
      const delta = (e.deltaY < 0 ? 1 : -1) * step * 4;
      const next = clamp(zoom + delta, parseFloat(slider.min), parseFloat(slider.max));
      slider.value = next;
      onSliderInput(next);
    }}

    window.addEventListener('DOMContentLoaded', () => {{
      const slider = $('zoomSlider');
      zoom = parseFloat(slider.value) || 1.0;
      updateZoomDisplay(zoom);
      $('canvas').addEventListener('wheel', onCanvasWheel, {{ passive: false }});
      setViewMode('fit'); // default mode = fit_window
      loadImage(false);
    }});

    // Fit-mode zoom is anchored to the fitted size, which depends on the
    // viewport. Recompute the layout on resize so the image keeps tracking
    // the slider correctly without forcing a mode change.
    let _resizeRaf = 0;
    window.addEventListener('resize', () => {{
      if (_resizeRaf) cancelAnimationFrame(_resizeRaf);
      _resizeRaf = requestAnimationFrame(() => {{
        _resizeRaf = 0;
        if (viewMode === 'fit' && Math.abs(zoom - 1.0) >= 0.001) {{
          applyZoom();
        }}
      }});
    }});
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@router.get("/test", response_class=HTMLResponse)
def test_image_display():
    """Test page to verify image rendering in browser"""
    test_html_path = Path(__file__).parent / "test_image.html"
    if test_html_path.exists():
        return FileResponse(test_html_path)
    else:
        return HTMLResponse(
            """
        <html>
        <body>
        <h1>Test page not found</h1>
        <p>Ensure test_image.html exists alongside visio_preview.py</p>
        </body>
        </html>
        """
        )
