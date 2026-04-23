# MCP Contract (Canonical)

This is the current MCP contract source for the live codebase.

Tool names are authoritative in:
`visio_core/tools/consolidated.py::CONSOLIDATED_TOOL_NAMES`.
`visio_mcp.contract.MCP_TOOL_NAMES` must match it exactly.

Current surface (15 tools, no deprecation alias band):

1. `recommend_template`
2. `search_templates`
3. `analyze_template`
4. `search_stencils`
5. `get_stencil`
6. `open_document`
7. `create_from_template`
8. `save_document`
9. `render_page`
10. `upsert_shape`
11. `upsert_connector`
12. `update_text`
13. `remove_shape`
14. `edit_shape`
15. `insert_from_stencil`
