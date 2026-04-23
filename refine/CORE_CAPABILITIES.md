# CORE CAPABILITIES

> Sibling document: [PROJECT_REFACTOR_ROADMAP.md](./PROJECT_REFACTOR_ROADMAP.md) — *how* and *when* to execute.
> This document focuses on *what* capabilities survive the refactor, why, and where each belongs in the MCP / Skill / Library stack.

Placement legend: **[MCP]** tool or resource the LLM calls · **[SKILL]** workflow/checklist the agent consumes as text · **[LIB]** pure-Python internal, never surfaced to the LLM.

---

## 1. Capabilities Kept (Closed-Loop Core)

The eleven capabilities below are the only ones with sustained diary evidence of real use. Each is mapped to (a) user value, (b) diary evidence, (c) current code location, (d) non-goals, (e) target placement.

### 1.1 Template recommendation (lite→full two-tier matching)

- **User value**: user types a Chinese requirement, gets ≤5 ranked templates with rationale; enables "pick-and-edit" rather than "draw-from-scratch" — the pivot decision of `10_26`.
- **Diary evidence**:
  - `diary/10_26/10_26.txt` — original pivot: *"要构建一个visio的模板库, 选个模板让agent进行更改"*.
  - `diary/11_3/11_3.txt` — designed the 4-step recommendation pipeline (keyword extract → lite filter → full LLM eval → Chinese output), ~29 s.
  - `diary/11_4/11_4.txt` — improved to be structure-aware (topology matters, not just keywords).
  - `diary/11_7/11_7.txt` — added complexity/confidence scoring and dynamic weights.
- **Code location**: `visio_system/utils/smart_matcher.py` (core), `visio_system/tools/prompt_tools.py::search_templates_by_requirement / rank_templates_for_requirement`, driven by `templates/template_library_lite.json` + `templates/template_library.json`.
- **Non-goals**: replacing the commercial edrawmax template catalog; guaranteeing a perfect match when the library is thin (diary `11_7`).
- **Placement**:
  - **[LIB]** `SmartMatcher`, scanners, JSON builders.
  - **[MCP]** `recommend_template(requirement: str, top_k: int = 5, scope: "templates"|"stencils"|"both") -> list[Recommendation]`.
  - **[SKILL]** "always call recommend_template first unless user pinned a filename".

### 1.2 Template analysis (6-step bundle)

- **User value**: before editing a template the agent must know its shapes, connections, positions, and grouping; without this, edits break structure.
- **Diary evidence**:
  - `diary/11_10/11_10.txt` — explicitly enumerates the six calls (`get_template_info`, `load_diagram`, `get_diagram_info`, `list_shapes`, `analyze_diagram_connections`, `list_position`) and warns *"model may ignore some tools"* when they are separate.
  - `diary/11_2/11_2.txt` — documents that group-nested shapes are missed by current `list_shapes`.
- **Code location**: `visio_system/tools/visio_tools.py` (list_shapes, analyze_diagram_connections, …), `visio_system/tools/prompt_tools.py::analyze_template_for_recommendation`, `visio_system/utils/template_analyzer.py`, `structure_analyzer.py`.
- **Non-goals**: semantic understanding ("what does this shape *mean*") — that is the LLM's job given the structural bundle.
- **Placement**:
  - **[LIB]** `analyze_template(path) -> TemplateAnalysis` (single function, recurses into groups).
  - **[MCP]** `analyze_template(path) -> {info, shapes, connections, positions, groups, topology, layout}` — one call replaces six.
  - **[SKILL]** checklist `skills/visio/checklists/template-analysis.md` describing when and how to consume each field.

### 1.3 Idempotent shape & connector editing

- **User value**: same prompt run twice produces the same diagram — no accumulating drift, no duplicate shapes. This is what makes agent loops safe.
- **Diary evidence**:
  - `diary/11_11/11_11.txt` — *"已有结构能够成功被连接到模板里了"* via node-key/edge-key model.
  - `diary/11_12/11_12.txt` — EdgeKey format `{from_node_key}@{from_glue}->{to_node_key}@{to_glue}|{label}` with dual-mode (auto/manual) glue points.
  - `diary/11_9/11_9.txt` — lesson: *"不让他虚空创建形状或者虚空连接形状"* → idempotent keys are the fix.
