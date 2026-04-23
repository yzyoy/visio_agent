# PROJECT REFACTOR ROADMAP

> Sibling document: [CORE_CAPABILITIES.md](./CORE_CAPABILITIES.md) — *what* stays and why.
> This document focuses on *how* and *when* to execute the refactor.

---

## 1. Problem Diagnosis

Evidence-based from `diary/` (primary) cross-checked against `visio_system/**` and `my_os.py`.

### 1.1 Surface-area explosion on the LLM side

- `visio_system/tools/visio_tools.py::get_visio_tools()` exposes **~45 tools** (≈55 methods defined).  `visio_system/tools/prompt_tools.py` adds another ~15 wrappers.
- Many tool pairs are near-duplicates, evidenced by the diary complaint *"屎山...太多地方要改"* (`diary/11_4/11_4.txt`):
  - `add_shape` vs `add_or_update_shape` (non-idempotent vs idempotent, same job).
  - `connect_shapes` vs `add_or_update_connector` — diary `11_12/11_12.txt` documents the connector bug rabbit-hole caused exactly by this ambiguity.
  - `update_shape_text` / `update_text_by_match` / `update_text_by_match_all` / `batch_update_text_by_map` / `fill_placeholders` — five overlapping text tools.
  - `remove_shape` vs `remove_shape_smart`.
  - `set_line_width` / `set_line_color` / `set_fill_color` — three trivial style setters.
  - `set_shape_position` + `nudge_shape`.
  - `get_shape_connections` / `query_shape_connections` / `analyze_diagram_connections`.
  - Six diagnostic tools (`cleanup_diagram_connectors`, `validate_diagram_connectors`, `verify_connector_persisted`, `get_log_summary`, `ensure_all_shapes_have_keys`, session getters) that the LLM should never need to call directly.
- `PromptTools` provides a six-method "6-step template analysis" facade (`get_template_info`, `load_template_for_analysis`, `get_diagram_info_from_loaded`, `list_shapes_from_loaded`, `analyze_connections_from_loaded`, `list_position_from_loaded`, `cleanup_analysis_temp_files`) that mirrors VisioTools. Diary `11_10/11_10.txt` proves the **workflow** must remain, but the *tool multiplicity* does not — it is six sequential calls that the model sometimes skips.

### 1.2 Chaotic directory responsibilities

| Area | Current state | Evidence of pain |
|---|---|---|
| Entry point | Single 115-line `my_os.py` mixes model config, secret API key, AgentOS assembly, FastAPI mounts, session admin. | `diary/10_27`, `10_28` — agno/DeepSeek compat hacks live inside it. Hard to test. |
| `prompts/` | 16 hand-crafted `.txt` prompt templates, largely superseded once the Prompt Agent (10/30) was built. | Diary `10_30/10_30.txt` — prompt assistant pipeline became the canonical way. |
| `docs/` | Mixed encodings (GBK filenames visible in listing), overlapping guides (`CONNECTOR_EXTENSION_GUIDE.md`, `CONNECTOR_VISIBILITY_FIX_SUMMARY.md`, two matching-process summaries), no index. | No diary ever references these docs after writing — they are internal notes. |
| `templates/` | Mixes **data** (`library/`, `stencils/`, `*.json` libraries), **one-off scripts** (`scan_templates.py`, `scan_stencils.py`, `compress_template_library.py`, `count_files.py`), **binary license** (`Aspose...lic`), **unpacked VSDX debris** (`transformer/`, `transformer_architecture/`). Total ~3.3 GB + a 1 GB `templates.zip` at repo root. | Diary `11_3`–`11_5` records catastrophic losses: discard-change wiped a day of work, blind batch conversion corrupted files, trial-Aspose still leaves watermarks. |
| `examples/` | Mix of runnable demos and accidental artifacts (`transformer_architecture.vsdx`, `try.vsdx`, `edge_centric_demo.py`, unpacked `try/` folder). | Never referenced from runtime code. Used during ad-hoc debugging. |
| `test/` | 11 hand-written scripts, most with `print()` asserts; no pytest discipline despite `.pytest_cache` present. | Diary confirms ad-hoc test habit — `11_12` admits iterating "六七遍" without a reproducible harness. |
| `output/` | Contains debug directories `test_connect_debug/`, `tmp_dbg/`, `tmp_idem/`, `tmp_ret/` + collision fixture `test_id_collision.vsdx`. | Git status shows these as untracked churn. |
| `log/` | 24 numbered operation-log sessions (`427/`…`450/`) checked into the repo. | Diary never mentions reading them; they are agent-runtime byproducts. |
| `dialog/` | Session JSON (`default.json`) colocated with source. Should be state, not source. | — |
| Repo root | `agent.zip` (25 MB), `templates.zip` (1 GB), `agno_sessions.db*`, `copilot-instructions.md` (empty), `.cursorignore` (empty). | Artifacts checked in, repo balloons for no functional reason. |
| `visio_system/examples/` | Four demo scripts (`layout_analysis_demo.py`, `optimized_agent_example.py`, `test_*`) duplicate top-level `examples/` and `test/`. | None are imported by runtime code. |
| `visio_system/patches/` | Two monkey-patch modules (`vsdx_connector_patch.py`, `connector_visibility_patch.py`) silently applied at import time. | Diary `11_12`–`11_13` prove they are needed; the problem is not their existence but that they are invisible side-effects. |
| `visio_system/tools/quality_control.py`, `layout_diagnostic.py` | Defined, exported, never cited by any diary. | No user ever consumed QC dashboards. |
| Stale top-level reports | `BUG_ANALYSIS.txt`, `CODE_FIX.txt`, `QUICK_FIX.txt`, `SUMMARY.txt` (already `D`-staged per `git status`). | Keep the deletions. |

