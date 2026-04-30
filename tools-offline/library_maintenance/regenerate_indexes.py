"""
Regenerate the lite + full template/stencil indexes.

Thin wrapper over the existing scanners in ``visio_core/utils/`` so the
index-rebuild step is scriptable and idempotent. Meant to be run after
``prune_library``.

Usage:
    python -m tools-offline.library_maintenance.regenerate_indexes \
        --template-dir assets/templates/library \
        --stencil-dir assets/templates/stencils \
        --out-dir assets/indexes

    # Stencils only (skip template scan):
    python -m tools-offline.library_maintenance.regenerate_indexes \
        --stencils-only --stencil-dir assets/templates/stencils \
        --out-dir assets/indexes
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional


def _regenerate_template_indexes(template_dir: Path, out_dir: Path) -> dict:
    try:
        from visio_core.utils.template_scanner import (  # type: ignore
            scan_templates,  # expected entry point
        )
    except Exception as e:
        return {"ok": False, "error": f"template_scanner unavailable: {e}"}

    try:
        full, lite = scan_templates(str(template_dir))  # type: ignore[assignment]
    except Exception as e:
        return {"ok": False, "error": f"scan_templates failed: {e}"}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "template_library.json").write_text(
        json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out_dir / "template_library_lite.json").write_text(
        json.dumps(lite, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {
        "ok": True,
        "full_count": len(full) if hasattr(full, "__len__") else None,
        "lite_count": len(lite) if hasattr(lite, "__len__") else None,
    }


def _regenerate_stencil_indexes(stencil_dir: Path, out_dir: Path) -> dict:
    try:
        from visio_core.utils.stencil_scanner import scan_stencils  # type: ignore
    except Exception as e:
        return {"ok": False, "error": f"stencil_scanner unavailable: {e}"}

    try:
        data = scan_stencils(str(stencil_dir))  # type: ignore[assignment]
    except Exception as e:
        return {"ok": False, "error": f"scan_stencils failed: {e}"}

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "stencil_library.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return {"ok": True, "count": len(data) if hasattr(data, "__len__") else None}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument(
        "--template-dir",
        default="",
        help="Root directory of .vsdx templates (required unless --stencils-only).",
    )
    parser.add_argument("--stencil-dir", default="", help="Root directory of .vssx stencil packs.")
    parser.add_argument(
        "--stencils-only",
        action="store_true",
        help="Only regenerate stencil_library.json; skip template scan.",
    )
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).resolve()

    if args.stencils_only:
        if not args.stencil_dir:
            parser.error("--stencils-only requires --stencil-dir")
        report = {
            "stencils": _regenerate_stencil_indexes(Path(args.stencil_dir).resolve(), out_dir)
        }
    else:
        if not args.template_dir:
            parser.error("either --template-dir or --stencils-only --stencil-dir is required")
        template_dir = Path(args.template_dir).resolve()
        report = {"templates": _regenerate_template_indexes(template_dir, out_dir)}
        if args.stencil_dir:
            report["stencils"] = _regenerate_stencil_indexes(
                Path(args.stencil_dir).resolve(), out_dir
            )

    report_path = out_dir / "regenerate_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    any_fail = any(not v.get("ok") for v in report.values())
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"{'[FAIL]' if any_fail else '[OK]'} Index regeneration report: {report_path}")
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
