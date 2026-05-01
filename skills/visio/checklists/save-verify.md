# Checklist: save and verify

Goal: persist edits and surface any connector regression immediately.

Steps (enforced by the MCP error model):

1. `save_document(path?)` — writes the file. The MCP contract returns
   `{status: "saved", path, requires_reload: true}`.
2. `open_document(path)` — always re-open, even if the path is the
   same file that was just open. This is the diary 11/13 ritual.
3. Verification:
   - `analyze_template(path)` — confirm every authored `edge_key`
     appears exactly once in the returned `connections` list.
   - `render_page(page=0, mode="url")` — eyeball the layout. The tool
     returns *both* an inline fit-window image and a markdown link to
     the interactive preview viewer
     (`http://localhost:7777/api/visio/preview?path=...`). Forward the
     full output to the user. **Never strip the viewer link** — it is
     the only reliable fit-window surface and the user's primary way
     to confirm that nothing was cropped.
4. If the connector count drops or any edge is missing, treat it as
   the 11/13 regression class. Do not retry the edit blindly — report
   the diff to the user.

Common mistakes to avoid:
- Calling `upsert_connector` *before* re-opening after save. The MCP
  server will raise `SAVE_REQUIRES_RELOAD`.
- Trusting `analyze_template` on a doc that was never saved. It only
  sees in-memory state until the save+reload pair completes.
