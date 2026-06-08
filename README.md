# AgentOS 的 Visio 助手

中文 | [English](./README_en.md)

基于 agno 的 AI Visio 绘图与编辑系统。无需安装 Microsoft Visio，直接读写 `.vsdx`。

## 快速开始（按顺序）

1. **克隆仓库**  
2. **恢复资产（推荐）**  
   仓库默认不包含大体量模板与索引；仅克隆代码时，`recommend_template` / `search_templates` / `search_stencils` 等行为与完整环境不一致。解压或合并后的文件必须落在 **`assets/templates/`** 与 **`assets/indexes/`**（详解见 **[`assets/README.md`](assets/README.md)**）。  
   **与资产、模板库、发行包相关的说明性 Markdown（`.md`）必须放在 `assets/` 下**（例如 [`assets/README.md`](assets/README.md)），不要散落到仓库其他目录，以免与 **`visio-assets-release.zip`** 的布局和维护脚本不一致。
   - 打开 [**GitHub Releases**]((https://github.com/yzyoy/visio_agent/releases))，下载 **`visio-assets-release.zip`**（约 1.5 GiB，以 Release 页为准）。
   - **解压目标：** 解压到 **仓库根目录**（包含 `apps/`、`assets/` 的那一层）。zip 内的相对路径形如 `assets/templates/...`、`assets/indexes/...`，解压完成后磁盘上应为 **`<repo>/assets/templates/`**、**`<repo>/assets/indexes/`**。若解压到新建的子文件夹（例如只选中 zip 解压到「`visio-assets-release/`」），会得到 **`.../visio-assets-release/assets/...`**，需把 **`assets`** 挪到仓库根下与 `apps` 并列，或使用下方命令指定根目录。
   - 推荐在本仓库根执行（`--repo-root` 默认为该根目录）：

     ```bash
     python tools-offline/package_assets_release.py --extract path/to/visio-assets-release.zip
     ```

   - 可选：本地改过 `.vsdx` / `.vssx` 后打包：

     ```bash
     python tools-offline/package_assets_release.py --out release/visio-assets-release.zip
     ```

3. **依赖与环境**  

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入 DEEPSEEK_API_KEY（见文末「环境变量」）
```

4. **启动**  

```bash
python -m apps.agent_os   # http://localhost:7777
```

开发热重载：

```bash
python -m uvicorn apps.agent_os:app --reload --port 7777
```

启动时 `apps/agent_os.py` 会显式调用 `visio_core.apply_patches()`，并创建 `.state/dialog`、`.state/log` 与 `outputs/`。

仅改模板未改索引时，可在解压资产后运行下文「离线维护」中的 `regenerate_indexes`。

## Agent 工作流（与 Skill 一致）

完整约束见 `skills/visio/SKILL.md`。建议顺序：

1. `recommend_template(requirement, top_k=5)`  
2. `analyze_template(path)` — **一次**原子调用，勿拆成多步  
3. 规划：用 `node_key` / `edge_key` 命名形状与边  
4. `open_document(path)` 或 `create_from_template(template, output_path)`  
5. 编辑仅用：`upsert_shape` / `upsert_connector` / `update_text` / `remove_shape` / `edit_shape` / `insert_from_stencil`  
6. 可选：`fit_page_to_drawing(page=0, margin=0.5)`  
7. `save_document()` 后 **必须** 紧接 `open_document(同一路径)`，否则会出现 `SAVE_REQUIRES_RELOAD`  
8. `render_page(page=0, scale=2.0, mode="data")` — 大于约 120KB 时自动改用 `mode="url"`

## 架构与边界

```
agent/
├── apps/              # agent_os.py（入口）、visio_agent.py（16 工具注入）
├── visio_core/        # 纯 Python 核心（import 不依赖 agno）
├── visio_mcp/         # MCP 契约映射，不增减工具名称
├── skills/visio/      # Agent Skill
├── assets/            # templates/、indexes/、资产相关 .md（须在此目录；见 assets/README.md）
├── tools-offline/     # 离线脚本，不暴露给 LLM
├── tests/
├── .state/            # dialog、log、agno_sessions.db（gitignored）
└── outputs/           # vsdx、预览 PNG（gitignored）
```

1. **agno** 为顶层运行时，在 `apps/agent_os.py` 装配。  
2. **`visio_core`** 只负责图形操作；不在 LLM 侧直接暴露 `VisioTools` 内部方法（Agent/MCP 为薄封装）。  
3. **`visio_mcp`** 仅将 `visio_core` 按契约投影，不重命名或删增工具集合（真源：`visio_core/tools/consolidated.py::CONSOLIDATED_TOOL_NAMES`）。

主要运行时路径：对话上下文 `.state/dialog/`；操作日志与保存快照 `.state/log/`；生成物 `outputs/`；模板根默认 `VISIO_TEMPLATE_DIR=assets/templates`。

## 公开工具（16 个）

| 分类 | 工具 | 摘要 |
| --- | --- | --- |
| 推荐 / 发现 | `recommend_template` | 按自然语言需求排序模板 |
|  | `search_templates` | 关键词或空查询列模板 |
|  | `analyze_template` | 原子 6 步结构分析 |
|  | `search_stencils` | 关键词或空查询列 stencil |
|  | `get_stencil` | stencil 元数据与 master 列表 |
| 文档生命周期 | `open_document` | 打开已有文档 |
|  | `create_from_template` | 从模板新建 |
|  | `save_document` | 保存；读连接器前需再 `open_document` |
|  | `fit_page_to_drawing` | 按内容适应页面 |
|  | `render_page` | 渲染为 data URI 或 URL |
| 幂等编辑 | `upsert_shape` | 按 `node_key` 创建或更新形状 |
|  | `upsert_connector` | 按 `edge_key` 创建或更新连接器 |
|  | `update_text` | 按 id / key / match 更新文本 |
|  | `remove_shape` | 删除形状；连接器目标会走连接线删除 |
|  | `edit_shape` | 单次 patch；文本归一化为单行 |
|  | `insert_from_stencil` | 从 stencil 插入 master |

## 预览与 HTTP

`render_page`：`mode="data"` 为内联 data URI（过大则自动 `url`）；`mode="url"` 写入 `outputs/static/visio/`，由 `/static/visio` 提供。

| 路径 | 用途 |
| --- | --- |
| `/api/visio/preview?path=...&page=0&scale=2` | 交互式预览 |
| `/api/visio/test` | 渲染诊断 |
| `/static/visio/*.png` | PNG 直链 |

底层：LibreOffice + poppler（如 `apt-get install libreoffice poppler-utils`）。颜色可能与 Visio 略有差异。

## MCP 与直接调用 core

Registry 示例：

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

stdio（需 `pip install mcp[cli]`）：`python -m visio_mcp.server`。  
错误类型为 `VisioToolError`，带机器可读 `code`（如 `SAVE_REQUIRES_RELOAD`、`LIBRARY_EMPTY`）；完整枚举见 `visio_mcp/errors.py`。

离线 / 测试层直接用法：

```python
from visio_core import apply_patches, VisioTools

apply_patches()
T = VisioTools(session_id="demo")
T.load_diagram("assets/templates/library/try.vsdx")
T.add_or_update_shape("step1", "处理数据", "Rectangle", 4.0, 7.0)
T.add_or_update_connector(from_node_key="step1", to_node_key="step2", label="Next")
T.save_diagram("outputs/demo.vsdx")
```

## 离线维护

```bash
python tools-offline/library_maintenance/detect_watermarks.py \
    --library assets/templates/library \
    --out refine/library_audit/watermarks.json

python -m tools-offline.library_maintenance.regenerate_indexes \
    --template-dir assets/templates \
    --stencil-dir assets/templates/stencils \
    --out-dir assets/indexes
```

## 测试

```bash
pip install pytest
pytest tests/
```

## 环境变量

见 `.env.example`：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | *(必填)* | DeepSeek API key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI 兼容基址 |
| `DEEPSEEK_MODEL_ID` | `deepseek-chat` | 模型 id |
| `AGNO_SESSIONS_DB` | `.state/agno_sessions.db` | agno SqliteDb |
| `VISIO_TEMPLATE_DIR` | `assets/templates` | 模板根 |
| `VISIO_DIALOG_DIR` | `.state/dialog` | 对话上下文目录 |
| `VISIO_LOG_DIR` | `.state/log` | 操作日志目录 |

## 依赖

`agno>=2.5.8`、`openai>=2.26.0`、`vsdx>=0.5.16`、`Pillow>=10.0.0`；可选 `aspose-diagram-python`。预览需系统级 `libreoffice` 与 `poppler-utils`。

## 常见问题

- 浏览器未打开：手动访问 `http://localhost:7777`。  
- 缺 `DEEPSEEK_API_KEY`：拷贝 `.env.example` 为 `.env` 并填写。  
- 保存后 `upsert_connector` 报 `SAVE_REQUIRES_RELOAD`：先 `open_document(同路径)`。  
- 模板搜索为空 / `LIBRARY_EMPTY`：按上文「恢复资产」解压 `visio-assets-release.zip` 到仓库根目录，并确认 **`assets/templates/`**、**`assets/indexes/`** 与本仓库合并（参见 [`assets/README.md`](assets/README.md)）。
