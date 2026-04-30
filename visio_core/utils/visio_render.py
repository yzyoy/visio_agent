"""
Utilities to render Visio (.vsdx) files to PNG for frontend preview.

Layered rendering pipeline (first backend that succeeds wins):

1. Microsoft Visio (COM)            - Windows + Visio installed: best fidelity, no watermark
2. Aspose.Diagram                   - Cross-platform: high fidelity (trial adds watermark)
3. LibreOffice (soffice) + Poppler  - Fallback: limited VSDX support; may produce blank pages

Caching strategy:
- Cache under system temp directory (e.g., %TEMP%/visio_renders on Windows, /tmp/visio_renders on Unix)
- Cache key: sha1(path + mtime + page + dpi + backend)
- Reuse cached PNG if source .vsdx hasn't changed.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from .exceptions import FileError, VisioError

logger = logging.getLogger(__name__)


ALLOWED_ROOTS = [
    # Filled at runtime using repo root if available; fallback to relative dirs
    "assets",
    "outputs",
    "tests",
]

# Order in which backends are attempted. Override via VISIO_RENDER_BACKENDS env var
# (comma-separated list). Names: visio_com, aspose, libreoffice.
_DEFAULT_BACKEND_ORDER = ("visio_com", "aspose", "libreoffice")

# Common Windows install locations for soffice.exe (not always in PATH).
_WINDOWS_SOFFICE_HINTS = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
)


# ---------------------------------------------------------------------------
# Path / cache helpers
# ---------------------------------------------------------------------------


def _resolve_repo_root() -> Path:
    try:
        # This file: <repo>/visio_core/utils/visio_render.py
        return Path(__file__).resolve().parents[2]
    except Exception:
        return Path.cwd()


def _allowed_roots_abs() -> List[Path]:
    root = _resolve_repo_root()
    return [(root / rel).resolve() for rel in ALLOWED_ROOTS]


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
            try:
                p.relative_to(base)
                return True
            except ValueError:
                continue
        # Also allow files inside the system temp dir (e.g. temp_analysis_*.vsdx)
        try:
            p.relative_to(Path(tempfile.gettempdir()).resolve())
            return True
        except ValueError:
            pass
        return False
    except Exception:
        return False


def _sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _cache_root() -> Path:
    root = Path(tempfile.gettempdir()) / "visio_renders"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _scale_to_dpi(scale: float) -> int:
    try:
        return max(72, int(96 * float(scale or 1.0)))
    except Exception:
        return 192


def _list_temp_dir_contents(dir_path: Path) -> List[str]:
    try:
        return [f.name for f in dir_path.iterdir() if f.is_file()]
    except Exception as exc:
        return [f"<error listing dir: {exc}>"]


# ---------------------------------------------------------------------------
# Backend: Microsoft Visio (COM, Windows only)
# ---------------------------------------------------------------------------


def _visio_com_available() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        import win32com.client  # noqa: F401  (import side-effect check only)
    except Exception:
        return False
    # Probing CLSID is too heavy for a hot path; trust the import and let the
    # actual Dispatch fail downstream if Visio isn't installed.
    return True


def _render_with_visio_com(src: Path, page: int, dpi: int, out_png: Path) -> None:
    """Render via Microsoft Visio COM automation."""
    import pythoncom  # type: ignore
    import win32com.client  # type: ignore

    # COM must be initialized on the calling thread (Visio's automation server
    # is STA). uvicorn's reload thread does not initialize it for us.
    pythoncom.CoInitialize()
    app = None
    doc = None
    try:
        try:
            app = win32com.client.DispatchEx("Visio.InvisibleApp")
        except Exception:
            # Some installs only expose Visio.Application
            app = win32com.client.DispatchEx("Visio.Application")
            try:
                app.Visible = False
            except Exception:
                pass

        # Suppress all dialogs / alerts during automation.
        try:
            app.AlertResponse = 7  # vbCancel
        except Exception:
            pass
        try:
            app.DeferRecalc = 1
        except Exception:
            pass

        # Configure raster export resolution to the requested DPI.
        try:
            settings = app.Settings
            # 1 = visRasterPixel; 2 = visRasterUseDocResolution.
            # We instead supply explicit DPI via RasterExportResolution* values.
            settings.RasterExportResolution = 0  # custom
            settings.RasterExportResolutionX = dpi
            settings.RasterExportResolutionY = dpi
            # 0 = pixels per inch
            settings.RasterExportResolutionUnit = 0
        except Exception as exc:  # nosec - non-fatal: fall back to default DPI
            logger.debug("Visio raster settings adjustment failed: %s", exc)

        # 0x10 = visOpenRO, 0x40 = visOpenMinimized, 0x80 = visOpenDocked
        flags = 0x10 | 0x40 | 0x80
        doc = app.Documents.OpenEx(str(src), flags)

        page_count = doc.Pages.Count
        if page < 0 or page >= page_count:
            raise FileError(
                f"Page {page} out of range (document has {page_count} page(s))",
                filepath=str(src),
            )

        # Visio Pages collection is 1-based.
        target_page = doc.Pages.Item(page + 1)

        out_png.parent.mkdir(parents=True, exist_ok=True)
        if out_png.exists():
            try:
                out_png.unlink()
            except Exception:
                pass
        target_page.Export(str(out_png))

        if not out_png.exists() or out_png.stat().st_size == 0:
            raise VisioError(
                "Microsoft Visio Export() produced no output. "
                "The document may be corrupted or restricted by IRM."
            )
    except FileError:
        raise
    except VisioError:
        raise
    except Exception as exc:
        raise VisioError(f"Microsoft Visio COM render failed: {exc}") from exc
    finally:
        try:
            if doc is not None:
                doc.Close()
        except Exception:
            pass
        try:
            if app is not None:
                app.Quit()
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Backend: Aspose.Diagram
# ---------------------------------------------------------------------------


def _aspose_available() -> bool:
    try:
        import aspose.diagram  # noqa: F401
        return True
    except Exception:
        return False


def _try_apply_aspose_license() -> None:
    """Best-effort license activation. Looks for ASPOSE_LICENSE_PATH env or
    common files at the repo root. Silent on failure (trial mode kicks in)."""
    candidates: List[Path] = []
    env_path = os.getenv("ASPOSE_LICENSE_PATH")
    if env_path:
        candidates.append(Path(env_path))
    repo_root = _resolve_repo_root()
    for name in ("Aspose.Diagram.lic", "Aspose.Total.lic"):
        candidates.append(repo_root / name)
        candidates.append(repo_root / "scripts" / name)

    for cand in candidates:
        try:
            if not cand.is_file():
                continue
            from aspose.diagram import License  # type: ignore
            License().set_license(str(cand))
            logger.info("Aspose.Diagram license applied from %s", cand)
            return
        except Exception as exc:
            logger.debug("Aspose license attempt failed (%s): %s", cand, exc)


_aspose_license_applied = False


def _render_with_aspose(src: Path, page: int, dpi: int, out_png: Path) -> None:
    global _aspose_license_applied
    try:
        from aspose.diagram import Diagram, SaveFileFormat
        from aspose.diagram.saving import ImageSaveOptions
    except Exception as exc:
        raise VisioError(f"Aspose.Diagram not available: {exc}") from exc

    if not _aspose_license_applied:
        _try_apply_aspose_license()
        _aspose_license_applied = True

    try:
        diagram = Diagram(str(src))
        page_count = diagram.pages.count
        if page < 0 or page >= page_count:
            raise FileError(
                f"Page {page} out of range (document has {page_count} page(s))",
                filepath=str(src),
            )
        opts = ImageSaveOptions(SaveFileFormat.PNG)
        opts.page_index = page
        try:
            opts.resolution = float(dpi)
        except Exception:
            pass
        out_png.parent.mkdir(parents=True, exist_ok=True)
        diagram.save(str(out_png), opts)
        if not out_png.exists() or out_png.stat().st_size == 0:
            raise VisioError("Aspose.Diagram produced no output PNG")
    except FileError:
        raise
    except VisioError:
        raise
    except Exception as exc:
        raise VisioError(f"Aspose.Diagram render failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Backend: LibreOffice + Poppler (existing best-effort approach)
# ---------------------------------------------------------------------------


def _which_or_hint(name: str, hints: Tuple[str, ...] = ()) -> Optional[str]:
    found = shutil.which(name)
    if found:
        return found
    if platform.system() == "Windows" and name == "soffice":
        for hint in hints or _WINDOWS_SOFFICE_HINTS:
            if Path(hint).is_file():
                return hint
    return None


def _libreoffice_available() -> bool:
    return _which_or_hint("soffice") is not None and (
        shutil.which("pdftocairo") is not None or shutil.which("pdftoppm") is not None
    )


def _run_subprocess_with_diagnostics(
    cmd: List[str], work_dir: Path, operation: str, timeout: int = 60
) -> Tuple[int, str, str]:
    logger.debug("%s: running %s", operation, " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return (
            result.returncode,
            (result.stdout or "").strip(),
            (result.stderr or "").strip(),
        )
    except subprocess.TimeoutExpired:
        raise VisioError(
            f"{operation} timed out after {timeout}s. Command: {' '.join(cmd)}"
        )
    except Exception as exc:
        raise VisioError(f"{operation} subprocess error: {exc}") from exc


def _get_pdf_pages(pdf_path: Path) -> Optional[int]:
    info = shutil.which("pdfinfo")
    if not info:
        return None
    try:
        out = subprocess.check_output(
            [info, str(pdf_path)], stderr=subprocess.STDOUT, text=True
        )
        for line in out.splitlines():
            if line.strip().lower().startswith("pages:"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    return int(parts[1].strip())
    except Exception:
        return None
    return None


def _render_with_libreoffice(src: Path, page: int, dpi: int, out_png: Path) -> None:
    soffice = _which_or_hint("soffice")
    if not soffice:
        raise VisioError(
            "LibreOffice 'soffice' not found. Install LibreOffice and ensure it is on PATH."
        )
    pdftocairo = shutil.which("pdftocairo")
    pdftoppm = shutil.which("pdftoppm")
    if not pdftocairo and not pdftoppm:
        raise VisioError(
            "Neither 'pdftocairo' nor 'pdftoppm' found. Install poppler-utils."
        )

    work_dir = out_png.parent / f"work_{out_png.stem}"
    work_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = work_dir / f"{src.stem}.pdf"

    if not pdf_path.exists() or pdf_path.stat().st_mtime < src.stat().st_mtime:
        # Copy source into work dir to avoid clutter / locks in the original tree.
        local_vsdx = work_dir / src.name
        if not local_vsdx.exists() or local_vsdx.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(str(src), str(local_vsdx))
        rc, _, stderr = _run_subprocess_with_diagnostics(
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
        if rc != 0 or not pdf_path.exists() or pdf_path.stat().st_size == 0:
            raise VisioError(
                f"LibreOffice failed to convert VSDX -> PDF (exit {rc}). "
                f"Stderr: {stderr[:200] if stderr else '(empty)'}"
            )

    pages = _get_pdf_pages(pdf_path)
    if pages is not None and page >= pages:
        raise FileError(
            f"Page {page} out of range (PDF has {pages} pages). "
            "LibreOffice often only converts the first page of multi-page VSDX files.",
            filepath=str(src),
        )

    one_based = page + 1
    out_prefix = out_png.with_suffix("")
    if pdftocairo:
        rc, _, stderr = _run_subprocess_with_diagnostics(
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
        if rc == 0 and out_png.exists() and out_png.stat().st_size > 0:
            return

    if pdftoppm:
        rc, _, stderr = _run_subprocess_with_diagnostics(
            [
                pdftoppm,
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
        if rc == 0 and out_png.exists() and out_png.stat().st_size > 0:
            return

    raise VisioError(
        "Both pdftocairo and pdftoppm failed to produce PNG output. "
        f"Last stderr: {stderr[:200] if stderr else '(empty)'}"
    )


# ---------------------------------------------------------------------------
# Backend orchestration
# ---------------------------------------------------------------------------


def _backend_order() -> List[str]:
    raw = os.getenv("VISIO_RENDER_BACKENDS")
    if not raw:
        return list(_DEFAULT_BACKEND_ORDER)
    order = [b.strip().lower() for b in raw.split(",") if b.strip()]
    return order or list(_DEFAULT_BACKEND_ORDER)


def _is_blank_png(png_path: Path) -> bool:
    """Heuristic: if a PNG has fewer than 3 unique colors AND the dominant
    color covers >99.5% of pixels, treat it as a blank/empty render. Used to
    detect LibreOffice's silent failure mode."""
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return False
    try:
        with Image.open(png_path) as im:
            small = im.convert("RGB").resize((64, 64))
            colors = small.getcolors(maxcolors=64 * 64) or []
            if len(colors) <= 2:
                total = sum(count for count, _ in colors) or 1
                top = max(count for count, _ in colors)
                if top / total > 0.995:
                    return True
        return False
    except Exception:
        return False


