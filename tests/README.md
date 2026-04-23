# Tests

Regression suite for the 15-tool consolidated surface and the
`visio_core` / `visio_mcp` / `apps` split.

## Suites

1. `test_save_reload_roundtrip.py` — open → edit → save → reload; guards
   the connector-visibility fix.
2. `test_idempotent_upsert.py` — repeated `upsert_shape` on the same
   `node_key` must not duplicate.
3. `test_idempotent_connector.py` — repeated `upsert_connector` on the
   same edge must not duplicate and must survive save→reload.
4. `test_grouped_shape_analysis.py` — grouped shapes must be reachable
   via recursive analysis.
5. `test_template_recommendation.py` — `recommend_template` still ranks
   results after library maintenance.

Contract / boundary tests:

- `test_consolidated_tool_surface.py` — the 15-tool consolidated surface
  is exactly what the agno agent sees.
- `test_mcp_contract.py` — `visio_mcp` exports match
  `CONSOLIDATED_TOOL_NAMES` one-for-one.
- `test_mcp_skill_integration.py` — MCP registry + skill manifest stay
  in lock-step with the consolidated names.
- `test_explicit_patch_application.py` — patches only apply through
  `visio_core.apply_patches()`, never as an import-time side effect.
- `test_visio_core_import_boundary.py` — `import visio_core` works
  without `agno` installed.
- `test_skill_manifest.py` — `skills/visio/SKILL.md` structural checks.

## Running

```bash
pip install pytest
pytest tests/
```

Tests requiring a real VSDX fixture auto-skip when no fixture is
present, so the suite is safe on a minimal clone.
