"""
Utilities to render Visio (.vsdx) files to PNG for frontend preview.

Pipeline (best-effort, no PyPI deps):
- LibreOffice (soffice) headless converts .vsdx -> .pdf
- Poppler (pdftocairo) renders a single PDF page -> .png

Caching strategy:
- Cache under system temp directory (e.g., %TEMP%/visio_renders on Windows, /tmp/visio_renders on Unix)
- Uses sha1(path+mtime+page+scale) for cache keys
- Reuse PDF/PNG if source .vsdx hasn't changed.
"""

import hashlib
import base64
import os
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional, Tuple, List

from .exceptions import FileError, VisioError

logger = logging.getLogger(__name__)


ALLOWED_ROOTS = [
    # Filled at runtime using repo root if available; fallback to relative dirs
    "assets",
    "outputs",
    "tests",
]


def _resolve_repo_root() -> Path:
    try:
        # This file: <repo>/visio_core/utils/visio_render.py
        return Path(__file__).resolve().parents[2]
    except Exception:
        return Path.cwd()


def _allowed_roots_abs() -> list[Path]:
    root = _resolve_repo_root()
    abs_roots: list[Path] = []
    for rel in ALLOWED_ROOTS:
        abs_roots.append((root / rel).resolve())
    return abs_roots


def _is_allowed_path(vsdx_path: Path, allowed_extra: Optional[Path] = None) -> bool:
    try:
        p = vsdx_path.resolve()
        if allowed_extra is not None:
            try:
                if p == allowed_extra.resolve():
                    return True
            except Exception:
                pass
        for base in _allowed_roots_abs():
            if str(p).startswith(str(base)):
                return True
        return False
    except Exception:
        return False