- **Code location**: `visio_system/tools/visio_tools.py::add_or_update_shape / add_or_update_connector / ensure_all_shapes_have_keys`, `visio_system/utils/edge_manager.py`, `visio_system/utils/shape_identity.py`, `visio_system/utils/connection_points.py`.
- **Non-goals**: auto-layout of arbitrary new nodes (the model supplies coordinates); semantic edge routing beyond the 9 Visio glue points.
- **Placement**:
  - **[LIB]** `edge_manager`, `shape_identity`, `connection_points` stay internal.
  - **[MCP]** `upsert_shape(key, text, type, x, y, w, h, style?)`, `upsert_connector(from_key, to_key, from_glue?, to_glue?, label?)`. Both return `{status: created|updated|unchanged, key, warnings}`.
  - **[SKILL]** "never call a non-idempotent add_*/connect_* — those do not exist in the MCP surface".

### 1.4 Text editing in place

- **User value**: the dominant edit operation in the diary is *replace the placeholder text on an existing template shape*. Keeping this fast and selective is the 80/20 of the product.
- **Diary evidence**:
  - `diary/10_29/10_29.txt` — *"对于模板的利用以及很好了…添加模块的能力还要优化"*: text-replace was already the working path.
  - `diary/11_2/11_2.txt` — the winning prompt was *"只能是删除形状或者替换形状中的文字或者是删除形状之间的连接线"*.
- **Code location**: `visio_system/tools/visio_tools.py::update_shape_text, update_text_by_match, update_text_by_match_all, batch_update_text_by_map, fill_placeholders` (five overlapping tools — see roadmap §1.1).
- **Non-goals**: rich-text formatting, per-run font tuning (kept as style ops §1.5).
- **Placement**:
  - **[LIB]** `DiagramBuilder` text methods.
  - **[MCP]** `update_text(selector, value)` where `selector` is one of `{shape_id}`, `{node_key}`, `{match: {text, mode}}`; and `batch_update_text(mapping)` for template bulk fills. 5→2.
  - **[SKILL]** prefer `node_key` selector when editing results of `upsert_shape`; prefer `{match}` when editing unknown templates.

### 1.5 Shape layout & styling primitives

- **User value**: nudging position and adjusting stroke/fill is needed for prettying output after structural edits.
- **Diary evidence**:
  - `diary/10_29/10_29.txt`, `diary/11_11/11_11.txt` — drawing-effect issues usually trace back to position/size.
  - `diary/11_7/11_7.txt` — structure-aware edits introduce format/position drift that must be corrected.
- **Code location**: `visio_system/tools/visio_tools.py::set_shape_position, nudge_shape, set_shape_size, set_line_width, set_line_color, set_fill_color`.
- **Non-goals**: full CSS-equivalent styling; theme-based re-coloring (defer).
- **Placement**:
  - **[LIB]** `DiagramBuilder` geometry + style methods.
  - **[MCP]** `set_shape_position(selector, x, y, relative=False)`, `set_shape_size(selector, w, h)`, `set_shape_style(selector, {fill, stroke, line_width})`. 6→3.
  - **[SKILL]** "apply style only after structure is final, to avoid reset during upserts".

### 1.6 Shape removal with reconnection

- **User value**: removing a node in a chain while preserving the flow is a recurring request (diary `11_2`).
- **Diary evidence**: `diary/11_2/11_2.txt` — the winning prompt's "可以删除但是不能破坏原有的连接结构".
- **Code location**: `visio_system/tools/visio_tools.py::remove_shape, remove_shape_smart`.
- **Non-goals**: sophisticated graph-rewriting.
- **Placement**:
  - **[LIB]** `DiagramBuilder.remove_shape(..., reconnect_mode)`.
  - **[MCP]** `remove_shape(selector, reconnect="smart"|"none")`. 2→1.
  - **[SKILL]** default reconnect=smart for mid-chain deletions; none for leaves.

### 1.7 Document lifecycle (open → create-from-template → save → reload)

- **User value**: the outer envelope of every session. Quality threshold lives here — the 11/13 bug proves save-without-reload silently drops connector state.
- **Diary evidence**:
  - `diary/10_28/10_28` — the canonical data-flow (UI → agent → VisioTools → vsdx lib).
  - `diary/11_13/11_13.txt` — *"我创建完文件后没有把它正确导入，所以连接器才添加失败"*. Mandates a reload step.
