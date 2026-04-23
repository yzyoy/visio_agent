# Checklist: template analysis

Goal: understand a template's structure before any mutation.

Use exactly one call: `analyze_template(path)`.

The atomic response contains every field the legacy 6-step workflow
produced separately. Expected keys in the returned structure:

1. `info` — template name, page count, overall size.
2. `shapes` — flat list with `id`, `text`, `node_key`, `type`, `x/y/w/h`.
3. `connections` — flat list of `{from_shape_id, to_shape_id, label}`.
4. `positions` — same as `shapes` but projected for layout queries.
5. `groups` — recursive tree of grouped shapes (diary 11/2 gap).
6. `topology` — edge-centric summary used for recommendation.

Consume rules:
- Do not re-call any of the legacy `*_from_loaded` tools. They no
  longer exist on the MCP surface.
- If `shapes` is empty, the template is a blank canvas. Warn the user
  and offer `create_from_template` with a different template.
- If a shape has no `node_key`, treat it as a template slot; address
  via `{match: {text, mode: "exact"}}` selectors until you add one
  through `upsert_shape` with an explicit key.