### 1.3 Non-core experiments that pollute the code mental model

- **AutoXxx / Aider pipeline (10/23–10/25)**: preceded the Visio pivot. No code trace remains outside `requirements.txt` comments, but the `.log`/`.tex` diary evidence proves the project once had a different identity. No action needed beyond "do not resurrect".
- **Multi-agent split (≤11/2)**: `diary/11_2` says *"多agent确实是灾难，各种工具很繁琐，合并了"*. The current single-agent design is already the right answer.
- **Aspose commercial conversion (11/2, 11/4, 11/5)**: trial license watermarks, wasted days. Treat as sunk cost. Do NOT gate future features on it.
- **Mass stencil ingestion (2,835 `.vss` → `.vssx`, `11_2`–`11_5`)**: library bloated to 2.34 GB with many corrupted / low-quality entries; diary explicitly flags as a time sink. Must be pruned.

### 1.4 Known quality-threshold gaps on the core loop

From diary, the edit→save→verify loop has these open defects that **any refactor must protect**:

1. **Connector visibility after save** (`11_13`): file must be re-opened to re-index before connectors are addressed. Root cause is tool-interaction ordering, not the vsdx library.
2. **Watermark contamination** in recommended templates (`11_4`).
3. **Group-nested shapes** invisible to `list_shapes` on complex templates (`11_2`).
4. **Web-browser preview fidelity** is poor vs native Visio render (`11_5`).
5. **Chinese-only prompts** degrade model performance on Claude/GPT; diary `11_5`, `11_9` recommend EN-translated prompts.
6. **Format corruption** on structure-aware edits (`11_7` "输出却有了格式上的损坏").

---

## 2. Target State

### 2.1 Layered architecture

```
┌─────────────────────────────────────────────────────────┐
│  Agent Skill  (skills/visio/SKILL.md)                   │  ← workflow, conventions, pitfalls
├─────────────────────────────────────────────────────────┤
│  MCP Server   (visio_mcp/)                              │  ← ~12 tools + 2 resources
│               exposes *capabilities*, not *methods*     │
├─────────────────────────────────────────────────────────┤
│  Core Library (visio_core/ — renamed from visio_system) │  ← pure Python, no LLM
│   ├ diagram/   builder, shape_identity, edge_manager    │
│   ├ library/   template_manager, stencil_manager,       │
│   │            smart_matcher, scanners                  │
│   ├ render/    visio_render (PNG), preview router       │
│   ├ patches/   vsdx_connector_patch (explicit apply)    │
│   └ schema/    structure_analyzer, layout_config        │
└─────────────────────────────────────────────────────────┘
```

