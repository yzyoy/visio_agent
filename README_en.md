# Visio Assistant for AgentOS

English | [中文](./README.md)

AI-powered Visio drawing and editing on top of agno. No Microsoft Visio
required — operates directly on `.vsdx` files.

## 🎯 Architecture at a glance

```
agent/
├── apps/
│   ├── agent_os.py          # ← canonical runtime entry (AgentOS + FastAPI)
│   └── visio_agent.py       # agno Agent factory (injects the 16 tools)
├── visio_core/              # pure-Python core library (agno-free)
│   ├── tools/               #   VisioTools / PromptTools / consolidated
│   ├── templates/           #   TemplateManager / StencilManager
│   ├── utils/               #   DiagramBuilder, rendering, matcher…
│   ├── patches/             #   vsdx monkey-patches (explicit apply)
│   └── api/                 #   FastAPI preview router
├── visio_mcp/               # MCP layer (16-tool contract projection)
│   ├── contract.py
│   ├── server.py
│   └── errors.py
├── skills/visio/            # Agent-facing skill (workflow knowledge)
│   ├── SKILL.md
│   └── checklists/
├── assets/                  # read-only resources
│   ├── templates/           #   .vsdx templates and stencils
│   └── indexes/             #   lite + full indexes
├── tools-offline/           # offline maintenance scripts (not LLM-exposed)
├── tests/                   # pytest regression suite
├── refine/                  # refactor history (archival, read-only)
├── .state/                  # runtime state (gitignored)
│   ├── dialog/              #   session context JSON
│   └── agno_sessions.db     #   SqliteDb
└── outputs/                 # generated .vsdx + preview PNGs (gitignored)
```

Three invariants:

1. **agno** is the top-level runtime shell, wired in `apps/agent_os.py`.
2. **`visio_core`** handles all Visio operations; `import visio_core`
   works without agno installed.
3. **`visio_mcp`** re-projects `visio_core` through the MCP contract — it
   never adds, renames, or drops tools.

## 🚀 Quick start

```bash
pip install -r requirements.txt
cp .env.example .env    # set DEEPSEEK_API_KEY
python -m apps.agent_os # open http://localhost:7777
```

Hot reload during development:

```bash
python -m uvicorn apps.agent_os:app --reload
```

`apps/agent_os.py` **explicitly** calls `visio_core.apply_patches()` on
startup and ensures `.state/` and `outputs/` exist.

## 🔧 Public tool surface (exactly 16)

The single source of truth is
`visio_core/tools/consolidated.py::CONSOLIDATED_TOOL_NAMES`.
`visio_mcp/contract.py` re-projects the same set over the MCP transport.

| Category | Tool | Summary |
| --- | --- | --- |
| Discovery | `recommend_template` | Rank templates for a natural-language requirement |
|  | `search_templates` | Keyword (or empty) search of the template library |
|  | `analyze_template` | Atomic 6-step structural bundle (info+shapes+connections+positions+groups+topology) |
|  | `search_stencils` | Keyword (or empty) search of the stencil library |
|  | `get_stencil` | Stencil metadata + master list |
| Document lifecycle | `open_document` | Open an existing document |
|  | `create_from_template` | Create a new document from a named template |
|  | `save_document` | Save; must be followed by `open_document` before reading connectors |
|  | `fit_page_to_drawing` | Resize a page to fit all drawing content with margin |
|  | `render_page` | Render a page as data URI or URL |
| Idempotent editing | `upsert_shape` | Create/update a shape by `node_key` |
|  | `upsert_connector` | Create/update a connector by `edge_key` |
|  | `update_text` | Update text by id / key / match |
|  | `remove_shape` | Remove a shape; connector IDs auto-route to connector deletion |
|  | `edit_shape` | Single patch `{text, node_key, position, size, style}`; text is normalized to one line |
|  | `insert_from_stencil` | Insert a master from a stencil |

## 🛠️ MCP layer

```python
from visio_mcp import MCP_TOOL_NAMES, MCP_TOOL_SPECS
from visio_mcp.server import build_server_registry, invoke

registry = build_server_registry(
    template_dir="assets/templates",
    dialog_dir=".state/dialog",
    session_id="demo",
)
assert set(registry) == set(MCP_TOOL_NAMES)
print(invoke(registry, "search_templates"))
```

stdio transport (needs `pip install mcp[cli]`):

```bash
python -m visio_mcp.server
```

All errors flow through `VisioToolError` with a machine-readable `code`
(`FILE_NOT_FOUND`, `DOC_NOT_OPEN`, `DUPLICATE_KEY`,
`CONNECTOR_GLUE_INVALID`, `SAVE_REQUIRES_RELOAD`, `NODE_NOT_FOUND`,
`INVALID_TYPE`, `PARSE_FAILED`, `TEMPLATE_NOT_FOUND`, `OUTPUT_EXISTS`,
`SELECTOR_NOT_FOUND`, `INVALID_OOXML`, `RENDER_FAILED`, `LIBRARY_EMPTY`,
`MODEL_UNAVAILABLE`).

