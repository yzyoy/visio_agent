# MCP Contract (Batch B Phase 4)

Single source of truth for the capability boundary between the agno
runtime shell and any MCP-shaped client (Cursor, Claude Code, remote
orchestrators).

## Derivation rule

The MCP tool list is derived **directly** from

    visio_system/tools/consolidated.py::CONSOLIDATED_TOOL_NAMES

No rename. No reordering. No additions. No silent collapses. Parity is
enforced at import time by `visio_mcp.contract.build_tool_registry` and
asserted by `tests/test_mcp_contract.py`.

If a capability must change shape, the update lands in
`CONSOLIDATED_TOOL_NAMES` first (and in `CORE_CAPABILITIES.md` §2). The
MCP layer follows.

## Tool inventory (15 names — roadmap ceiling)

| # | Name | Idempotent | Mutates | Primary error codes |
|---|---|---|---|---|
| 1 | `recommend_template` | yes | no | `LIBRARY_EMPTY`, `MODEL_UNAVAILABLE` |
| 2 | `search_templates` | yes | no | — |
| 3 | `analyze_template` | yes | no | `FILE_NOT_FOUND`, `PARSE_FAILED` |
| 4 | `search_stencils` | yes | no | — |
| 5 | `get_stencil` | yes | no | `FILE_NOT_FOUND` |
| 6 | `open_document` | yes | no | `FILE_NOT_FOUND` |
| 7 | `create_from_template` | yes | yes | `TEMPLATE_NOT_FOUND`, `OUTPUT_EXISTS` |
| 8 | `save_document` | yes | yes | `DOC_NOT_OPEN`, `INVALID_OOXML`, `SAVE_REQUIRES_RELOAD` |
| 9 | `render_page` | yes | no | `FILE_NOT_FOUND`, `RENDER_FAILED` |
| 10 | `upsert_shape` | yes | yes | `DOC_NOT_OPEN`, `INVALID_TYPE`, `DUPLICATE_KEY` |
| 11 | `upsert_connector` | yes | yes | `NODE_NOT_FOUND`, `CONNECTOR_GLUE_INVALID`, `SAVE_REQUIRES_RELOAD` |
| 12 | `update_text` | yes | yes | `SELECTOR_NOT_FOUND` |
| 13 | `remove_shape` | yes | yes | `SELECTOR_NOT_FOUND` |
| 14 | `edit_shape` | yes | yes | `SELECTOR_NOT_FOUND` |
| 15 | `insert_from_stencil` | yes | yes | `FILE_NOT_FOUND` |

This lands the ≤15 ceiling mandated by
`refine/CORE_CAPABILITIES.md` §2.1.

### Consolidations applied

- `list_templates` folded into `search_templates` — empty keywords lists
  the whole library.
- `list_stencils` folded into `search_stencils` — same rule.
- `set_shape_position` / `set_shape_size` / `edit_shape_style` (and
  related line/fill/width setters and `nudge_shape`) folded into
  `edit_shape(selector, patch)` with a `{position, size, style}` patch
  schema.
- `analyze_connections` folded into `analyze_template` — the atomic
  6-step bundle already includes the connection topology the legacy
  tool emitted.
- `generate_edit_plan` is not on the primary surface; it remains
  callable through the deprecation alias band while prompts migrate
  to using the skill-driven workflow.

All legacy names keep working for one transition cycle via the
warn-and-forward band in `visio_system/tools/consolidated.py`.

## Transport

- **stdio** — default, implemented in `visio_mcp/server.py::serve_stdio`.
  Requires the `mcp[cli]` Python SDK. The scaffold degrades gracefully
  when the SDK is not installed: the tool registry is still exposed for
  tests.
- **sse** — deferred. The roadmap §5 flags it as speculative; add it
  only when a concrete remote-deployment target materializes.

## Error envelope

Defined in `visio_mcp/errors.py`:

```
VisioToolError {
  code: ErrorCode,       # machine-readable, enum-constrained
  message: str,          # human-readable
  hint: str | None,      # remediation hint (e.g., "call open_document")
  recoverable: bool,     # whether the client should retry
  details: dict          # optional extra context
}
```

`SAVE_REQUIRES_RELOAD` is the protocol-level enforcement of the
11/13 lesson: a connector write that is not preceded by
`open_document(saved_path)` must fail fast with this code.

## Session model

- No hidden global state. The document handle returned by
  `open_document` is passed explicitly on subsequent mutating calls.
- Persistence for conversation memory stays on agno + SqliteDb.
- The MCP server is stateless across tool calls *within* the same
  process; it stores nothing to disk beyond what `save_document` and
  `render_page` create.

## Idempotency

Every mutating tool accepts a stable `node_key` / `edge_key` and
returns `{status: "created"|"updated"|"unchanged", key, warnings}`.
Repeated calls with identical payload are no-ops.

## Patch application

`visio_mcp.server.build_server_registry` calls
`visio_system.patches.apply_patches()` before returning the registry.
The call is idempotent; double-invocation is safe. This is how the
Batch B "explicit patch application" acceptance gate is satisfied on
the MCP path. The agno path inherits the same behavior via
`tests/conftest.py` and the legacy import side effect.

## Adding a new tool

If you truly must expand the surface:

1. Extend `CONSOLIDATED_TOOL_NAMES` in `visio_system/tools/consolidated.py`.
2. Wire the implementation inside `get_consolidated_tools(...)`.
3. Add an entry to `_SPEC_TABLE` in `visio_mcp/contract.py`.
4. Run `tests/test_mcp_contract.py` and
   `tests/test_consolidated_tool_surface.py` — both must pass.
5. Update `CORE_CAPABILITIES.md` §2 to justify the new capability.

If a new tool is purely an adapter over existing primitives (e.g.,
merging two setters), prefer collapsing within the existing name
instead of growing the surface.
