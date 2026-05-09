"""
Build or extract a Release zip of ``assets/templates`` + ``assets/indexes``.

**Zip layout (relative paths, forward slashes, no leading slash)**

- ``assets/indexes/...`` — JSON indexes
- ``assets/templates/...`` — template library + stencils (see ``build_zip`` exclusions)
- ``assets/**/*.md`` — Markdown next to assets (policy: keep asset-related ``.md`` under ``assets/`` only)

**Markdown**

- Asset- or release-oriented ``.md`` files must stay under ``assets/`` (for example ``assets/README.md``) so they ship in this zip and match the extract validator (entries must be under ``assets/``).

**Where to extract**

- **Correct:** extract **into the repository root** (the directory that contains ``apps/``
  and ``assets/``). After extraction you must have, for example:

  - ``<repo>/assets/templates/library/``
  - ``<repo>/assets/templates/stencils/``
  - ``<repo>/assets/indexes/*.json``

- **Wrong:** unpacking into a new folder (e.g. ``Downloads/visio-assets-release/``)
  yields ``.../visio-assets-release/assets/...`` and the runtime will not see templates
  under the real repo unless you move ``assets/`` up one level.

Excludes unpacked OOXML trees (directories containing ``[Content_Types].xml``):
those are exploded .vsdx/.vssx packages, not normal library layout.

Packaging uses ZIP_STORED (no compression) for maximum speed; binaries are already compressed.

Human-oriented layout notes: ``assets/README.md`` in the repo.
"""

from __future__ import annotations

import argparse
import os
import shutil
import zipfile
from pathlib import Path


def find_ooxml_roots(templates_root: Path) -> frozenset[Path]:
    roots: list[Path] = []
    if not templates_root.is_dir():
        return frozenset()
    for dirpath, _dirnames, filenames in os.walk(templates_root):
        if "[Content_Types].xml" in filenames:
            roots.append(Path(dirpath).resolve())
    return frozenset(roots)


def is_under_excluded(path: Path, excluded: frozenset[Path]) -> bool:
    rp = path.resolve()
    for er in excluded:
        try:
            rp.relative_to(er)
            return True
        except ValueError:
            continue
    return False


def build_zip(
    repo_root: Path,
    out_zip: Path,
    *,
    compression: int = zipfile.ZIP_STORED,
    compresslevel: int | None = None,
) -> None:
    assets = (repo_root / "assets").resolve()
    indexes = assets / "indexes"
    templates = assets / "templates"
    excluded = find_ooxml_roots(templates)
    for er in sorted(excluded, key=lambda p: str(p)):
        rel = er.relative_to(templates.resolve())
        print(f"exclude unpacked OOXML: templates/{rel.as_posix()}")

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    if out_zip.exists():
        out_zip.unlink()

    # Paths inside zip: assets/indexes/..., assets/templates/..., assets/**/*.md
    arc_parent = repo_root.resolve()

    with zipfile.ZipFile(out_zip, "w", allowZip64=True) as zf:
        arcs_written: set[str] = set()

        def add_file(fp: Path, arc: str) -> None:
            if arc in arcs_written:
                return
            arcs_written.add(arc)
            kwargs: dict = {}
            if compression == zipfile.ZIP_DEFLATED and compresslevel is not None:
                kwargs["compresslevel"] = compresslevel
            zf.write(fp, arc, compress_type=compression, **kwargs)

        if indexes.is_dir():
            for fp in indexes.rglob("*"):
                if fp.is_file():
                    arc = fp.relative_to(arc_parent).as_posix()
                    add_file(fp, arc)

        if templates.is_dir():
            for root, dirs, files in os.walk(templates):
                root_path = Path(root)
                dirs[:] = [
                    d
                    for d in dirs
                    if not is_under_excluded(root_path / d, excluded)
                ]
                if is_under_excluded(root_path, excluded):
                    dirs.clear()
                    continue
                for name in files:
                    fp = root_path / name
                    if is_under_excluded(fp, excluded):
                        continue
                    arc = fp.relative_to(arc_parent).as_posix()
                    add_file(fp, arc)

        for fp in sorted(assets.rglob("*.md")):
            if not fp.is_file() or is_under_excluded(fp, excluded):
                continue
            arc = fp.relative_to(arc_parent).as_posix()
            add_file(fp, arc)


def _validate_release_member(name: str, repo_root: Path) -> None:
    """Reject path traversal and require our release layout (under assets/)."""
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        raise ValueError(f"zip entry must be relative, got {name!r}")
    path = Path(normalized)
    if ".." in path.parts:
        raise ValueError(f"zip entry must not contain '..', got {name!r}")
    if not path.parts:
        return
    # Directory-only entries often end with '/'; Path still has meaningful parts
    if path.parts[0] != "assets":
        raise ValueError(
            f"release zip entries must live under 'assets/', got {name!r} "
            "(extract into repo root, not into an extra wrapper folder)"
        )
    dest = (repo_root / path).resolve()
    dest.relative_to(repo_root.resolve())


def extract_release_zip(zip_path: Path, repo_root: Path) -> int:
    """
    Extract a zip built by :func:`build_zip` into ``repo_root``.

    Writes to ``repo_root / 'assets' / ...`` so that existing ``<repo>/assets``
    is merged/replaced as in a normal archive unpack at repo root.

    Returns the number of file members extracted (directory placeholders skipped).
    """
    repo_root = repo_root.resolve()
    repo_root.mkdir(parents=True, exist_ok=True)
    file_count = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            _validate_release_member(info.filename, repo_root)

        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.endswith("/"):
                (repo_root / name.rstrip("/")).mkdir(parents=True, exist_ok=True)
                continue

            target = repo_root / Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            file_count += 1
    return file_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root (parent of assets/)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "dist" / "visio-assets-release.zip",
        help="Output .zip path (when building)",
    )
    parser.add_argument(
        "--extract",
        type=Path,
        metavar="ZIP",
        help="Extract a release zip into --repo-root (validates assets/ layout)",
    )
    parser.add_argument(
        "--deflate-fast",
        action="store_true",
        help="Use fastest deflate instead of ZIP_STORED (slower, slightly smaller)",
    )
    args = parser.parse_args()
    if args.extract:
        n = extract_release_zip(args.extract.resolve(), args.repo_root.resolve())
        print(
            f"Extracted {n} files from {args.extract} -> {args.repo_root.resolve()} "
            f"(expect {args.repo_root.resolve() / 'assets' / 'templates'} etc.)"
        )
        return
    if args.deflate_fast:
        build_zip(
            args.repo_root.resolve(),
            args.out.resolve(),
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=1,
        )
    else:
        build_zip(args.repo_root.resolve(), args.out.resolve(), compression=zipfile.ZIP_STORED)
    size_mb = args.out.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.out} ({size_mb:.2f} MiB)")


if __name__ == "__main__":
    main()