def render_vsdx_page_to_png(
    vsdx_path: str,
    page: int = 0,
    scale: float = 2.0,
    allowed_extra_path: Optional[str] = None,
) -> bytes:
    """Render a .vsdx page to PNG bytes using the first available backend.

    Args:
        vsdx_path: Path to the .vsdx file (must be under an allowed directory
            or explicitly whitelisted via ``allowed_extra_path``).
        page: 0-based page index.
        scale: Render scale multiplier; ``1.0`` ≈ 96 DPI, so DPI = ``int(96 * scale)``.
        allowed_extra_path: Additional path to whitelist beyond default roots.
    """

    if page < 0:
        raise FileError("Page index must be >= 0", filepath=vsdx_path)
    dpi = _scale_to_dpi(scale)

    src = Path(vsdx_path)
    if not src.exists():
        raise FileError("Visio file not found", filepath=vsdx_path)
    src = src.resolve()

    extra = Path(allowed_extra_path).resolve() if allowed_extra_path else None
    if not _is_allowed_path(src, allowed_extra=extra):
        roots = " | ".join(str(p) for p in _allowed_roots_abs())
        raise FileError(
            f"Access denied. Path must be under allowed roots: {roots}",
            filepath=str(src),
        )

    cache = _cache_root()
    mtime = int(src.stat().st_mtime)

    backends_attempted: List[str] = []
    failures: List[str] = []
    last_blank_path: Optional[Path] = None

    for backend in _backend_order():
        cache_key = _sha1(f"{src}|{mtime}|{page}|{dpi}|{backend}")
        cached = cache / f"{cache_key}.png"

        if cached.exists() and cached.stat().st_size > 0 and not _is_blank_png(cached):
            logger.debug("render_vsdx_page_to_png: cache hit (%s)", backend)
            return cached.read_bytes()

        try:
            if backend == "visio_com":
                if not _visio_com_available():
                    failures.append(f"{backend}: not available on this platform")
                    continue
                backends_attempted.append(backend)
                _render_with_visio_com(src, page, dpi, cached)
            elif backend == "aspose":
                if not _aspose_available():
                    failures.append(f"{backend}: aspose.diagram not installed")
                    continue
                backends_attempted.append(backend)
                _render_with_aspose(src, page, dpi, cached)
            elif backend == "libreoffice":
                if not _libreoffice_available():
                    failures.append(
                        f"{backend}: soffice and/or poppler-utils not on PATH"
                    )
                    continue
                backends_attempted.append(backend)
                _render_with_libreoffice(src, page, dpi, cached)
            else:
                failures.append(f"{backend}: unknown backend")
                continue
        except FileError:
            raise
        except VisioError as exc:
            failures.append(f"{backend}: {exc}")
            logger.warning("Render backend '%s' failed: %s", backend, exc)
            continue
        except Exception as exc:  # pragma: no cover - defensive
            failures.append(f"{backend}: unexpected {type(exc).__name__}: {exc}")
            logger.exception("Render backend '%s' raised", backend)
            continue

        if not cached.exists() or cached.stat().st_size == 0:
            failures.append(f"{backend}: produced no output file")
            continue

        if _is_blank_png(cached):
            failures.append(
                f"{backend}: output is a blank page (likely silent conversion failure)"
            )
            last_blank_path = cached
            continue

        logger.info("Rendered %s page %d via %s (%d DPI)", src.name, page, backend, dpi)
        return cached.read_bytes()

    # If every non-blank backend failed but we have a blank-but-valid PNG, return it
    # rather than erroring out, with a clear log warning.
    if last_blank_path is not None and last_blank_path.exists():
        logger.warning(
            "All non-blank backends failed; returning blank fallback render. "
            "Failures: %s",
            "; ".join(failures),
        )
        return last_blank_path.read_bytes()

    diag = "\n".join(f"  - {f}" for f in failures) or "  - (no backends ran)"
    raise VisioError(
        "Could not render VSDX to PNG. Backend failures:\n"
        f"{diag}\n\n"
        "Suggestions:\n"
        "  • On Windows: install Microsoft Visio (best fidelity) or `pip install aspose-diagram-python`.\n"
        "  • On Linux/macOS: install `libreoffice` and `poppler-utils`, or `pip install aspose-diagram-python`.\n"
        f"  • Override backend order with VISIO_RENDER_BACKENDS=visio_com,aspose,libreoffice\n"
        f"  • Tried backends (in order): {', '.join(backends_attempted) or '(none)'}"
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def png_to_data_uri(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def render_vsdx_page_to_data_uri(
    vsdx_path: str,
    page: int = 0,
    scale: float = 2.0,
    allowed_extra_path: Optional[str] = None,
) -> str:
    """Render a VSDX page to a PNG data URI (base64)."""
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
    """Render to PNG and persist under ``outputs/static/visio/<key>.png``.

    Returns a dict with keys ``url`` (relative), ``absolute_url`` and ``file``.
    """
    try:
        s = float(scale)
    except Exception:
        s = 2.0
    s = max(0.5, min(3.0, s))

    png_bytes = render_vsdx_page_to_png(
        vsdx_path=vsdx_path,
        page=page,
        scale=s,
        allowed_extra_path=allowed_extra_path,
    )

    src = Path(vsdx_path).resolve()
    mtime = int(src.stat().st_mtime)
    dpi = _scale_to_dpi(s)
    key = _sha1(f"{src}|{mtime}|{page}|{dpi}|saved")

    repo_root = _resolve_repo_root()
    static_dir = (repo_root / "outputs" / "static" / "visio").resolve()
    static_dir.mkdir(parents=True, exist_ok=True)

    out_file = static_dir / f"{key}.png"
    if not out_file.exists() or out_file.stat().st_size != len(png_bytes):
        out_file.write_bytes(png_bytes)

    relative_url = f"/static/visio/{key}.png"
    absolute_url = f"{base_url}{relative_url}"
    return {
        "url": relative_url,
        "absolute_url": absolute_url,
        "file": str(out_file),
    }