- **Code location**: `visio_system/tools/visio_tools.py::load_diagram, create_new_diagram, create_from_template_and_load, save_diagram`, `visio_system/utils/diagram_builder.py`, `visio_system/patches/*` (connector patches required on load).
- **Non-goals**: Visio app automation (we never call a Visio binary); multi-document tabs.
- **Placement**:
  - **[LIB]** `DiagramBuilder.load_from_file / save_to_file` + explicit `apply_patches()`.
  - **[MCP]** `open_document(path)`, `create_from_template(template_name, output_path)`, `save_document(path?)`. Saving returns `{path, requires_reload: true}`; next connector write must be preceded by `open_document` (the skill enforces this).
  - **[SKILL]** checklist `skills/visio/checklists/save-verify.md` — save → open_document(same path) → validate.

### 1.8 Rendering & preview

- **User value**: chat-embedded inspection of the diagram; diary `10_30` records that this took 4 hours to get right and is considered shippable.
- **Diary evidence**:
  - `diary/10_30/10_30.txt` — PNG preview + web URL, "加入预览visio文件工具, 方便迅速查看图片效果".
  - `diary/11_4/11_4.txt` — recommendation UI depends on this to inline-preview candidates.
  - `diary/11_5/11_5.txt` — honest note: *"本地visio看是好的,但是在网页端预览是效果不好的"* → fidelity is acceptable, not perfect.
