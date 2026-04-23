"""
Apply a watermark manifest to the library.

This step IS destructive. It:
- moves flagged files into a quarantine folder (default:
  ``refine/library_audit/quarantine/``) rather than deleting outright,
  so the operator can still recover a false positive;
- writes a ``removed.json`` manifest next to the audit, which the
  ``regenerate_indexes`` step reads to exclude pruned files.

Usage:
    python -m tools-offline.library_maintenance.prune_library \
        --manifest refine/library_audit/watermarks.json \
        --quarantine refine/library_audit/quarantine \
        --removed-out refine/library_audit/removed.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__ or "")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--quarantine", required=True)
    parser.add_argument("--removed-out", required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without moving any files.",
    )
    args = parser.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"[FAIL] Manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    hits = manifest.get("watermarked_files", [])
    quarantine = Path(args.quarantine).resolve()
    quarantine.mkdir(parents=True, exist_ok=True)

    moved: List[dict] = []
    for hit in hits:
        src = Path(hit["absolute"])
        if not src.exists():
            continue
        dst = quarantine / Path(hit["path"]).name
        # avoid clobbering on name collision
        idx = 1
        while dst.exists():
            dst = quarantine / f"{Path(hit['path']).stem}_{idx}{Path(hit['path']).suffix}"
            idx += 1
        if args.dry_run:
            print(f"[dry-run] would move {src} -> {dst}")
        else:
            shutil.move(str(src), str(dst))
        moved.append({"from": str(src), "to": str(dst), "reason": hit.get("matched_needle")})

    removed_out = Path(args.removed_out).resolve()
    removed_out.parent.mkdir(parents=True, exist_ok=True)
    removed_out.write_text(
        json.dumps({"moved": moved, "count": len(moved), "dry_run": args.dry_run}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[OK] {'Planned' if args.dry_run else 'Moved'} {len(moved)} file(s); removed manifest: {removed_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
