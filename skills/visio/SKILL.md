# Visio Skill

**When to use:** the user wants to recommend, create, analyze, edit, or
annotate a Visio diagram through the agent.

This skill captures *workflow* knowledge. Capability knowledge lives in
the tool contract (`visio_mcp/contract.py` and
`visio_core/tools/consolidated.py::CONSOLIDATED_TOOL_NAMES`). Never
duplicate the tool list here; ask the MCP server for the current list.

---

## 1. Canonical workflow

Always follow these steps in order, skipping only the explicit
exceptions below:

1. **Recommend** — `recommend_template(requirement, top_k=5)` unless the
   user has already named a template file.
2. **Analyze** — `analyze_template(path)` returns the atomic 6-step
   bundle (info + shapes + connections + positions + groups + topology).
   Never split this into six separate calls; that is the legacy mistake
   from diary 11/10.
3. **Plan** — produce an edit plan expressed in `node_key` / `edge_key`
   terms. A good plan names every shape and edge before any mutation.
4. **Open** — `open_document(path)` or `create_from_template(template,
   output_path)` once per session handle.
5. **Mutate idempotently** — only call `upsert_shape`, `upsert_connector`,
   `update_text`, `remove_shape`, `edit_shape`, or
   `insert_from_stencil`. The non-idempotent legacy names
   (`add_shape`, `connect_shapes`) do not exist on the MCP surface.
   `edit_shape(selector, patch)` accepts a single dict with any subset of
   `{position, size, style}`; see `MCP_CONTRACT.md` for the
   schema.
6. **Save + reload ritual** — `save_document()` then
   `open_document(same_path)` before any connector verification. This is
   the diary 11/13 lesson, now enforced at the protocol level through
   the `SAVE_REQUIRES_RELOAD` error code.
7. **Render and surface preview** — `render_page(page=0, scale=2.0,
   mode="url")` to confirm. The tool returns **two artefacts in a single
   reply**: an inline fit-window image *and* a markdown link to the
   interactive viewer (`/api/visio/preview?path=...`). Both are funnelled
   through the same `render_and_cache_preview` pipeline as the HTML
   viewer, so the chat preview is byte-identical to what the user sees
   when they open the link — never a cropped title bar or half-rendered
   page. Mode `"data"` inlines the PNG as a base64 data URI for offline
   replay; it still returns the same interactive viewer link.

## 2. Selector conventions

- Prefer `node_key` whenever the shape was created via `upsert_shape`.
  It is the only stable identity across reloads.
- Fall back to `{match: {text, mode}}` for shapes authored by
  `create_from_template` that have no key yet.
- Never rely on numeric `shape_id` across save/reload.

## 3. Hard rules (diary pitfalls)

1. **Chinese-only prompts degrade Claude/GPT planning.** If the user
   writes in Chinese and the model is Claude/GPT, internally translate
   to English before planning. See diary `11_5`, `11_9`.
2. **Always re-open after save before reading connectors.** The saved
   VSDX must be re-indexed for connectors to be visible. See diary
   `11_13`. The MCP server raises `SAVE_REQUIRES_RELOAD` if you break
   this rule.
3. **Do not trust Aspose-trial output.** It watermarks silently. See
   diary `11_5`.
4. **Group-nested shapes require recursive analysis.** `analyze_template`
   already recurses; do not write any new list-only path that ignores
   groups. See diary `11_2`.
5. **Watermark filter runs before recommending any new template.** The
   offline pipeline in `tools-offline/library_maintenance/` is the
   authoritative check; `recommend_template` assumes its output is
   clean. See diary `11_4`.
6. **Never deliver a preview without the interactive link.** A bare
   inline image is unverifiable — the chat UI may crop the height,
   compress the title, or fail to load at all. Every preview reply must
   include the `[name](http://localhost:7777/api/visio/preview?path=...)`
   link so the user has a guaranteed fit-window, zoomable surface.
   `render_page` already returns both; forward its full output verbatim.
7. **Template deletions may leave stale connector references until cleanup is confirmed.**
   After deleting shapes from a template or partially edited file,
   assume some connectors may still carry deleted `Sheet.<id>` refs.
   Rely on the strengthened connector cleanup or an explicit orphan
   scan, not on "shape removed" wording alone.

## 4. Output conventions

- Generated files go to `outputs/<session>/` (gitignored). The agno
  shell supplies the session id.
- **Preview link is mandatory.** Every reply that produces, edits, or
  inspects a `.vsdx` file MUST end with the interactive preview link
  in markdown form:
  `[文件名](http://localhost:7777/api/visio/preview?path=<完整路径>)`.
  The link is what gives the user a fully fit-window, zoomable view.
  Forgetting it is a regression — the rendered PNG alone is not enough.
- **Preview images must be complete.** Always call `render_page` (which
  uses the `render_and_cache_preview` pipeline) instead of constructing
  raw `/static/visio/...` URLs by hand. The tool returns both the
  fit-window inline image and the interactive viewer link in one
  payload; forward both to the user verbatim.
- Prefer `render_page(mode="url")` for any non-trivial diagram. Only
  fall back to `mode="data"` when the user has explicitly asked for an
  offline / log-replay-friendly response and the diagram is small.
- Always return the path of the saved document in the final assistant
  message so the user can re-open it.
- When reporting a deletion result, explicitly state connector cleanup:
  say that connectors touching deleted shapes were removed, listed for
  follow-up, or that an orphan scan ran and found none. Never imply
  `shape removed` alone guarantees a clean page.

## 5. When NOT to act

- The lite template library is empty or missing. Bail with a pointer to
  `tools-offline/library_maintenance/regenerate_indexes.py`.
- The user requests in-browser WYSIWYG Visio fidelity. Refer to the
  "non-goals" in `refine/CORE_CAPABILITIES.md`.
- The user asks the agent to use `add_shape` / `connect_shapes`
  directly. Explain that these have been replaced by
  `upsert_shape` / `upsert_connector` and proceed with the idempotent
  variants.

## 6. Checklists

- Template analysis — `checklists/template-analysis.md`
- Save / verify ritual — `checklists/save-verify.md`
- Complex (grouped) templates — `checklists/complex-template.md`
