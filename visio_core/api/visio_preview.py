from typing import Optional
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, HTMLResponse, FileResponse

from ..utils.visio_render import render_vsdx_page_to_png
from ..utils.exceptions import FileError, VisioError


router = APIRouter()


@router.get("/render", response_class=Response)
def render(
    path: str = Query(..., description="Path to .vsdx under assets/, outputs/, or tests/"),
    page: int = Query(0, ge=0, description="0-based page index"),
    scale: float = Query(2.0, gt=0, description="Scale multiplier; 1.0 ≈ 96 DPI"),
):
    try:
        png = render_vsdx_page_to_png(path, page=page, scale=scale)
        return Response(content=png, media_type="image/png")
    except FileError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 400
        raise HTTPException(status_code=status, detail=msg)
    except VisioError as e:
        msg = str(e)
        # Map dependency-missing cases to HTTP 501, conversion/render errors to 500
        if "missing dependency" in msg.lower():
            status = 501
        else:
            status = 500
        raise HTTPException(status_code=status, detail=msg)


@router.get("/preview", response_class=HTMLResponse)
def preview_page(
    path: Optional[str] = None,
    file: Optional[str] = None,  # Support 'file' parameter for backward compatibility
    page: int = 0,
    scale: float = 2.0,
):
    # Enhanced self-contained HTML preview with view mode controls
    safe_path = path or file or "tests/fixtures/transformer_architecture.vsdx"
    html = f"""
<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Visio PNG Preview</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; }}
    .row {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }}
    input, select, button {{ padding: 6px 8px; font-size: 14px; }}
    .hint {{ color: #6b7280; font-size: 12px; margin-top: 4px; }}
    #info {{ color: #059669; font-size: 13px; margin: 8px 0; font-weight: 500; }}
    #imgContainer {{ 
      margin-top: 16px; 
      border: 1px solid #e5e7eb; 
      background: #f9fafb;
      overflow: auto;
      max-height: calc(100vh - 200px);
    }}
    #img {{ 
      border: 1px solid #e5e7eb; 
      background: #fff;
      display: block;
      cursor: crosshair;
    }}
    #img.fit-window {{ max-width: 100%; height: auto; }}
    #img.actual-size {{ max-width: none; }}
    .button-group {{ display: flex; gap: 8px; flex-wrap: wrap; }}
    .btn {{ 
      padding: 6px 12px; 
      font-size: 14px; 
      border: 1px solid #d1d5db;
      background: #fff;
      cursor: pointer;
      border-radius: 4px;
    }}
    .btn:hover {{ background: #f3f4f6; }}
    .btn.active {{ background: #3b82f6; color: white; border-color: #3b82f6; }}
  </style>
  <script>
    let viewMode = 'fit'; // 'fit' or 'actual'
    
    function updateImg() {{
      const path = document.getElementById('path').value;
      const page = document.getElementById('page').value;
      const scale = document.getElementById('scale').value;
      const ts = Date.now();
      const rand = Math.random();
      const url = `/api/visio/render?path=${{encodeURIComponent(path)}}&page=${{page}}&scale=${{scale}}&t=${{ts}}&r=${{rand}}`;
      const img = document.getElementById('img');
      const info = document.getElementById('info');
      
      info.textContent = 'Loading...';
      
      img.onload = function() {{
        info.textContent = `Image loaded: ${{img.naturalWidth}} × ${{img.naturalHeight}}px (Scale: ${{scale}}x, DPI: ${{Math.round(96 * scale)}})`;
        info.style.color = '#059669';
      }};
      
      img.onerror = function() {{
        info.textContent = `❌ Error loading image from: ${{url}}`;
        info.style.color = '#dc2626';
        console.error('Failed to load image:', url);
        
        // Try to fetch and show the actual error
        fetch(url)
          .then(response => {{
            if (!response.ok) {{
              return response.text().then(text => {{
                info.textContent = `❌ Error ${{response.status}}: ${{text.substring(0, 200)}}`;
              }});
            }}
          }})
          .catch(err => {{
            console.error('Fetch error:', err);
            info.textContent = `❌ Network error: Check if path "${{path}}" is correct. Must be under assets/, outputs/, or tests/`;
          }});
      }};
      
      img.src = url;
    }}
    
    function setViewMode(mode) {{
      viewMode = mode;
      const img = document.getElementById('img');
      const fitBtn = document.getElementById('fitBtn');
      const actualBtn = document.getElementById('actualBtn');
      
      if (mode === 'fit') {{
        img.className = 'fit-window';
        fitBtn.classList.add('active');
        actualBtn.classList.remove('active');
      }} else {{
        img.className = 'actual-size';
        fitBtn.classList.remove('active');
        actualBtn.classList.add('active');
      }}
    }}
    
    function loadPath(newPath) {{
      document.getElementById('path').value = newPath;
      updateImg();
    }}
    
    window.addEventListener('DOMContentLoaded', () => {{
      updateImg();
      setViewMode('fit');
    }});
  </script>
  </head>
  <body>
    <h2>Visio PNG Preview</h2>
    <div class=\"row\" style=\"margin-bottom: 12px;\">
      <label>Path <input id=\"path\" type=\"text\" size=\"60\" value=\"{safe_path}\" onchange=\"updateImg()\" /></label>
      <label>Page <input id=\"page\" type=\"number\" min=\"0\" value=\"{page}\" onchange=\"updateImg()\" /></label>
      <label>Scale
        <select id=\"scale\" onchange=\"updateImg()\">
          <option value=\"0.5\">0.5x</option>
          <option value=\"1\">1x</option>
          <option value=\"1.5\">1.5x</option>
          <option value=\"2\" selected>2x</option>
          <option value=\"3\">3x</option>
        </select>
      </label>
      <button class=\"btn\" onclick=\"updateImg()\">🔄 Refresh</button>
    </div>
    <div class=\"row\" style=\"margin-bottom: 8px;\">
      <span style=\"font-size: 14px; font-weight: 500;\">View Mode:</span>
      <div class=\"button-group\">
        <button id=\"fitBtn\" class=\"btn active\" onclick=\"setViewMode('fit')\">📐 Fit Window</button>
        <button id=\"actualBtn\" class=\"btn\" onclick=\"setViewMode('actual')\">🔍 Actual Size</button>
      </div>
    </div>
    <div class=\"hint\">
      <strong>⚠️ Important:</strong> To see scale changes clearly, switch to <strong>"Actual Size"</strong> mode. In "Fit Window" mode, CSS scaling may hide DPI differences.<br/>
      Allowed roots: <code>assets/</code>, <code>outputs/</code>, <code>tests/</code> (relative to repo root)
    </div>
    <div id=\"info\"></div>
    <div id=\"imgContainer\">
      <img id=\"img\" alt=\"PNG preview\" />
    </div>
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
        return HTMLResponse("""
        <html>
        <body>
        <h1>测试页面未找到</h1>
        <p>请确保 test_image.html 文件存在</p>
        </body>
        </html>
        """)

