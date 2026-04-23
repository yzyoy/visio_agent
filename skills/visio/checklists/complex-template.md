# Checklist: complex templates (grouped shapes)

Goal: handle templates whose primary content lives inside Visio groups,
so structural listings don't silently miss half the diagram (diary 11/2).

Steps:

1. Always call `analyze_template(path)` and consume the `groups` tree.
   Do not rely on `shapes` alone for group-heavy templates.
2. When a target lives inside a group, address it via `node_key` after
   the first `upsert_shape` that touches it. Never rely on the group's
   internal id.
3. For large groups, prefer leaf-level edits. Editing the group root's
   text via `update_text` typically does not propagate to inner labels.
4. Avoid `remove_shape(reconnect="smart")` on a group leaf that is an
   intermediate hop in a chain of connectors — reconnection semantics
   for group-nested chains are not guaranteed. Remove at the group
   boundary instead.

Validation ritual:
- After the final `save_document` + `open_document` pair, call
  `analyze_template(path)` again and diff the `groups` tree against
  the pre-edit snapshot. Any unexpected drop in group depth usually
  means a save regressed the structure.
