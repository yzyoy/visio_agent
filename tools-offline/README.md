# tools-offline

Offline CLI utilities that are **not** exposed to the LLM.

These scripts operate on the template/stencil libraries and the generated
indexes under `assets/`. They are safe to run manually, but none of them
are wired into the 15-tool agent surface.

## Structure

- `library_maintenance/` — template + stencil pruning, watermark
  detection, index regeneration.

## Invocation

Always run from the repo root so relative paths resolve consistently:

```bash
# Invoke by path; the hyphenated folder name is intentional (not a
# valid Python module identifier, so the LLM cannot import it).
python tools-offline/library_maintenance/detect_watermarks.py \
    --library assets/templates/library \
    --out refine/library_audit/watermarks.json

python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates \
    --stencil-dir assets/templates/stencils \
    --out-dir assets/indexes
```

Each script writes a manifest under `refine/library_audit/` so that the
prune step is reviewable before any file is actually deleted.
