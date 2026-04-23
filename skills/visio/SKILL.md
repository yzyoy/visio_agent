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
7. **Render** — `render_page(page=0, scale=2.0, mode="data")` to
   confirm. Mode `"url"` for images larger than the 120 KB data-URI cap.

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

## 4. Output conventions

- Generated files go to `outputs/<session>/` (gitignored). The agno
  shell supplies the session id.
- Preview images: prefer `render_page(mode="data")` when the image is
  under the 120 KB cap; otherwise use `mode="url"` and return the URL.
- Always return the path of the saved document in the final assistant
  message so the user can re-open it.

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
