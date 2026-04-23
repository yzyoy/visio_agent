"""
Scan a Visio template/stencil library for trial-license watermarks.

Diary 11/4 and 11/5 record that Aspose's trial license injects an
``Evaluation Only`` (plus localised Chinese/English variants) text frame
into any file it touches during batch conversion. Those files poison the
recommendation path — a user who picks a "good" template then gets a
watermarked edit target. The fix is to detect them during an offline
audit, write a manifest, and prune separately.

This script NEVER deletes files. It only produces a JSON manifest that
the prune step consumes.

Usage:
    python -m tools-offline.library_maintenance.detect_watermarks \
        --library assets/templates/library \
        --out refine/library_audit/watermarks.json
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional

# Strings that strongly indicate an Aspose trial watermark. We match
# case-insensitively and allow both English and common localised forms.
WATERMARK_NEEDLES = (
    "evaluation only",
    "created with an unlicensed copy",
    "aspose.diagram",
    "aspose.diagram for",
    "evaluation copy",
    "仅供评估",
    "评估版本",
    "未经授权",
)

# Files inside a VSDX/VSSX package whose text content is worth scanning.
# Limiting the scan keeps the audit fast even for a multi-GB library.
SCAN_MEMBER_SUFFIXES = (".xml", ".rels")


def iter_zip_texts(zip_path: Path) -> Iterable[str]:
    """Yield text chunks from every textual member of a VSDX/VSSX zip."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                if not info.filename.lower().endswith(SCAN_MEMBER_SUFFIXES):
                    continue
                try:
                    with zf.open(info) as fp:
                        yield fp.read().decode("utf-8", errors="ignore")
                except Exception:
                    continue
    except zipfile.BadZipFile:
        return


def file_is_watermarked(path: Path) -> Optional[str]:
    """Return the matched needle if ``path`` looks watermarked; else None."""
    for blob in iter_zip_texts(path):
        lower = blob.lower()
        for needle in WATERMARK_NEEDLES:
            if needle in lower:
                return needle
    return None


def scan_library(root: Path, extensions: tuple[str, ...]) -> List[dict]:
    """Walk ``root`` and report any files with a watermark signature."""
    results: List[dict] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue
        needle = file_is_watermarked(path)
        if needle is not None:
            results.append(
                {
                    "path": str(path.relative_to(root)),
                    "absolute": str(path),
                    "size_bytes": path.stat().st_size,
                    "matched_needle": needle,
                }
            )
    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--library", required=True, help="Root dir to scan.")
    parser.add_argument(
        "--ext",
        default=".vsdx,.vssx",
        help="Comma-separated extensions to inspect (default: .vsdx,.vssx).",
    )
    parser.add_argument("--out", required=True, help="Output manifest path.")
    args = parser.parse_args(argv)

    root = Path(args.library).resolve()
    if not root.exists():
        print(f"[FAIL] Library root not found: {root}", file=sys.stderr)
        return 2
    extensions = tuple(e.strip().lower() for e in args.ext.split(",") if e.strip())

    hits = scan_library(root, extensions)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "library_root": str(root),
                "extensions": extensions,
                "needles": WATERMARK_NEEDLES,
                "watermarked_files": hits,
                "count": len(hits),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[OK] Scanned {root} - {len(hits)} watermarked file(s); manifest: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
