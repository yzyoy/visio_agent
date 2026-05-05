"""
Regenerate the lite + full template/stencil indexes.

Supports both full rebuilds and targeted refreshes for newly added folders.
When a target subdirectory is provided, only entries under that subtree are
rescanned and merged back into the corresponding index files.

Usage:
    # Full rebuild: templates + stencils
    python -m tools-offline.library_maintenance.regenerate_indexes \
        --template-dir assets/templates/library \
        --stencil-dir assets/templates/stencils \
        --out-dir assets/indexes

    # Refresh only a newly added template folder
    python -m tools-offline.library_maintenance.regenerate_indexes \
        --template-dir assets/templates/library \
        --template-subdir "New Folder" \
        --out-dir assets/indexes

    # Refresh only a newly added stencil folder
    python -m tools-offline.library_maintenance.regenerate_indexes \
        --stencils-only \
        --stencil-dir assets/templates/stencils \
        --stencil-subdir "Vendor Packs" \
        --out-dir assets/indexes
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {path}")
    return data


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_sort_mapping(data), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _sort_mapping(data: Dict[str, Any]) -> Dict[str, Any]:
    return {key: data[key] for key in sorted(data)}


def _normalize_rel_key(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    normalized = normalized.strip("/")
    return "" if normalized == "." else normalized


def _strip_visio_suffix(value: str) -> str:
    normalized = value.strip()
    for suffix in (".vsdx", ".vsd", ".vssx", ".vss"):
        if normalized.lower().endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def _matches_any_prefix(rel_key: str, prefixes: Iterable[str]) -> bool:
    normalized_key = _normalize_rel_key(rel_key)
    for prefix in prefixes:
        normalized_prefix = _normalize_rel_key(prefix)
        if not normalized_prefix:
            return True
        if normalized_key == normalized_prefix or normalized_key.startswith(
            f"{normalized_prefix}/"
        ):
            return True
    return False


def _resolve_template_scan_dir(template_dir: Path) -> Path:
    template_dir = template_dir.resolve()
    if template_dir.name.lower() == "library":
        return template_dir
    return (template_dir / "library").resolve()


def _resolve_stencil_scan_dir(stencil_dir: Path) -> Path:
    stencil_dir = stencil_dir.resolve()
    if stencil_dir.name.lower() == "stencils":
        return stencil_dir
    return (stencil_dir / "stencils").resolve()


def _resolve_target_subdirs(
    base_dir: Path, raw_subdirs: List[str], label: str
) -> List[str]:
    resolved: List[str] = []
    seen = set()
    base_dir = base_dir.resolve()

    for raw_subdir in raw_subdirs:
        candidate = Path(raw_subdir)
        abs_dir = candidate.resolve() if candidate.is_absolute() else (base_dir / candidate).resolve()
        try:
            rel_path = abs_dir.relative_to(base_dir)
        except ValueError as exc:
            raise ValueError(f"{label} '{raw_subdir}' is outside '{base_dir}'") from exc
        if not abs_dir.exists():
            raise ValueError(f"{label} '{raw_subdir}' does not exist: {abs_dir}")
        if not abs_dir.is_dir():
            raise ValueError(f"{label} '{raw_subdir}' is not a directory: {abs_dir}")

        normalized = _normalize_rel_key(rel_path.as_posix())
        if normalized not in seen:
            seen.add(normalized)
            resolved.append(normalized)

    return resolved


def _scan_template_scope(template_dir: Path, target_subdirs: List[str]) -> Dict[str, Dict[str, Any]]:
    from visio_core.utils.template_scanner import TemplateScanner

    results: Dict[str, Dict[str, Any]] = {}
    scan_roots = target_subdirs or [""]

    for subdir in scan_roots:
        scan_root = template_dir if not subdir else template_dir / subdir
        scanned = TemplateScanner.scan_directory(str(scan_root))
        prefix = f"{subdir}/" if subdir else ""
        for rel_path, scan_data in scanned.items():
            results[_normalize_rel_key(f"{prefix}{rel_path}")] = scan_data

    return results


def _scan_stencil_scope(stencil_dir: Path, target_subdirs: List[str]) -> Dict[str, Dict[str, Any]]:
    from visio_core.utils.stencil_scanner import StencilScanner

    results: Dict[str, Dict[str, Any]] = {}
    scan_roots = target_subdirs or [""]

    for subdir in scan_roots:
        scan_root = stencil_dir if not subdir else stencil_dir / subdir
        scanned = StencilScanner.scan_directory(str(scan_root))
        prefix = f"{subdir}/" if subdir else ""
        for rel_path, scan_data in scanned.items():
            results[_normalize_rel_key(f"{prefix}{rel_path}")] = scan_data

    return results


def _build_template_full_entry(
    rel_path: str, scan_data: Dict[str, Any], existing: Dict[str, Any]
) -> Dict[str, Any]:
    from visio_core.templates.template_manager import TemplateManager
    from visio_core.utils.metadata_generator import MetadataGenerator

    category = existing.get("category", "general")
    metadata = MetadataGenerator.generate_template_metadata(scan_data, category)
    shape_counts = scan_data.get("total_shapes", {}) or {}

    return {
        "name": existing.get("name", _strip_visio_suffix(rel_path)),
        "category": category,
        "keywords": metadata["keywords"],
        "use_cases": metadata["use_cases"],
        "shapes": shape_counts,
        "shape_total": sum(shape_counts.values()) if isinstance(shape_counts, dict) else 0,
        "shape_types": sorted(shape_counts.keys()) if isinstance(shape_counts, dict) else [],
        "total_connectors": scan_data.get("total_connectors", 0),
        "complexity": scan_data.get("complexity", "unknown"),
        "scan_date": scan_data.get("scan_date", ""),
        "pages": scan_data.get("total_pages", 1),
        "sample_texts": scan_data.get("sample_texts", [])[:10],
        "pages_detail": TemplateManager._simplify_pages_detail(
            scan_data.get("pages_detail", [])
        ),
        "connection_graph": TemplateManager._simplify_connection_graph(
            scan_data.get("connection_graph", {})
        ),
        "topology_pattern": scan_data.get("topology_pattern", {}),
        "layout_pattern": scan_data.get("layout_pattern", {}),
    }


def _build_template_lite_entry(full_entry: Dict[str, Any]) -> Dict[str, Any]:
    lite_keys = (
        "name",
        "category",
        "keywords",
        "use_cases",
        "shapes",
        "shape_total",
        "shape_types",
        "total_connectors",
        "complexity",
        "scan_date",
        "pages",
        "topology_pattern",
        "layout_pattern",
    )
    return {key: full_entry.get(key) for key in lite_keys}


def _build_stencil_full_entry(
    rel_path: str, scan_data: Dict[str, Any], existing: Dict[str, Any]
) -> Dict[str, Any]:
    from visio_core.utils.metadata_generator import MetadataGenerator

    category = existing.get("category", "general")
    metadata = MetadataGenerator.generate_stencil_metadata(scan_data, category)

    return {
        "name": existing.get("name", _strip_visio_suffix(rel_path)),
        "category": category,
        "keywords": metadata["keywords"],
        "use_cases": metadata["use_cases"],
        "masters": scan_data.get("masters", {}),
        "master_count": scan_data.get("master_count", 0),
        "master_names": scan_data.get("master_names", []),
        "complexity": scan_data.get("complexity", "unknown"),
        "scan_date": scan_data.get("scan_date", ""),
    }


def _build_stencil_lite_entry(full_entry: Dict[str, Any]) -> Dict[str, Any]:
    lite_keys = (
        "name",
        "category",
        "keywords",
        "use_cases",
        "master_count",
        "master_names",
        "complexity",
        "scan_date",
    )
    return {key: full_entry.get(key) for key in lite_keys}


def _merge_scanned_entries(
    existing_full: Dict[str, Any],
    existing_lite: Dict[str, Any],
    scanned: Dict[str, Dict[str, Any]],
    target_subdirs: List[str],
    build_full_entry,
    build_lite_entry,
) -> Dict[str, Any]:
    lookup_full = dict(existing_full)
    full_mode = "partial" if target_subdirs else "full"
    cleared_existing_count = (
        sum(1 for key in existing_full if _matches_any_prefix(key, target_subdirs))
        if target_subdirs
        else len(existing_full)
    )
    next_full = (
        {k: v for k, v in existing_full.items() if not _matches_any_prefix(k, target_subdirs)}
        if target_subdirs
        else {}
    )
    next_lite = (
        {k: v for k, v in existing_lite.items() if not _matches_any_prefix(k, target_subdirs)}
        if target_subdirs
        else {}
    )

    failures: Dict[str, str] = {}
    updated = 0

    for rel_path, scan_data in scanned.items():
        if scan_data.get("error"):
            failures[rel_path] = str(scan_data["error"])
            continue

        full_entry = build_full_entry(rel_path, scan_data, lookup_full.get(rel_path, {}))
        next_full[rel_path] = full_entry
        next_lite[rel_path] = build_lite_entry(full_entry)
        updated += 1

    return {
        "mode": full_mode,
        "full": _sort_mapping(next_full),
        "lite": _sort_mapping(next_lite),
        "updated_count": updated,
        "failed_count": len(failures),
        "cleared_existing_count": cleared_existing_count,
        "target_subdirs": target_subdirs,
        "failures": failures,
    }


def _regenerate_template_indexes(
    template_dir: Path, out_dir: Path, target_subdirs: List[str]
) -> dict:
    template_dir = _resolve_template_scan_dir(template_dir)
    full_path = out_dir / "template_library.json"
    lite_path = out_dir / "template_library_lite.json"

    try:
        existing_full = _load_json(full_path)
        existing_lite = _load_json(lite_path)
        scanned = _scan_template_scope(template_dir, target_subdirs)
        merged = _merge_scanned_entries(
            existing_full=existing_full,
            existing_lite=existing_lite,
            scanned=scanned,
            target_subdirs=target_subdirs,
            build_full_entry=_build_template_full_entry,
            build_lite_entry=_build_template_lite_entry,
        )
        _write_json(full_path, merged["full"])
        _write_json(lite_path, merged["lite"])
    except Exception as e:
        return {"ok": False, "error": f"template index regeneration failed: {e}"}

    return {
        "ok": merged["failed_count"] == 0,
        "mode": merged["mode"],
        "scan_dir": str(template_dir),
        "target_subdirs": merged["target_subdirs"],
        "scanned_count": len(scanned),
        "updated_count": merged["updated_count"],
        "failed_count": merged["failed_count"],
        "cleared_existing_count": merged["cleared_existing_count"],
        "full_count": len(merged["full"]),
        "lite_count": len(merged["lite"]),
        "failures": merged["failures"],
        "written_files": [str(full_path), str(lite_path)],
    }


def _regenerate_stencil_indexes(
    stencil_dir: Path, out_dir: Path, target_subdirs: List[str]
) -> dict:
    stencil_dir = _resolve_stencil_scan_dir(stencil_dir)
    full_path = out_dir / "stencil_library.json"
    lite_path = out_dir / "stencil_library_lite.json"

    try:
        existing_full = _load_json(full_path)
        existing_lite = _load_json(lite_path)
        scanned = _scan_stencil_scope(stencil_dir, target_subdirs)
        merged = _merge_scanned_entries(
            existing_full=existing_full,
            existing_lite=existing_lite,
            scanned=scanned,
            target_subdirs=target_subdirs,
            build_full_entry=_build_stencil_full_entry,
            build_lite_entry=_build_stencil_lite_entry,
        )
        _write_json(full_path, merged["full"])
        _write_json(lite_path, merged["lite"])
    except Exception as e:
        return {"ok": False, "error": f"stencil index regeneration failed: {e}"}

    return {
        "ok": merged["failed_count"] == 0,
        "mode": merged["mode"],
        "scan_dir": str(stencil_dir),
        "target_subdirs": merged["target_subdirs"],
        "scanned_count": len(scanned),
        "updated_count": merged["updated_count"],
        "failed_count": merged["failed_count"],
        "cleared_existing_count": merged["cleared_existing_count"],
        "full_count": len(merged["full"]),
        "lite_count": len(merged["lite"]),
        "failures": merged["failures"],
        "written_files": [str(full_path), str(lite_path)],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__ or "",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--template-dir",
        default="",
        help="Root directory of .vsdx/.vsd templates (required unless --stencils-only).",
    )
    parser.add_argument("--stencil-dir", default="", help="Root directory of .vssx/.vss stencil packs.")
    parser.add_argument(
        "--template-subdir",
        action="append",
        default=[],
        help=(
            "Refresh only this template subdirectory (relative to --template-dir or absolute path). "
            "Repeat to refresh multiple folders."
        ),
    )
    parser.add_argument(
        "--stencil-subdir",
        action="append",
        default=[],
        help=(
            "Refresh only this stencil subdirectory (relative to --stencil-dir or absolute path). "
            "Repeat to refresh multiple folders."
        ),
    )
    parser.add_argument(
        "--stencils-only",
        action="store_true",
        help="Only regenerate stencil indexes; skip template scan.",
    )
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    template_subdirs: List[str] = []
    stencil_subdirs: List[str] = []

    try:
        if args.template_subdir:
            if not args.template_dir:
                parser.error("--template-subdir requires --template-dir")
            template_subdirs = _resolve_target_subdirs(
                _resolve_template_scan_dir(Path(args.template_dir)),
                args.template_subdir,
                "--template-subdir",
            )

        if args.stencil_subdir:
            if not args.stencil_dir:
                parser.error("--stencil-subdir requires --stencil-dir")
            stencil_subdirs = _resolve_target_subdirs(
                _resolve_stencil_scan_dir(Path(args.stencil_dir)),
                args.stencil_subdir,
                "--stencil-subdir",
            )
    except ValueError as exc:
        parser.error(str(exc))

    if args.stencils_only:
        if not args.stencil_dir:
            parser.error("--stencils-only requires --stencil-dir")
        report = {
            "stencils": _regenerate_stencil_indexes(
                Path(args.stencil_dir).resolve(), out_dir, stencil_subdirs
            )
        }
    else:
        if not args.template_dir:
            parser.error("either --template-dir or --stencils-only --stencil-dir is required")
        template_dir = Path(args.template_dir).resolve()
        report = {
            "templates": _regenerate_template_indexes(template_dir, out_dir, template_subdirs)
        }
        if args.stencil_dir:
            report["stencils"] = _regenerate_stencil_indexes(
                Path(args.stencil_dir).resolve(), out_dir, stencil_subdirs
            )

    report_path = out_dir / "regenerate_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    any_fail = any(not v.get("ok") for v in report.values())
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"{'[FAIL]' if any_fail else '[OK]'} Index regeneration report: {report_path}")
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
