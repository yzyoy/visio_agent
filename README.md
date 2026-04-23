# AgentOS 的 Visio 助手

中文 | [English](./README_en.md)

基于 agno 的 AI Visio 绘图与编辑系统。无需安装 Microsoft Visio——直接读写 `.vsdx`。

## 🎯 架构总览

```
agent/
├── apps/
│   ├── agent_os.py          # ← 规范运行入口（AgentOS + FastAPI）
│   └── visio_agent.py       # agno Agent 工厂（注入 15 个工具）
├── visio_core/              # 纯 Python 核心库（零 agno 依赖）
│   ├── tools/               #   VisioTools / PromptTools / consolidated
│   ├── templates/           #   TemplateManager / StencilManager
│   ├── utils/               #   DiagramBuilder、渲染、matcher…
│   ├── patches/             #   vsdx 猴子补丁（需显式调用）
│   └── api/                 #   FastAPI 预览路由
├── visio_mcp/               # MCP 传输层（15 工具的契约视图）
│   ├── contract.py
│   ├── server.py
│   └── errors.py
├── skills/visio/            # 面向 Agent 的 Skill（工作流知识）
│   ├── SKILL.md
│   └── checklists/
├── assets/                  # 只读资源
│   ├── templates/           #   .vsdx 模板与 stencils
│   └── indexes/             #   lite + 全量索引
├── tools-offline/           # 离线维护脚本（不暴露给 LLM）
├── tests/                   # pytest 回归套件
├── refine/                  # 重构历史文档（归档，只读）
├── .state/                  # 运行时状态（gitignored）
│   ├── dialog/              #   会话上下文 JSON
│   └── agno_sessions.db     #   SqliteDb
└── outputs/                 # 生成的 .vsdx 与预览 PNG（gitignored）
```

三个不可逾越的边界：

1. **agno** 是顶层运行壳，由 `apps/agent_os.py` 装配。
2. **`visio_core`** 只做图形操作；`import visio_core` 不依赖 agno。
3. **`visio_mcp`** 只是把 `visio_core` 暴露为 MCP 契约——不增加、重命名或删除工具。

## 🚀 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env    # 填入 DEEPSEEK_API_KEY
python -m apps.agent_os # 访问 http://localhost:7777
```

开发热重载：

```bash
python -m uvicorn apps.agent_os:app --reload
```

启动时 `apps/agent_os.py` 会 **显式** 调用 `visio_core.apply_patches()` 打上 vsdx 补丁，并创建 `.state/` 与 `outputs/` 目录。

## 🔧 公开工具表面（15 个，不多不少）

所有 LLM / MCP 客户端可见的工具，完整定义见 `visio_core/tools/consolidated.py::CONSOLIDATED_TOOL_NAMES`，由 `visio_mcp/contract.py` 在传输层原样重投影。

| 分类 | 工具 | 摘要 |
| --- | --- | --- |
| 推荐 / 发现 | `recommend_template` | 用自然语言需求排序模板库 |
|  | `search_templates` | 关键词或空查询列模板库 |
|  | `analyze_template` | 原子 6 步结构分析（info+shapes+connections+positions+groups+topology） |
|  | `search_stencils` | 关键词或空查询列 stencil 库 |
|  | `get_stencil` | 返回 stencil 元数据与 master 列表 |
| 文档生命周期 | `open_document` | 打开已有文档 |
|  | `create_from_template` | 从指定模板创建新文档 |
|  | `save_document` | 保存；之后读连接器前必须 `open_document` 重载 |
|  | `render_page` | 渲染某页为 data URI 或 URL |
| 幂等编辑 | `upsert_shape` | 按 `node_key` 创建或更新形状 |
|  | `upsert_connector` | 按 `edge_key` 创建或更新连接器 |
|  | `update_text` | 按 id / key / match 更新文本 |
|  | `remove_shape` | 删除形状（智能重连上游边） |
|  | `edit_shape` | 单次 patch：`{position, size, style}` |
|  | `insert_from_stencil` | 从 stencil 插入 master |

## 🛠️ MCP 层

```python
from visio_mcp import MCP_TOOL_NAMES, MCP_TOOL_SPECS
from visio_mcp.server import build_server_registry, invoke

registry = build_server_registry(
    template_dir="assets/templates",
    dialog_dir=".state/dialog",
    session_id="demo",
)
print(sorted(registry))               # == sorted(MCP_TOOL_NAMES)
print(invoke(registry, "search_templates"))
```

stdio 传输（需要 `pip install mcp[cli]`）：

```bash
python -m visio_mcp.server
```

所有错误都会流经 `VisioToolError`，携带机器可读的 `code`（`FILE_NOT_FOUND`、`DOC_NOT_OPEN`、`DUPLICATE_KEY`、`CONNECTOR_GLUE_INVALID`、`SAVE_REQUIRES_RELOAD`、`NODE_NOT_FOUND`、`INVALID_TYPE`、`PARSE_FAILED`、`TEMPLATE_NOT_FOUND`、`OUTPUT_EXISTS`、`SELECTOR_NOT_FOUND`、`INVALID_OOXML`、`RENDER_FAILED`、`LIBRARY_EMPTY`、`MODEL_UNAVAILABLE`）。

## 📦 visio_core 直接调用（离线脚本 / 测试）

```python
from visio_core import apply_patches, VisioTools, PromptTools

