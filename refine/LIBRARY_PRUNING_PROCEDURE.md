# Library Pruning Procedure (Batch A Phase 3)

Deliberately non-destructive by default. The templates and stencils
ship with the repo (3+ GB), so pruning is gated on an operator-reviewed
manifest rather than being auto-applied.

## Steps

1. **Detect** — scan the tracked library for trial-license watermarks.

   The folder name ``tools-offline`` matches the roadmap target layout
   (§2.2) but is not a valid Python module identifier; invoke the
   scripts by path rather than with ``-m``.

   ```bash
   python tools-offline/library_maintenance/detect_watermarks.py \
       --library templates/library \
       --out refine/library_audit/watermarks.json
   ```

   Output: a JSON manifest listing every file that contains any of the
   watermark needles (`Evaluation Only`, `aspose.diagram`, etc.). No
   file is touched.

2. **Review** — open `refine/library_audit/watermarks.json`, spot-check
   a handful of flagged files, and confirm the prune list is sane.

3. **Prune** (dry-run first) — quarantine flagged files.

   ```bash
   python tools-offline/library_maintenance/prune_library.py \
       --manifest refine/library_audit/watermarks.json \
       --quarantine refine/library_audit/quarantine \
       --removed-out refine/library_audit/removed.json \
       --dry-run
   ```

   When the plan looks right, drop `--dry-run` to actually move the
   files into quarantine. Recoverable: the move step never deletes.

4. **Regenerate indexes** — after prune.

   ```bash
   python tools-offline/library_maintenance/regenerate_indexes.py \
       --template-dir templates \
       --stencil-dir templates/stencils \
       --out-dir assets/indexes
   ```

   This writes `template_library.json`, `template_library_lite.json`,
   and `stencil_library.json` under `assets/indexes/`. Batch B will move
   the agent to read from this location; Batch A keeps the legacy
   `templates/*_library*.json` path as the runtime source of truth.

## Deferred in Batch A

- Running the destructive prune against the full 3.3 GB library
  (requires operator go-ahead; scripts are ready).
- Moving the runtime read path from `templates/` to `assets/indexes/`
  (that is a Batch B directory-layout change).
- Stencil master-hash deduplication (follow-up script; the roadmap
  leaves this as an optional pass when redundancy is painful).

## Test coverage

See `tests/test_template_recommendation.py`. Today it verifies:

- The lite index parses cleanly if present.
- `SmartMatcher` imports successfully.

When the prune has actually been run, the same file should be extended
to assert that every path referenced by `template_library_lite.json`
still exists on disk, and that every `removed.json` entry is absent from
the index.