## 📦 Calling `visio_core` directly (offline / tests)

```python
from visio_core import apply_patches, VisioTools, PromptTools

apply_patches()

T = VisioTools(session_id="demo")
T.load_diagram("assets/templates/library/try.vsdx")
T.add_or_update_shape("step1", "Process Data", "Rectangle", 4.0, 7.0)
T.add_or_update_shape("step2", "Output", "Parallelogram", 4.0, 5.5)
T.add_or_update_connector(from_node_key="step1", to_node_key="step2", label="Next")
T.save_diagram("outputs/demo.vsdx")
```

`VisioTools` is the implementation layer; both the agno agent and the
MCP server are thin adapters over it — never expose its internal
methods directly to an LLM.

## 🧭 Canonical workflow (enforced by the skill)

`skills/visio/SKILL.md` mandates this order:

1. `recommend_template(requirement, top_k=5)`
2. `analyze_template(path)` — one atomic call, not six
3. Plan — name every shape and edge by `node_key` / `edge_key`
4. `open_document(path)` or `create_from_template(template, output_path)`
5. Mutate only via `upsert_shape` / `upsert_connector` /
   `update_text` / `remove_shape` / `edit_shape` /
   `insert_from_stencil`
6. Optionally call `fit_page_to_drawing(page=0, margin=0.5)` when the
   drawing should expand the page bounds like Visio's fit-to-drawing
7. `save_document()` → **always** followed by `open_document(same_path)`
   before reading connectors (protocol-enforced via
   `SAVE_REQUIRES_RELOAD`)
8. `render_page(page=0, scale=2.0, mode="data")` (auto-falls back to
   `mode="url"` above 120 KB)

## 🖼️ Preview and rendering

`render_page` has two modes:

- `mode="data"` — inline data URI; auto-falls back to URL above 120 KB.
- `mode="url"` — writes to `outputs/static/visio/` and returns a URL
  served by AgentOS at `/static/visio`.

Runtime FastAPI helpers:

| Path | Purpose |
| --- | --- |
| `/api/visio/preview?path=...&page=0&scale=2` | Interactive preview page (better colour fidelity) |
| `/api/visio/test` | Rendering diagnostics page |
| `/static/visio/*.png` | Direct links to generated PNGs |

The conversion chain is LibreOffice + Poppler (`apt-get install
libreoffice poppler-utils`). Colours may differ slightly from Microsoft
Visio — a known limitation of the headless open-source pipeline.

## 🗂️ Runtime state and outputs

| Purpose | Location | Git-ignored |
| --- | --- | --- |
| Dialog context | `.state/dialog/{session_id}.json` | ✅ |
| agno SqliteDb | `.state/agno_sessions.db` (override via `AGNO_SESSIONS_DB`) | ✅ |
| Generated VSDX | `outputs/{session}/*.vsdx` | ✅ |
| Preview PNGs | `outputs/static/visio/*.png` | ✅ |
| Template / stencil indexes | `assets/indexes/*.json` | tracked |

## 🧰 Offline maintenance

Scripts under `tools-offline/` are not exposed to the agent:

```bash
python tools-offline/library_maintenance/detect_watermarks.py \
    --library assets/templates/library \
    --out refine/library_audit/watermarks.json

python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates \
    --stencil-dir assets/templates/stencils \
    --out-dir assets/indexes
```

## 🧪 Testing

```bash
pip install pytest
pytest tests/
```

Coverage focuses on the `save_document` / `open_document` round-trip,
idempotent upsert, grouped shapes, template recommendation, the MCP
contract parity, and the `visio_core` agno-free import boundary.

## ⚙️ Environment variables

See `.env.example`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | *(required)* | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible base URL |
| `DEEPSEEK_MODEL_ID` | `deepseek-chat` | Model id |
| `AGNO_SESSIONS_DB` | `.state/agno_sessions.db` | agno SqliteDb path |
| `VISIO_TEMPLATE_DIR` | `assets/templates` | Read-only template root |
| `VISIO_DIALOG_DIR` | `.state/dialog` | Dialog-context directory |

## 📚 Dependencies

`agno>=2.5.8`, `openai>=2.26.0`, `vsdx>=0.5.16`, `Pillow>=10.0.0`;
optional `aspose-diagram-python` for advanced features. Preview needs
system `libreoffice` and `poppler-utils`.

## ❓ Troubleshooting

- Browser didn't open: visit `http://localhost:7777` manually.
- Startup fails with missing `DEEPSEEK_API_KEY`: copy `.env.example` to
  `.env` and fill it in.
- `upsert_connector` raises `SAVE_REQUIRES_RELOAD` after save: call
  `open_document(same_path)` before writing connectors again.