Design rule: **everything an LLM needs lives in MCP+Skill**; `visio_core` is never imported by the agent directly. `my_os.py` keeps only the CLI/HTTP wiring.

### 2.2 Directory convention

```
agent/
├ visio_core/                # renamed visio_system, no tools/, no agents/
├ visio_mcp/                 # new MCP server (stdio + sse)
│   ├ server.py
│   ├ tools/                 # thin adapters over visio_core
│   └ resources/             # live document snapshot, template index
├ skills/
│   └ visio/
│       ├ SKILL.md
│       └ checklists/        # 6-step template analysis, save/verify ritual
├ assets/                    # formerly templates/  (data only)
│   ├ templates/library/
│   ├ templates/stencils/
│   └ indexes/  (lite + full JSON libraries)
├ tools-offline/             # moved from scripts/ + templates/*.py
│   └ library_maintenance/   (scan, lite-ify, dedupe, watermark-check)
├ apps/
│   └ agent_os.py            # former my_os.py, config-driven
├ docs/                      # curated, one source of truth
├ tests/                     # pytest-based
├ .state/                    # runtime only, gitignored
│   ├ logs/   (former log/)
│   ├ dialog/ (former dialog/)
│   └ sessions.db
└ outputs/                   # generated artifacts, gitignored
```

### 2.3 MCP tool surface (target: 12 tools, 2 resources)

See [CORE_CAPABILITIES.md §2](./CORE_CAPABILITIES.md) for each tool's mapping, parameter granularity, and idempotency contract.

### 2.4 Non-goals (explicit)

- Commercial-grade template coverage (diary `11_12` concludes this is not reachable with current effort).
- In-browser WYSIWYG Visio fidelity (diary `11_5`).
- Aspose-based conversion without a paid license.
- Multi-agent orchestration.
- Automatic "one-shot" prompt-to-diagram without user template selection (`10_30` deliberately kept user-in-the-loop).

---

## 3. Phased Plan

Each phase is independently shippable; earlier phases reduce risk for later phases.

### Phase 0 — Freeze & Hygiene (0.5 day)

Goal: stop the bleeding before refactoring.

1. Delete or git-ignore checked-in runtime artifacts: `agent.zip`, `templates.zip`, `agno_sessions.db*`, `.pytest_cache/`, `log/`, `dialog/`, `output/tmp_*/`, `output/test_connect_debug/`, `output/test_connectors/`, `output/test_id_collision.vsdx`, `__pycache__/`, `templates/transformer/`, `templates/transformer_architecture/`.
2. Finalize deletion of stale reports already staged (`BUG_ANALYSIS.txt`, `CODE_FIX.txt`, `QUICK_FIX.txt`, `SUMMARY.txt`). Also delete empty `.cursorignore`, `copilot-instructions.md`.
3. **Extract the hard-coded DeepSeek API key** in `my_os.py:21` into `.env` / env var. This is a committed secret; rotate it.
4. Add `.gitignore` rules for `.state/`, `outputs/`, `*.db`, `*.zip`, `__pycache__/`.

**Validation**: `git status` clean after fresh clone + one agent run; secret-scan passes.

### Phase 1 — Tool Surface Consolidation (1–2 days)

Goal: shrink the LLM-facing tool list from ~60 to ≤15 without losing the closed loop.

For each collapse below, keep the underlying implementation in `visio_core`; only the `get_visio_tools()` export changes.