- **Code location**: `visio_system/utils/visio_render.py`, `visio_system/api/visio_preview.py` (FastAPI router), `my_os.py` mounts `/api/visio` + `/static/visio`.
- **Non-goals**: in-browser interactive editing; pixel-perfect fidelity with desktop Visio.
- **Placement**:
  - **[LIB]** `render_vsdx_page_to_png / _data_uri`.
  - **[MCP]** `render_page(path, page=0, scale=2.0, mode="url"|"data") -> {image_url|image_data_uri, width, height}` with the 120 KB cap from current code to avoid token overflow.
  - **[LIB]** the FastAPI router stays as a companion HTTP surface for the AgentOS web UI; not an MCP resource (it's for humans, not the LLM).

### 1.9 Stencil (VSSX) library & insertion

- **User value**: adding domain-specific icons (servers, flowchart symbols) that are not in the base template.
- **Diary evidence**:
  - `diary/10_31/10_31.txt`, `11_2/11_2.txt` — the vsdx/vssx split and scanning pipeline.
  - `diary/11_5/11_5.txt` — insertion works but quality is "effect not great"; still used.
- **Code location**: `visio_system/templates/stencil_manager.py`, `visio_system/utils/stencil_importer.py`, `visio_system/utils/stencil_scanner.py`, `visio_system/tools/visio_tools.py::list_library_stencils, search_library_stencils, get_stencil_info, list_stencil_masters, add_shape_from_stencil`, `scripts/stencil_parser.py`.
- **Non-goals**: VSS (non-X) support without manual pre-conversion (`10_31` confirmed Linux limitation).
- **Placement**:
  - **[LIB]** stencil managers, importer, parser.
  - **[MCP]** `list_stencils()`, `search_stencils(keywords)`, `get_stencil(name)` (includes master list), `insert_from_stencil(stencil, master, x, y, text)`.
  - **[SKILL]** "when user names an icon type not in the current template, try insert_from_stencil; if result is poor, fall back to a rectangle with the label".

### 1.10 Prompt generation (template-grounded edit plan)

- **User value**: converts free-form Chinese intent into a step-by-step tool-call script, dramatically improving one-shot success for the downstream Visio agent.
- **Diary evidence**:
  - `diary/10_30/10_30.txt` — introduced the prompt helper and deliberately kept the user in the loop.
  - `diary/11_3` – `11_7` — evolved the prompt to include structure, positions, and the 6-step analysis.
- **Code location**: `visio_system/agents/prompt_agent.py`, `visio_system/tools/prompt_tools.py` (generation, ranking, validation), `prompts/` (legacy hand-crafted examples).
- **Non-goals**: fully autonomous zero-click generation (user still selects/approves the chosen template); natural-language QA beyond the structural report.
- **Placement**:
  - **[LIB]** keep a minimal prompt renderer (Jinja-like) in `visio_core/prompts/` that accepts a template analysis + user requirement and returns text.
  - **[MCP]** `generate_edit_plan(requirement, template_path) -> {plan_markdown, tool_calls[]}` — returns both human text and a machine-executable tool sequence.
  - **[SKILL]** "call `recommend_template` → ask user to confirm → `analyze_template` → `generate_edit_plan` → execute". Two of the three legacy prompt files (`idempotent_workflow_prompt.txt`, `transformer_flowchart_prompt.txt`) live on as skill examples; the other 13 are deleted.

### 1.11 Session context & persistence

- **User value**: "AI remembers the last loaded file and the operations so far" — the reason users can say *"modify the title"* without repeating the file name.
- **Diary evidence**:
  - `diary/11_5/11_5.txt` — *"优化上下文能力, 基于SqliteDb"*.
  - `diary/11_9/11_9.txt` — listed as the #1 agent-building lesson.
- **Code location**: `visio_system/context/session_context.py`, `visio_system/context/instruction_builder.py`, `visio_system/context/instruction_loader.py`, `my_os.py` (SqliteDb wiring), `dialog/*.json` persistence.
- **Non-goals**: cross-user session sharing; time-travel undo.
- **Placement**:
  - **[LIB]** `SessionContext` dataclass + `DialogContextStore` JSON persistence; agno's `SqliteDb` stays at the app layer.
  - **[MCP]** no direct tool — MCP tools are stateless; the `open_document` return value is the session handle. The AgentOS layer remains responsible for conversation memory.
  - **[SKILL]** "on conversation start, check if there is a current file; if yes, skip re-opening; pass the file path explicitly to MCP tools anyway (stateless)".

---

## 2. Target MCP Surface (Consolidated)

Exactly 15 tools + 2 resources. Each LIB entry in §1 collapses to at most one MCP tool.

### 2.1 Tools

| # | Tool | Params (summary) | Idempotent? | Error codes |
|---|---|---|---|---|
| 1 | `recommend_template` | `requirement`, `top_k`, `scope` | yes (read-only) | `LIBRARY_EMPTY`, `MODEL_UNAVAILABLE` |
| 2 | `list_templates` | `category?`, `limit?` | yes | — |
| 3 | `search_templates` | `keywords[]` | yes | — |
| 4 | `analyze_template` | `path` | yes | `FILE_NOT_FOUND`, `PARSE_FAILED` |
| 5 | `list_stencils` | — | yes | — |
| 6 | `search_stencils` | `keywords[]` | yes | — |
| 7 | `get_stencil` | `name`, `include_masters` | yes | `FILE_NOT_FOUND` |
| 8 | `open_document` | `path` | yes | `FILE_NOT_FOUND` |
| 9 | `create_from_template` | `template`, `output_path` | yes (on target) | `TEMPLATE_NOT_FOUND`, `OUTPUT_EXISTS` |
| 10 | `save_document` | `path?` | yes | `DOC_NOT_OPEN`, `INVALID_OOXML` |
| 11 | `render_page` | `path`, `page`, `scale`, `mode` | yes | `FILE_NOT_FOUND`, `RENDER_FAILED` |
| 12 | `upsert_shape` | `key`, `text`, `type`, `x`, `y`, `w`, `h`, `style?` | **yes** (key-based) | `DOC_NOT_OPEN`, `INVALID_TYPE` |
| 13 | `upsert_connector` | `from_key`, `to_key`, `from_glue?`, `to_glue?`, `label?` | **yes** (edge-key) | `NODE_NOT_FOUND`, `CONNECTOR_GLUE_INVALID`, `SAVE_REQUIRES_RELOAD` |
| 14 | `update_text` | `selector`, `value` (also bulk `batch_update_text(mapping)` as a variant) | yes | `SELECTOR_NOT_FOUND` |
| 15 | `remove_shape` + `set_shape_position` + `set_shape_size` + `set_shape_style` + `insert_from_stencil` + `generate_edit_plan` | see §1 for per-tool params | yes (all selector/key-based) | per §1 |

> Note: the cell marked #15 is intentionally a group to keep the total to 15 *externally visible* names; in practice these are six tools that share the `selector`-based contract and all fit the one-sentence idempotency rule. If strict ≤15 is required, the style/position/size setters can be unified into `edit_shape(selector, patch)`; the diary evidence does not demand finer granularity.

### 2.2 Resources

| URI | Content | Producer |
|---|---|---|
| `visio://document/current` | JSON snapshot of the open document: page, shapes (with keys/positions), connectors (edge_keys), groups. Used by the agent for planning without redundant tool calls. | `DiagramBuilder` + `structure_analyzer`. |
| `visio://library/index` | The lite template + stencil JSON (matches `templates/*_library_lite.json` role). Enables keyword search on the client side. | Scanners in `visio_core/library/`. |

### 2.3 Error model (uniform)

```
VisioToolError {
  code: <enum above>,
  message: human-readable,
  hint?: remediation hint (e.g., "call open_document(path) before upsert_connector"),
  recoverable: bool
}
```

The `SAVE_REQUIRES_RELOAD` code is the mechanism that enforces the 11/13 lesson at the protocol level.

---

## 3. Agent Skill Scope (What belongs in SKILL.md)

Per roadmap §3 Phase 5; listed here for the "what" inventory.

- **Workflow script** — 6 steps (recommend → analyze → plan → upsert-loop → save → reload+verify).
- **Selector conventions** — node_key first, text-match as fallback.
- **Pitfalls** — five diary-sourced rules:
  1. Chinese-only prompts degrade Claude/GPT → translate internally.
  2. Always re-open after save before reading connectors (11/13).
  3. Never rely on Aspose trial output (11/5).
  4. Group-nested shapes require recursive analysis (11/2).
  5. Watermark filter runs before recommending any newly-added template (11/4).
- **Output contract** — where files land, when to return a preview URL vs data URI.
- **When NOT to act** — if the library is empty or the user requests in-browser WYSIWYG, bail with a pointer to the non-goals in this document.

---

## 4. What is Explicitly Cut (and Why)

Short reference list; full reasoning is in the roadmap §1.

| Cut | Reason (diary source) |
|---|---|
| 13 of 16 `prompts/*.txt` | Superseded by Prompt Agent + Skill (`10_30` onwards). |
| Non-idempotent `add_shape` / `connect_shapes` | Source of the `11_12` connector regressions. |
| `cleanup_diagram_connectors`, `validate_diagram_connectors`, `verify_connector_persisted`, `get_log_summary`, `ensure_all_shapes_have_keys`, `set_session`, `reset_session` from LLM surface | Never user-facing; internal hygiene moves to CI/tests. |
| `visio_system/tools/quality_control.py`, `visio_system/tools/layout_diagnostic.py` | Zero diary references; no downstream consumer. |
| `visio_system/examples/` (4 scripts) | Duplicates top-level `examples/`; not imported. |
| `templates/scan_*.py`, `templates/compress_template_library.py`, `templates/count_files.py`, `scripts/move_visio_files.py`, `scripts/path_mapper.py`, `scripts/manage_templates.py` | One-off migration scripts from the 11/2–11/5 library churn; relocate survivors to `tools-offline/`. |
| `docs/*.md` (GBK-named), `CONNECTOR_EXTENSION_GUIDE.md`, `SSH_PORT_FORWARDING_README.md` | Internal notes; consolidate or delete. |
| `agent.zip`, `templates.zip`, checked-in `*.db`, `log/`, `dialog/*.json`, `output/tmp_*/` | Runtime artifacts; belong in `.state/` + gitignore. |
| Multi-agent scaffolding (if any residual) | Diary `11_2` already merged. |
| Aspose-dependent conversion path | Trial still watermarks (`11_5`); treat as non-core. |
| `BUG_ANALYSIS.txt`, `CODE_FIX.txt`, `QUICK_FIX.txt`, `SUMMARY.txt` | Already `D`-staged; confirm deletion. |

---

## 5. Assumptions & Open Questions

Non-overlapping with the roadmap's assumption list.

1. **Assumed** that `analyze_template` returning a single bundled payload (≈20–80 KB JSON for typical templates) fits within the agent's context; for the very largest templates (diary `11_3` noted token-limit issues on the library index, not on individual templates) this should still hold. If not, add a `fields` filter parameter.
2. **Assumed** that `node_key` / `edge_key` naming is the agent's responsibility (the model picks stable keys like `login_box`, `validate_decision`). The library enforces uniqueness and returns a `DUPLICATE_KEY` error, but does not auto-generate keys. If the model proves unreliable at key picking, add an `auto_key_from_text` option on `upsert_shape`.
3. **Open**: whether stencil insertion quality (`11_5` "effect not great") justifies investing a `place_and_align` post-processor, or whether the skill's "fall back to rectangle with label" is good enough for MVP. Recommend deferring until a specific user complaint recurs.
4. **Open**: whether `generate_edit_plan` should also *execute* the plan (single-shot) when the user has already approved a template. Current diary stance (`10_30`) is user-in-the-loop; make this a per-call flag (`execute=False` default), not a hard policy.