apply_patches()

T = VisioTools(session_id="demo")
T.load_diagram("assets/templates/library/try.vsdx")
T.add_or_update_shape("step1", "处理数据", "Rectangle", 4.0, 7.0)
T.add_or_update_shape("step2", "输出结果", "Parallelogram", 4.0, 5.5)
T.add_or_update_connector(from_node_key="step1", to_node_key="step2", label="Next")
T.save_diagram("outputs/demo.vsdx")
```

`VisioTools` 是实现层；agno Agent 与 MCP server 都是它之上的薄包装——永远不要在 LLM 面前直接暴露 `VisioTools` 的内部方法。

## 🧭 典型流程（Skill 强制顺序）

Skill 文件位于 `skills/visio/SKILL.md`，强约束如下顺序：

1. `recommend_template(requirement, top_k=5)`
2. `analyze_template(path)` — 原子一次，勿拆成六步
3. 规划：以 `node_key` / `edge_key` 命名每个形状与边
4. `open_document(path)` 或 `create_from_template(template, output_path)`
5. 只用 `upsert_shape` / `upsert_connector` / `update_text` / `remove_shape` / `edit_shape` / `insert_from_stencil`
6. `save_document()` → **必须** 紧接 `open_document(same_path)`，否则 MCP 会返回 `SAVE_REQUIRES_RELOAD`
7. `render_page(page=0, scale=2.0, mode="data")` 确认（>120KB 时自动落到 `mode="url"`）

## 🖼️ 预览与渲染

`render_page` 有两种模式：

- `mode="data"`：内联 data URI，超过 120KB 会自动切换到 URL。
- `mode="url"`：写入 `outputs/static/visio/`，由 AgentOS 的 `/static/visio` 静态挂载提供。

运行时的 FastAPI 辅助路由：

| 路径 | 用途 |
| --- | --- |
| `/api/visio/preview?path=...&page=0&scale=2` | 交互式预览页（颜色更贴近 Visio） |
| `/api/visio/test` | 图像渲染诊断页 |
| `/static/visio/*.png` | 生成 PNG 的直链 |

底层依赖 LibreOffice + poppler（`apt-get install libreoffice poppler-utils`）。颜色与原始 Visio 文件可能略有差异，这是开源转换链的已知限制。

## 🗂️ 运行时状态与生成物

| 用途 | 位置 | 是否 gitignored |
| --- | --- | --- |
| 对话上下文 | `.state/dialog/{session_id}.json` | ✅ |
| agno SqliteDb | `.state/agno_sessions.db`（由 `AGNO_SESSIONS_DB` 覆写） | ✅ |
| 生成 vsdx | `outputs/{session}/*.vsdx` | ✅ |
| 预览 PNG | `outputs/static/visio/*.png` | ✅ |
| 模板 / stencil 索引 | `assets/indexes/*.json` | 跟踪 |

## 🧰 离线维护

`tools-offline/` 下的脚本不会暴露给 Agent。最常用：

```bash
python tools-offline/library_maintenance/detect_watermarks.py \
    --library assets/templates/library \
    --out refine/library_audit/watermarks.json

python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates \
    --stencil-dir assets/templates/stencils \
    --out-dir assets/indexes
```

## 🧪 测试

```bash
pip install pytest
pytest tests/
```

主要回归点：`save_document` / `open_document` 往返、幂等 upsert、分组形状、模板推荐、MCP 契约一致性、以及 `visio_core` 不依赖 agno 的边界测试。

## ⚙️ 环境变量

见 `.env.example`：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | *(必填)* | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容基址 |
| `DEEPSEEK_MODEL_ID` | `deepseek-chat` | 模型 id |
| `AGNO_SESSIONS_DB` | `.state/agno_sessions.db` | agno SqliteDb 路径 |
| `VISIO_TEMPLATE_DIR` | `assets/templates` | 只读模板根 |
| `VISIO_DIALOG_DIR` | `.state/dialog` | 对话上下文落盘目录 |

## 📚 依赖

`agno>=2.5.8`、`openai>=2.26.0`、`vsdx>=0.5.16`、`Pillow>=10.0.0`；可选 `aspose-diagram-python` 用于高级特性。预览需要系统级 `libreoffice` 与 `poppler-utils`。

## ❓ 常见问题

- 浏览器未自动打开：手动访问 `http://localhost:7777`。
- 启动报错缺 `DEEPSEEK_API_KEY`：拷贝 `.env.example` 为 `.env` 并填入。
- 保存后 `upsert_connector` 报 `SAVE_REQUIRES_RELOAD`：先调用 `open_document(same_path)` 再写连接器。