| Collapse | Action | Rationale |
|---|---|---|
| `add_shape` + `add_or_update_shape` | Keep only `upsert_shape` (idempotent, key-based). | Diary `11_11` confirms idempotent is the winning pattern. |
| `connect_shapes` + `add_or_update_connector` | Keep only `upsert_connector` with glue-point param (the 11/12 EdgeKey format). | Removing `connect_shapes` eliminates the entire 11/12 bug class. |
| 5 text-update tools | Keep `update_text(selector, value)` and `batch_update_text(mapping)`. Selector accepts `shape_id`, `node_key`, or text-match dict. | 5→2. |
| `remove_shape` + `remove_shape_smart` | Keep `remove_shape(selector, reconnect="smart"\|"none")`. | 2→1. |
| `set_line_width/color`, `set_fill_color` | Collapse into `set_shape_style(selector, style)`. | 3→1. |
| `set_shape_position` + `nudge_shape` | Keep `set_shape_position(selector, x, y, relative=False)`. | 2→1. |
| 3 connection-query tools | Keep `analyze_connections(scope)` (scope = page\|shape\|all). | 3→1. |
| 6 "from_loaded" prompt-tool wrappers | Replace with single `analyze_template(path)` that returns the 6-step bundle atomically. | Diary `11_10` proves the model skips steps when they are separate. |
| Diagnostic / session tools | Remove from LLM surface: `cleanup_diagram_connectors`, `validate_diagram_connectors`, `verify_connector_persisted`, `get_log_summary`, `ensure_all_shapes_have_keys`, `set_session`, `reset_session`, `layout_diagnostic.*`, `quality_control.*`. | Move to offline CLI / internal post-save hooks. |
| `PromptTools.validate_prompt_tools`, `get_available_visio_tools` | Remove — they reflect on a mutable tool list and will desync. | Replace with a static skill checklist. |

**Result**: the final `get_visio_tools()` returns a curated list matching [CORE_CAPABILITIES.md §2](./CORE_CAPABILITIES.md).

**Validation**: run the `prompts/idempotent_workflow_prompt.txt` and `transformer_flowchart_prompt.txt` regression flows; both must still complete end-to-end.

### Phase 2 — Library Pruning & Watermark Purge (1 day, mostly data work)

Goal: get `assets/templates/` to a trustworthy <500 MB set.

1. Write `tools-offline/library_maintenance/detect_watermarks.py` (heuristic: specific text-frame strings from Aspose trial; also detectable via OOXML embedded metadata).
2. Remove watermarked and zero-structure templates (the 287 removed in `11_4` was only the first pass).
3. Re-run `scan_templates.py` and regenerate both `template_library.json` (full) and `template_library_lite.json` after pruning.
4. Deduplicate `stencils/` by master-hash; diary `11_3` records heavy redundancy from the colleague's dump.
5. Keep the two-tier JSON design (diary `11_3`/`11_7` proved its value); move to `assets/indexes/`.

**Validation**: `SmartMatcher` recommendation test suite (diary `11_7` reports ~29 s full, target <5 s on lite-first path); memory footprint ≤200 MB during recommendation.

### Phase 3 — Core Library Carve-out (1 day)

Goal: make `visio_core` pure and importable without `agno`.

1. Rename `visio_system/` → `visio_core/`.
2. Move `agents/`, `context/instruction_*.py`, and the `PromptTools` class **out** of `visio_core`. `context/session_context.py` stays (it is just a dataclass + JSON store).
3. Make `patches/__init__.py` **explicit** — require callers to `apply_patches()` instead of side-effect import. Log which patches ran.
4. Delete `visio_system/examples/` (4 files), `visio_system/docs/` (empty). Fold anything valuable into `docs/` and `tests/`.
5. Delete `visio_system/tools/quality_control.py`, `visio_system/tools/layout_diagnostic.py` unless a concrete downstream consumer exists.  (Diary survey: none.)
6. Keep the 6-step analysis logic (in `utils/template_analyzer.py` / `structure_analyzer.py`) as a single public function `analyze_template(path) -> TemplateAnalysis`.

**Validation**: `python -c "import visio_core"` succeeds without `agno` installed. Unit tests cover: open→edit→save→reload round-trip; idempotent `upsert_shape/connector`; connector-visibility post-save (the `11_13` scenario).

### Phase 4 — MCP Server (2 days)

Goal: expose `visio_core` as an MCP server usable from Cursor, Claude Code, and the existing AgentOS wrapper.

