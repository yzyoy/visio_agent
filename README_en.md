# Visio Assistant for AgentOS

English | [中文](./README.md)

AI-powered Visio drawing and editing on top of agno. No Microsoft Visio required — operates directly on `.vsdx` files.

## Quick start (in order)

1. **Clone the repository.**  
2. **Restore assets (recommended).**  
   Large template and index trees are not part of a bare clone; without them, `recommend_template`, `search_templates`, and `search_stencils` will not match a full developer setup. After restore, files must land under **`assets/templates/`** and **`assets/indexes/`** — see **[`assets/README.md`](assets/README.md)**.  
   **Asset-related Markdown (`.md`) must live under `assets/`** (for example [`assets/README.md`](assets/README.md)); do not add parallel docs elsewhere, or they will drift from the **`visio-assets-release.zip`** layout and `package_assets_release.py`.  
   - Open [**GitHub Releases**](https://github.com/xuxue152/visio_agent_new/releases) and download **`visio-assets-release.zip`** (~1.5 GiB; use the file name shown on the Releases page).
   - **Destination:** unpack **into the repository root** (the folder that contains `apps/` and `assets/`). Members are stored as `assets/templates/...` and `assets/indexes/...`, so after extraction you should have **`<repo>/assets/templates/`** and **`<repo>/assets/indexes/`** beside `apps/`. If your GUI unzip created **`.../<folder>/assets/...`**, move `assets/` up next to `apps/`, or use the command below with `--repo-root` pointing at the real repo root.
   - Recommended (from repo root; `--repo-root` defaults to that directory):

     ```bash
     python tools-offline/package_assets_release.py --extract path/to/visio-assets-release.zip
     ```

   - Optional bundle after local `.vsdx` / `.vssx` edits:

     ```bash
     python tools-offline/package_assets_release.py --out release/visio-assets-release.zip
     ```

3. **Dependencies and env**  

```bash
pip install -r requirements.txt
cp .env.example .env   # set DEEPSEEK_API_KEY (see **Environment variables** below)
```

4. **Run**  

```bash
python -m apps.agent_os   # http://localhost:7777
```

Hot reload:

```bash
python -m uvicorn apps.agent_os:app --reload --port 7777
```

On startup, `apps/agent_os.py` calls `visio_core.apply_patches()` and ensures `.state/dialog`, `.state/log`, and `outputs/` exist.

If you change template files on disk without refreshing indexes, run `regenerate_indexes` under **Offline maintenance** after restoring assets.

## Agent workflow (matches the skill)

Full rules: `skills/visio/SKILL.md`. Suggested order:

1. `recommend_template(requirement, top_k=5)`  
2. `analyze_template(path)` — **one** atomic call, not six separate steps  
3. Plan: name every shape and edge with `node_key` / `edge_key`  
4. `open_document(path)` or `create_from_template(template, output_path)`  
5. Edit only with `upsert_shape` / `upsert_connector` / `update_text` / `remove_shape` / `edit_shape` / `insert_from_stencil`  
6. Optional: `fit_page_to_drawing(page=0, margin=0.5)`  
7. After `save_document()`, **always** call `open_document(same_path)` before reading connectors (`SAVE_REQUIRES_RELOAD` if skipped)  
8. `render_page(page=0, scale=2.0, mode="data")` — auto `mode="url"` above ~120 KB

## Architecture and invariants

```
agent/
├── apps/              # agent_os.py (entry), visio_agent.py (16 tools)
├── visio_core/        # pure Python core (import works without agno)
├── visio_mcp/         # MCP contract projection; tool names unchanged
├── skills/visio/      # agent skill
├── assets/            # templates/, indexes/, asset-related .md (required here; see assets/README.md)
├── tools-offline/     # offline scripts, not LLM-exposed
├── tests/
├── .state/            # dialog, log, agno_sessions.db (gitignored)
└── outputs/           # vsdx, preview PNGs (gitignored)
```

1. **agno** is the top-level runtime, wired in `apps/agent_os.py`.  
2. **`visio_core`** owns Visio operations; never expose raw `VisioTools` internals to an LLM (agent and MCP are thin adapters).  
3. **`visio_mcp`** only re-projects the same tool set (`visio_core/tools/consolidated.py::CONSOLIDATED_TOOL_NAMES`).

Runtime paths worth knowing: `.state/dialog/`, `.state/log/`, outputs under `outputs/`, templates under `VISIO_TEMPLATE_DIR` (default `assets/templates`).

## Public tools (exactly 16)

| Category | Tool | Summary |
| --- | --- | --- |
| Discovery | `recommend_template` | Rank templates by natural-language need |
|  | `search_templates` | Keyword or empty browse of templates |
|  | `analyze_template` | Atomic 6-step structural bundle |
|  | `search_stencils` | Keyword or empty browse of stencils |
|  | `get_stencil` | Stencil metadata + master list |
| Document lifecycle | `open_document` | Open existing doc |
|  | `create_from_template` | New doc from template |
|  | `save_document` | Save; reopen with `open_document` before connector reads |
|  | `fit_page_to_drawing` | Fit page to content |
|  | `render_page` | Data URI or URL |
| Idempotent editing | `upsert_shape` | Create/update shape by `node_key` |
|  | `upsert_connector` | Create/update connector by `edge_key` |
|  | `update_text` | Update text by id / key / match |
|  | `remove_shape` | Remove shape; connector targets route to connector removal |
|  | `edit_shape` | Single patch; text normalized to one line |
|  | `insert_from_stencil` | Insert master from stencil |

## Preview and HTTP

`render_page`: `mode="data"` is inline (switches to `url` when large); `mode="url"` writes `outputs/static/visio/` and is served under `/static/visio`.

| Path | Purpose |
| --- | --- |
| `/api/visio/preview?path=...&page=0&scale=2` | Interactive preview |
| `/api/visio/test` | Rendering diagnostics |
| `/static/visio/*.png` | Direct PNG links |

Stack: LibreOffice + Poppler (e.g. `apt-get install libreoffice poppler-utils`). Colours may differ slightly from Microsoft Visio.

## MCP and calling `visio_core`

Registry:

```python
from visio_mcp import MCP_TOOL_NAMES
from visio_mcp.server import build_server_registry, invoke

registry = build_server_registry(
    template_dir="assets/templates",
    dialog_dir=".state/dialog",
    session_id="demo",
)
assert set(registry) == set(MCP_TOOL_NAMES)
print(invoke(registry, "search_templates"))
```

stdio (`pip install mcp[cli]`): `python -m visio_mcp.server`.  
Errors are `VisioToolError` with a machine-readable `code` (`SAVE_REQUIRES_RELOAD`, `LIBRARY_EMPTY`, etc.; see `visio_mcp/errors.py`).

Offline / tests:

```python
from visio_core import apply_patches, VisioTools

apply_patches()
T = VisioTools(session_id="demo")
T.load_diagram("assets/templates/library/try.vsdx")
T.add_or_update_shape("step1", "Process Data", "Rectangle", 4.0, 7.0)
T.add_or_update_connector(from_node_key="step1", to_node_key="step2", label="Next")
T.save_diagram("outputs/demo.vsdx")
```

## Offline maintenance

```bash
python tools-offline/library_maintenance/detect_watermarks.py \
    --library assets/templates/library \
    --out refine/library_audit/watermarks.json

python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates \
    --stencil-dir assets/templates/stencils \
    --out-dir assets/indexes
```

## Testing

```bash
pip install pytest
pytest tests/
```

## Environment variables

See `.env.example`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | *(required)* | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible base URL |
| `DEEPSEEK_MODEL_ID` | `deepseek-chat` | Model id |
| `AGNO_SESSIONS_DB` | `.state/agno_sessions.db` | agno SqliteDb path |
| `VISIO_TEMPLATE_DIR` | `assets/templates` | Read-only template root |
| `VISIO_DIALOG_DIR` | `.state/dialog` | Dialog context directory |
| `VISIO_LOG_DIR` | `.state/log` | Operation logs directory |

## Dependencies

`agno>=2.5.8`, `openai>=2.26.0`, `vsdx>=0.5.16`, `Pillow>=10.0.0`; optional `aspose-diagram-python`. Preview needs system `libreoffice` and `poppler-utils`.

## Troubleshooting

- Browser did not open: visit `http://localhost:7777` manually.  
- Missing `DEEPSEEK_API_KEY`: copy `.env.example` to `.env` and fill it in.  
- `upsert_connector` raises `SAVE_REQUIRES_RELOAD` after save: `open_document(same_path)` first.  
- Empty template search / `LIBRARY_EMPTY`: restore **`visio-assets-release.zip`** into the repo root so **`assets/templates/`** and **`assets/indexes/`** merge correctly — see [`assets/README.md`](assets/README.md) and **Quick start** above.
