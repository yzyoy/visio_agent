# tools-offline

Offline CLI utilities that are **not** exposed to the LLM. None of them are wired into the agent tool surface.

## Scope

These scripts maintain **both**:

- **Templates** (`.vsdx`) — `--template-dir` populates `template_library*.json` (skipped when `--stencils-only`).
- **Stencils** (`.vssx`) — `--stencil-dir`; alone with `--stencils-only` updates only `stencil_library.json`.

Watermark detection applies to **both** file types by default (`--ext .vsdx,.vssx`). They are not stencil-only tools.

Typical layout under `assets/templates/` (adjust paths if yours differ):

| Path | Role |
|------|------|
| `assets/templates/library/` | `.vsdx` templates |
| `assets/templates/stencils/` | `.vssx` stencil packs |

You can point `detect_watermarks --library` at a single subtree (e.g. only `library/`), only `stencils/`, or a parent folder that contains both — the scanner walks the tree recursively.

Generated indexes land in `--out-dir` (commonly `assets/indexes/`): `template_library.json`, `template_library_lite.json`, and optionally `stencil_library.json`.

## Package layout

- **`library_maintenance/`** — `detect_watermarks`, `prune_library`, `regenerate_indexes`.

Invoke scripts **by path** (examples below) or with **`python -m tools-offline.library_maintenance.<module>`** from the repo root — both resolve the hyphenated folder name as a package when the current directory is on `sys.path`.

## Recommended workflow (watermark audit → prune → indexes)

1. **Detect** — write a manifest; **no files are modified.**
2. **Review** `refine/library_audit/watermarks.json` (or your `--out` path).
3. **Prune** — move flagged files to quarantine; use `--dry-run` first. Writes `removed.json` for bookkeeping.
4. **Regenerate indexes** — run after prune so JSON indexes match files on disk.

More detail (dry-run, recovery): see [`refine/LIBRARY_PRUNING_PROCEDURE.md`](../refine/LIBRARY_PRUNING_PROCEDURE.md).

## Commands

Run from the **repository root** so paths resolve consistently.

**Watermark scan** (default extensions: `.vsdx,.vssx`; override with `--ext`):

```bash
python tools-offline/library_maintenance/detect_watermarks.py \
    --library assets/templates/library \
    --out refine/library_audit/watermarks.json
```

Repeat with `--library assets/templates/stencils` if stencils are not under the same tree you scanned.

**Prune** (destructive moves — quarantine, not delete):

```bash
python tools-offline/library_maintenance/prune_library.py \
    --manifest refine/library_audit/watermarks.json \
    --quarantine refine/library_audit/quarantine \
    --removed-out refine/library_audit/removed.json \
    --dry-run
```

Drop `--dry-run` after review.

**Regenerate indexes** — pick one mode:

- **Templates only (library `.vsdx`)** — writes `template_library.json` and `template_library_lite.json`; omit `--stencil-dir`:

```bash
python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates/library \
    --out-dir assets/indexes
```

- **Templates + stencils** — also writes `stencil_library.json` (template scan runs first, then stencils):

```bash
python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates/library \
    --stencil-dir assets/templates/stencils \
    --out-dir assets/indexes
```

- **Stencils only** — writes `stencil_library.json` only; skips the template scan (`--template-dir` not used):

```bash
python -m tools-offline.library_maintenance.regenerate_indexes \
    --stencils-only \
    --stencil-dir assets/templates/stencils \
    --out-dir assets/indexes
```

Writes `regenerate_report.json` next to the output indexes.