1. `visio_mcp/server.py` using the official `mcp` Python SDK. Support both stdio and sse transports (diary `10_28` explicitly plans for this).
2. **Tools** (see CORE_CAPABILITIES.md §2 for the exact contract): `open_document`, `create_from_template`, `save_document`, `render_page`, `list_templates`, `search_templates`, `analyze_template`, `list_stencils`, `search_stencils`, `upsert_shape`, `upsert_connector`, `update_text`, `remove_shape`, `set_shape_style`, `recommend_template`, `generate_edit_plan`.
3. **Resources**: `visio://document/current` (live shapes + edges + positions snapshot), `visio://library/index` (lite library JSON).
4. **Error model**: one `VisioToolError` type with machine-readable `code` field (`FILE_NOT_FOUND`, `DOC_NOT_OPEN`, `DUPLICATE_KEY`, `CONNECTOR_GLUE_INVALID`, `SAVE_REQUIRES_RELOAD`). Diary `11_13` makes the last one mandatory.
5. **Idempotency**: every mutating tool accepts a stable `node_key`/`edge_key`; repeated calls with identical payload are no-ops. Return shape: `{status: "created"|"updated"|"unchanged", key: ..., warnings: [...]}`.
6. **Session**: no hidden global state; document handle returned from `open_document` is passed explicitly. Persistence for the AgentOS wrapper stays in `agno` + SqliteDb (diary `11_5`, `11_9` — treat as non-negotiable for UX).

**Validation**: MCP client (`mcp` CLI or Cursor) can walk the full closed-loop scenario from `prompts/user_login_flow_prompt.txt` using only MCP tools. No direct Python import of `visio_core` from the agent side.

### Phase 5 — Agent Skill (0.5 day)

Goal: move process knowledge out of 340-line instruction files into a skill the agent reads on demand.

Create `skills/visio/SKILL.md` with:

1. **When to use**: user wants to create / edit / annotate / recommend a Visio diagram.
2. **The canonical workflow** (consolidates `diary/10_28`, `10_30`, `11_7`, `11_10`):
   1. Call `recommend_template` (unless user already named one).
   2. Call `analyze_template(path)` — never skip; this is the 6-step bundle.
   3. Produce an *edit plan* in `node_key`/`edge_key` terms.
   4. `open_document` → sequence of `upsert_shape` / `upsert_connector` / `update_text` / `remove_shape` — **always idempotent variants**.
   5. `save_document`, then **re-open** before any connector verification (the `11_13` lesson).
   6. `render_page` to confirm.