def _require_cmd(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise VisioError(
            f"Missing dependency: '{name}'. Install system packages 'libreoffice' and 'poppler-utils'.\n"
            f"To verify installation, run: {name} --version"
        )
    return path


def _list_temp_dir_contents(dir_path: Path) -> List[str]:
    """List files in a temp directory for diagnostics. Returns sanitized file names (no full paths)."""
    try:
        return [f.name for f in dir_path.iterdir() if f.is_file()]
    except Exception as e:
        return [f"<error listing dir: {e}>"]


def _run_subprocess_with_diagnostics(
    cmd: List[str],
    work_dir: Path,
    operation: str,
    timeout: int = 30
) -> Tuple[int, str, str]:
    """
    Run subprocess and capture diagnostics for error reporting.
    
    Returns:
        (returncode, stdout, stderr)
    
    Raises:
        VisioError on failure with detailed diagnostics
    """
    logger.debug(f"{operation}: Running command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        
        returncode = result.returncode
        stdout = result.stdout.strip() if result.stdout else ""
        stderr = result.stderr.strip() if result.stderr else ""
        
        # Log outputs (truncate if too large)
        if stdout:
            logger.debug(f"{operation} stdout (truncated): {stdout[:500]}")
        if stderr:
            logger.debug(f"{operation} stderr (truncated): {stderr[:500]}")
        logger.debug(f"{operation} return code: {returncode}")
        
        return returncode, stdout, stderr
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"{operation} timed out after {timeout}s")
        raise VisioError(
            f"{operation} timed out after {timeout}s. "
            f"Command: {' '.join(cmd)}\n"
            f"This may indicate LibreOffice is hanging. Try: killall soffice.bin"
        )
    except Exception as e:
        logger.error(f"{operation} subprocess error: {e}")
        raise VisioError(
            f"{operation} failed with exception: {e}\n"
            f"Command: {' '.join(cmd)}"
        )


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _get_pdf_pages(pdf_path: Path) -> Optional[int]:
    """Return number of pages using pdfinfo if available; None if unknown."""
    info = shutil.which("pdfinfo")
    if not info:
        return None
    try:
        out = subprocess.check_output([info, str(pdf_path)], stderr=subprocess.STDOUT, text=True)
        for line in out.splitlines():
            if line.strip().lower().startswith("pages:"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return int(parts[1].strip())
    except Exception:
        return None
    return None


def render_vsdx_page_to_png(
    vsdx_path: str,
    page: int = 0,
    scale: float = 2.0,
    allowed_extra_path: Optional[str] = None,
) -> bytes:
    """
    Render a .vsdx file page to PNG bytes.

    Args:
        vsdx_path: Path to the .vsdx file (must be under an allowed directory)
        page: 0-based page index
        scale: Scale multiplier (1.0 ~ ~96 DPI). We render at DPI = 96*scale.

    Returns:
        PNG bytes.
    """
    if page < 0:
        raise FileError("Page index must be >= 0", filepath=vsdx_path)
    try:
        dpi = max(72, int(96 * float(scale or 1.0)))
    except Exception:
        dpi = 192  # default 2x

    src = Path(vsdx_path)
    if not src.exists():
        raise FileError("Visio file not found", filepath=vsdx_path)
    extra = Path(allowed_extra_path).resolve() if allowed_extra_path else None
    if not _is_allowed_path(src, allowed_extra=extra):
        allowed_list = " | ".join([str(p) for p in _allowed_roots_abs()])
        raise FileError(
            f"Access denied. Path must be under allowed roots: {allowed_list}", filepath=str(src)
        )

    soffice = _require_cmd("soffice")
    pdftocairo = _require_cmd("pdftocairo")

    # Cache directory - use platform-appropriate temp location
    cache_root = Path(tempfile.gettempdir()) / "visio_renders"
    cache_root.mkdir(parents=True, exist_ok=True)

    # Build keys
    mtime = src.stat().st_mtime
    key_base = f"{src.resolve()}|{mtime}|{page}|{dpi}"
    key = _sha1(key_base)
    work_dir = cache_root / f"work_{key}"
    work_dir.mkdir(parents=True, exist_ok=True)

    cached_png = cache_root / f"{key}.png"
    if cached_png.exists():
        return cached_png.read_bytes()

    # Convert VSDX -> PDF (in work dir)
    # Use soffice to write output PDF into work_dir
    try:
        pdf_path = work_dir / f"{src.stem}.pdf"
        need_pdf = True
        if pdf_path.exists():
            # If existing PDF is newer than source VSDX, reuse
            need_pdf = pdf_path.stat().st_mtime < src.stat().st_mtime
        if (not pdf_path.exists()) or need_pdf:
            # Copy source into work dir to avoid clutter
            local_vsdx = work_dir / src.name
            if not local_vsdx.exists() or local_vsdx.stat().st_mtime < src.stat().st_mtime:
                shutil.copy2(str(src), str(local_vsdx))
            
            # Attempt 1: Try PDF export (existing approach)
            logger.debug("Attempting LibreOffice PDF conversion")
            returncode, stdout, stderr = _run_subprocess_with_diagnostics(
                [
                    soffice,
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(work_dir),
                    str(local_vsdx),
                ],
                work_dir=work_dir,
                operation="LibreOffice PDF conversion",
            )
            
            if returncode != 0:
                logger.warning(f"LibreOffice PDF conversion failed with code {returncode}")
            
            # Check if output was produced
            if not pdf_path.exists() or pdf_path.stat().st_size == 0:
                # Fallback 2: Try direct-to-PNG via soffice
                logger.debug("PDF conversion failed, attempting direct PNG conversion")
                png_direct = work_dir / f"{src.stem}.png"
                returncode2, stdout2, stderr2 = _run_subprocess_with_diagnostics(
                    [
                        soffice,
                        "--headless",
                        "--nologo",
                        "--nodefault",
                        "--convert-to",
                        "png",
                        "--outdir",
                        str(work_dir),
                        str(local_vsdx),
                    ],
                    work_dir=work_dir,
                    operation="LibreOffice PNG conversion",
                )
                
                if png_direct.exists() and png_direct.stat().st_size > 0:
                    # Success via direct PNG! Return it immediately
                    logger.info("Direct PNG conversion succeeded")
                    cached_png.write_bytes(png_direct.read_bytes())
                    return cached_png.read_bytes()
                
                # Fallback 3: Try unoconv if available
                unoconv_path = shutil.which("unoconv")
                if unoconv_path:
                    logger.debug("Attempting unoconv PDF conversion")
                    returncode3, stdout3, stderr3 = _run_subprocess_with_diagnostics(
                        [
                            unoconv_path,
                            "-f",
                            "pdf",
                            "-o",
                            str(pdf_path),
                            str(local_vsdx),
                        ],
                        work_dir=work_dir,
                        operation="unoconv PDF conversion",
                    )
                    
                    if returncode3 != 0:
                        logger.warning(f"unoconv conversion failed with code {returncode3}")
                
                # Check again if PDF was produced by any method
                if not pdf_path.exists() or pdf_path.stat().st_size == 0:
                    # All conversion attempts failed
                    temp_files = _list_temp_dir_contents(work_dir)
                    logger.error(f"All conversion methods failed. Temp dir contents: {temp_files}")
                    
                    diagnostic_msg = (
                        "PDF conversion failed; no output produced by LibreOffice.\n\n"
                        "Diagnostics:\n"
                        f"  - Attempted command 1 (PDF): {soffice} --headless --convert-to pdf\n"
                        f"    Return code: {returncode}, Stderr: {stderr[:200] if stderr else '(empty)'}\n"
                        f"  - Attempted command 2 (PNG): {soffice} --headless --convert-to png\n"
                        f"    Return code: {returncode2}, Stderr: {stderr2[:200] if stderr2 else '(empty)'}\n"
                    )
                    
                    if unoconv_path:
                        diagnostic_msg += f"  - Attempted command 3 (unoconv): {unoconv_path} -f pdf\n"
                        diagnostic_msg += f"    Return code: {returncode3}, Stderr: {stderr3[:200] if stderr3 else '(empty)'}\n"
                    
                    diagnostic_msg += (
                        f"  - Temp directory: {work_dir}\n"
                        f"  - Files in temp dir: {', '.join(temp_files) if temp_files else '(none)'}\n\n"
                        "Troubleshooting steps:\n"
                        f"  1. Verify LibreOffice is installed: {soffice} --headless --version\n"
                        f"  2. Check which/where soffice: which {soffice} (Linux/Mac) or where {soffice} (Windows)\n"
                        f"  3. Inspect temp directory: ls -la {work_dir}\n"
                        f"  4. Try manual conversion: {soffice} --headless --convert-to pdf {local_vsdx}\n"
                    )
                    
                    raise VisioError(diagnostic_msg)
    except VisioError:
        raise
    except subprocess.CalledProcessError as e:
        raise VisioError(f"LibreOffice conversion error (exit {e.returncode})")
    except Exception as e:
        logger.error(f"Unexpected error during conversion: {e}")
        raise VisioError(f"Conversion failed: {e}")

    # Optional: validate page range via pdfinfo
    pages = _get_pdf_pages(pdf_path)
    if pages is not None and page >= pages:
        # LibreOffice has a known limitation: it only converts the first page of multi-page VSDX files
        # Check if the VSDX actually has more pages
        try:
            from vsdx import VisioFile
            with VisioFile(str(src)) as vis:
                total_vsdx_pages = len(vis.pages)
                if page < total_vsdx_pages:
                    # VSDX has the page, but LibreOffice didn't convert it
                    raise VisioError(
                        f"Cannot preview page {page}. LibreOffice only converted page 0 from this {total_vsdx_pages}-page VSDX file. "
                        f"This is a known LibreOffice limitation with multi-page VSDX files. "
                        f"To preview other pages, please open the file in Microsoft Visio or use visio_tools to extract individual pages."
                    )
                else:
                    # Page doesn't exist in VSDX either
                    raise FileError(
                        f"Page {page} out of range (VSDX has {total_vsdx_pages} pages, PDF has {pages})",
                        filepath=str(src),
                    )
        except (ImportError, VisioError):
            raise
        except FileError:
            raise
        except Exception:
            # If we can't check the VSDX, just report the PDF limitation
            raise FileError(
                f"Page {page} out of range (PDF has {pages} pages)",
                filepath=str(src),
            )

    # Render single page -> PNG
    # pdftocairo -png -singlefile -f <1-based> -l <1-based> -r <dpi> <pdf> <outprefix>
    one_based = page + 1
    out_prefix = cache_root / f"{key}"
    
    # Try pdftocairo first
    logger.debug("Attempting PDF to PNG with pdftocairo")
    returncode, stdout, stderr = _run_subprocess_with_diagnostics(
        [
            pdftocairo,
            "-png",
            "-singlefile",
            "-f",
            str(one_based),
            "-l",
            str(one_based),
            "-r",
            str(dpi),
            str(pdf_path),
            str(out_prefix),
        ],
        work_dir=work_dir,
        operation="pdftocairo PNG render",
    )
    
    # pdftocairo creates <prefix>.png when -singlefile is used
    if not cached_png.exists() or cached_png.stat().st_size == 0:
        # Fallback: Try pdftoppm if available
        pdftoppm_path = shutil.which("pdftoppm")
        if pdftoppm_path:
            logger.debug("pdftocairo failed, trying pdftoppm")
            returncode2, stdout2, stderr2 = _run_subprocess_with_diagnostics(
                [
                    pdftoppm_path,
                    "-png",
                    "-f",
                    str(one_based),
                    "-l",
                    str(one_based),
                    "-r",
                    str(dpi),
                    "-singlefile",
                    str(pdf_path),
                    str(out_prefix),
                ],
                work_dir=work_dir,
                operation="pdftoppm PNG render",
            )
            
            if not cached_png.exists() or cached_png.stat().st_size == 0:
                # Fallback: Try ImageMagick convert if available
                convert_path = shutil.which("convert")
                if convert_path:
                    logger.debug("pdftoppm failed, trying ImageMagick convert")
                    # ImageMagick: convert -density <dpi> pdf[page] png
                    returncode3, stdout3, stderr3 = _run_subprocess_with_diagnostics(
                        [
                            convert_path,
                            "-density",
                            str(dpi),
                            f"{pdf_path}[{page}]",
                            str(cached_png),
                        ],
                        work_dir=work_dir,
                        operation="ImageMagick PNG render",
                    )
        
        # Final check
        if not cached_png.exists() or cached_png.stat().st_size == 0:
            temp_files = _list_temp_dir_contents(work_dir)
            logger.error(f"PNG render failed. Temp dir contents: {temp_files}")
            
            diagnostic_msg = (
                "PNG render failed; output file missing or empty.\n\n"
                "Diagnostics:\n"
                f"  - PDF path: {pdf_path} (exists: {pdf_path.exists()}, size: {pdf_path.stat().st_size if pdf_path.exists() else 0})\n"
                f"  - Expected PNG: {cached_png}\n"
                f"  - Attempted command 1 (pdftocairo): Return code: {returncode}\n"
                f"    Stderr: {stderr[:200] if stderr else '(empty)'}\n"
            )
            
            if pdftoppm_path:
                diagnostic_msg += f"  - Attempted command 2 (pdftoppm): Return code: {returncode2}\n"
                diagnostic_msg += f"    Stderr: {stderr2[:200] if stderr2 else '(empty)'}\n"
            
            convert_path = shutil.which("convert")
            if convert_path:
                diagnostic_msg += f"  - Attempted command 3 (ImageMagick): Return code: {returncode3}\n"
                diagnostic_msg += f"    Stderr: {stderr3[:200] if stderr3 else '(empty)'}\n"
            
            diagnostic_msg += (
                f"  - Files in temp dir: {', '.join(temp_files) if temp_files else '(none)'}\n\n"
                "Troubleshooting:\n"
                "  1. Check PDF is valid: pdfinfo {}\n"
                "  2. Verify poppler-utils: pdftocairo --version\n"
                "  3. Try manual render: pdftocairo -png {} output\n"
            ).format(pdf_path, pdf_path)
            
            raise VisioError(diagnostic_msg)
    
    # Verify output is non-empty
    if cached_png.stat().st_size == 0:
        raise VisioError(f"PNG render produced empty file: {cached_png}")
    
    return cached_png.read_bytes()


def png_to_data_uri(png_bytes: bytes) -> str:
    """Return a data URI for PNG bytes."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def render_vsdx_page_to_data_uri(
    vsdx_path: str,
    page: int = 0,
    scale: float = 2.0,
    allowed_extra_path: Optional[str] = None,
) -> str:
    """Render a VSDX page to a PNG data URI (base64)."""
    # Clamp scale for safety
    try:
        s = float(scale)
    except Exception:
        s = 2.0
    s = max(0.5, min(3.0, s))

    png = render_vsdx_page_to_png(
        vsdx_path=vsdx_path,
        page=page,
        scale=s,
        allowed_extra_path=allowed_extra_path,
    )
    # If extremely large, suggest lowering scale
    if len(png) > 6 * 1024 * 1024:
        raise VisioError(
            "Rendered image is too large (>6MB). Try a lower scale such as 1.5 or 1.0."
        )
    return png_to_data_uri(png)


def render_and_save_png(
    vsdx_path: str,
    page: int = 0,
    scale: float = 2.0,
    allowed_extra_path: Optional[str] = None,
    base_url: str = "http://localhost:7777",
) -> dict:
    """
    Render to PNG and save under static/visio/<key>.png, returning URL and file path.
    
    Args:
        base_url: Base URL for the server (default: http://localhost:7777)
                 Use for absolute URLs in markdown rendering
    """
    # Clamp scale
    try:
        s = float(scale)
    except Exception:
        s = 2.0
    s = max(0.5, min(3.0, s))

    # Render bytes
    png_bytes = render_vsdx_page_to_png(
        vsdx_path=vsdx_path,
        page=page,
        scale=s,
        allowed_extra_path=allowed_extra_path,
    )

    # Build deterministic key matching render inputs
    src = Path(vsdx_path).resolve()
    mtime = src.stat().st_mtime
    dpi = int(96 * s) if s >= 0.5 else 96
    key = _sha1(f"{src}|{mtime}|{page}|{dpi}")

    repo_root = _resolve_repo_root()
    static_dir = (repo_root / "outputs" / "static" / "visio").resolve()
    static_dir.mkdir(parents=True, exist_ok=True)

    out_file = static_dir / f"{key}.png"
    if not out_file.exists():
        out_file.write_bytes(png_bytes)

    # Return both relative and absolute URLs
    relative_url = f"/static/visio/{key}.png"
    absolute_url = f"{base_url}{relative_url}"
    return {
        "url": relative_url,
        "absolute_url": absolute_url,
        "file": str(out_file)
    }