3. **Hard rules** (pitfalls, from diary):
   - Never call `connect_shapes`/`add_shape` raw (they don't exist in MCP anymore, but reinforce).
   - Never auto-batch-import stencils without watermark check (`11_5`).
   - If the model is Claude/GPT and the user prompt is Chinese-only, internally translate to EN before planning (`11_5`, `11_9`).
   - Always pass glue points for load-bearing connectors; auto-mode is fine for cosmetic links (`11_12`).
4. **Output conventions**: outputs go to `outputs/<session>/`, preview via `render_page` returning either data URI (<120 KB) or URL.
5. **Checklists** in `skills/visio/checklists/`:
   - `template-analysis.md` — the 6 tool calls and what each returns.
   - `save-verify.md` — save → reload → validate-connectors.
   - `complex-template.md` — handle group-nested shapes (the `11_2` gap).

**Validation**: agent reading SKILL.md can reproduce the `transformer_flowchart_prompt.txt` run without any additional inline instructions.

### Phase 6 — Prompts & Docs Cleanup (0.5 day)

1. `prompts/`: keep `idempotent_workflow_prompt.txt`, `transformer_flowchart_prompt.txt` (canonical examples). Delete the other 13 + the update-summary; they are superseded by the Prompt Agent + Skill.
2. `docs/`: rename GBK-encoded files, fold the two matching-process writeups into one `docs/ARCHITECTURE.md`. Keep `CONNECTOR_VISIBILITY_FIX_SUMMARY.md` content inside `visio_core/patches/README.md`.
3. `examples/`: reduce to 2 scripts — `use_library_system.py` (recommendation) and `idempotent_edit.py` (new; replaces the 4 ad-hoc demos).
4. `test/`: replace with `tests/` pytest suite covering the five diary-evidenced regression scenarios (§1.4).

---

## 4. Risks & Validation

| Risk | Likelihood | Mitigation | Validation hook |
|---|---|---|---|
| Collapsing tools breaks an undocumented prompt that relied on the old name. | Medium | Keep old method names as deprecated aliases for one release; log a warning on call. | Run every `prompts/*.txt` against the new tool list in CI. |
| `apply_patches()` becoming explicit regresses connector behavior in the agent. | Medium-High | Call `apply_patches()` in `visio_mcp/server.py` startup and in `apps/agent_os.py`; add a pytest that fails if patches are not applied. | The 11/13 regression test: build a diagram with 3 upsert_connector calls, save, re-open, assert `edge_count == 3` and all connectors rendered in PNG. |
| Library pruning deletes a template a user referenced by name. | Low-Medium | Pruning writes a `removed.json` manifest; `recommend_template` falls back with a helpful error. | Diff `template_library_lite.json` before/after. |
| MCP migration leaves AgentOS UI broken. | Medium | Keep `apps/agent_os.py` wrapping the same `visio_core` (not via MCP) during the transition; flip switch only once MCP passes scenario tests. | Smoke test: load `examples/try.vsdx`, edit text, save, preview. |
| Secret key already leaked in git history. | Certain (`my_os.py:21`). | Rotate the DeepSeek key immediately; add pre-commit secret-scan. | `gitleaks` or `trufflehog` run on every commit. |
| Web preview still underperforms native Visio. | Certain (`11_5` diary). | Document this as a non-goal; add a "Open in local Visio" link in preview HTML. | Manual acceptance test. |
| Structure-aware edits re-introduce the 11/7 format-corruption bug. | Medium | Add post-save OOXML validator in `save_document` that re-parses the file and fails fast. | `tests/test_save_validity.py`. |
| Group-nested shapes (11/2 gap) still invisible. | Medium | `analyze_template` recursively walks `Shapes` children and returns a `groups` tree; documented in the skill checklist. | Unit test against one known grouped template (e.g., the `11_2/animal.png` source VSDX). |

### 4.1 Definition-of-Done for the refactor

- LLM-visible tool count ≤ 15.
- `git clone` → `pip install -r requirements.txt` → `python apps/agent_os.py` works in <5 minutes with no secrets committed.
- `pytest tests/` green; covers all five §1.4 regression scenarios.
- The 11/13 connector-visibility flow passes as an explicit test.
- `skills/visio/SKILL.md` is self-contained enough that a new agent run with only the skill + MCP (no system prompt) can create a working `user_login_flow.vsdx`.

---

## 5. Assumptions & Open Questions

Listed to avoid back-and-forth; resolve only if a downstream decision actually depends on them.

1. **Assumed**: the `visio_system/patches/*` are still required because the underlying `vsdx` package has not been patched upstream. Evidence: `diary/11_12`–`11_13`. Verify by running the current test suite with patches disabled — if it fails, the patches stay.
2. **Assumed**: the SqliteDb session store (`agno_sessions.db`) is for agent conversation memory only, not for Visio document state. The document-state JSON in `dialog/` is the authoritative place for "which file is loaded". Diary `11_5`, `11_9` are consistent with this.
3. **Assumed**: MCP transport choice is stdio for local dev + sse for remote per `diary/10_28`. Question: is there a concrete remote-deployment target, or is sse speculative? If speculative, ship stdio only in Phase 4.
4. **Assumed**: The commercial/branding goal mentioned in `diary/11_12` is deferred. The refactor targets an engineering-clean MVP, not a product release.
5. **Open**: retention policy for `.state/logs/` and `.state/dialog/` — suggest a 30-day TTL with an offline cleanup script; confirm this matches the user's debugging habits.
6. **Open**: whether `layout_diagnostic.py` / `quality_control.py` should be preserved as offline tools-offline artifacts or fully deleted. Current recommendation is delete (zero diary evidence of use); resurrect from git history if ever needed.
