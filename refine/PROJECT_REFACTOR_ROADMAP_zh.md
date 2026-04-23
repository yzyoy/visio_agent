# 项目重构路线图

> 姊妹文档：[CORE_CAPABILITIES_zh.md](./CORE_CAPABILITIES_zh.md) — *保留什么*以及*为何*。
> 本文聚焦*如何*以及*何时*执行重构。

---

## 1. 问题诊断

以 `diary/` 为主要证据，并与 `visio_system/**`、`my_os.py` 交叉核对。

### 1.1 LLM 侧表面爆炸

- `visio_system/tools/visio_tools.py::get_visio_tools()` 暴露 **约 45 个工具**（约 55 个已定义方法）。`visio_system/tools/prompt_tools.py` 另加约 15 个包装。
- 许多工具对近乎重复，日记抱怨 *「屎山...太多地方要改」*（`diary/11_4/11_4.txt`）可佐证：
  - `add_shape` vs `add_or_update_shape`（非幂等 vs 幂等，同一职责）。
  - `connect_shapes` vs `add_or_update_connector` —— 日记 `11_12/11_12.txt` 记录的正因这种模糊性导致的连接器 bug 深坑。
  - `update_shape_text` / `update_text_by_match` / `update_text_by_match_all` / `batch_update_text_by_map` / `fill_placeholders` —— 五个重叠的文本工具。
  - `remove_shape` vs `remove_shape_smart`。
  - `set_line_width` / `set_line_color` / `set_fill_color` —— 三个简单样式设置。
  - `set_shape_position` + `nudge_shape`。
  - `get_shape_connections` / `query_shape_connections` / `analyze_diagram_connections`。
  - 六个诊断工具（`cleanup_diagram_connectors`、`validate_diagram_connectors`、`verify_connector_persisted`、`get_log_summary`、`ensure_all_shapes_have_keys`、会话 getter）—— LLM 本不应直接调用。
- `PromptTools` 提供六方法的「六步模板分析」门面（`get_template_info`、`load_template_for_analysis`、`get_diagram_info_from_loaded`、`list_shapes_from_loaded`、`analyze_connections_from_loaded`、`list_position_from_loaded`、`cleanup_analysis_temp_files`），镜像 VisioTools。日记 `11_10/11_10.txt` 证明**工作流**必须保留，但*工具数量*不必 —— 模型有时会跳过这六次顺序调用。

### 1.2 目录职责混乱

| 区域 | 当前状态 | 痛点证据 |
|---|---|---|
| 入口 | 单文件 115 行的 `my_os.py` 混有模型配置、密钥、AgentOS 组装、FastAPI 挂载、会话管理。 | `diary/10_27`、`10_28` —— agno/DeepSeek 兼容 hack 写在里面。难测。 |
| `prompts/` | 16 份手写 `.txt`，Prompt Agent（10/30）建成后大多被取代。 | 日记 `10_30/10_30.txt` —— 提示助手管线成为规范做法。 |
| `docs/` | 混用编码（列表中可见 GBK 文件名），指南重叠（`CONNECTOR_EXTENSION_GUIDE.md`、`CONNECTOR_VISIBILITY_FIX_SUMMARY.md`、两份匹配过程摘要），无索引。 | 写日记后无日记再引用 —— 属内部笔记。 |
| `templates/` | 混有**数据**（`library/`、`stencils/`、`*.json` 库）、**一次性脚本**（`scan_templates.py` 等）、**二进制许可**（`Aspose...lic`）、**解压 VSDX 残留**（`transformer/` 等）。合计约 3.3 GB + 仓库根 1 GB `templates.zip`。 | 日记 `11_3`–`11_5`：discard-change 抹掉一天工作、盲批转换损坏文件、试用 Aspose 仍留水印。 |
| `examples/` | 可运行演示与偶然产物混杂（`transformer_architecture.vsdx`、`try.vsdx`、`edge_centric_demo.py`、解压的 `try/`）。 | 运行时代码从未引用。用于临时调试。 |
| `test/` | 11 个手写脚本，多为 `print()` 断言；虽有 `.pytest_cache` 却无 pytest 规范。 | 日记承认临时测试习惯 —— `11_12` 称迭代「六七遍」却无可复现 harness。 |
| `output/` | 含 `test_connect_debug/`、`tmp_dbg/` 等调试目录 + 碰撞用例 `test_id_collision.vsdx`。 | Git 状态显示为未跟踪变动。 |
| `log/` | 24 个编号操作日志会话（`427/`…`450/`）提交进仓库。 | 日记从未提阅读它们；属代理运行时副产物。 |
| `dialog/` | 会话 JSON（`default.json`）与源码同目录。应为状态，非源码。 | — |
| 仓库根 | `agent.zip`（25 MB）、`templates.zip`（1 GB）、`agno_sessions.db*`、空 `copilot-instructions.md`、空 `.cursorignore`。 | 产物入库，仓库膨胀无功能收益。 |
| `visio_system/examples/` | 四个演示脚本与顶层 `examples/`、`test/` 重复。 | 运行时代码均未 import。 |
| `visio_system/patches/` | 两个在 import 时静默应用的猴子补丁模块。 | 日记 `11_12`–`11_13` 证明需要；问题在于不可见的副作用。 |
| `visio_system/tools/quality_control.py`、`layout_diagnostic.py` | 已定义、已导出，无任何日记引用。 | 无用户消费 QC 面板。 |
| 顶层陈旧报告 | `BUG_ANALYSIS.txt` 等（git 状态已为 `D` 暂存）。 | 维持删除。 |

### 1.3 污染心智模型的非核心实验

- **AutoXxx / Aider 管线（10/23–10/25）**：早于 Visio 转向。除 `requirements.txt` 注释外代码无迹，但 `.log`/`.tex` 日记证明项目曾有不同身份。无需动作，仅「勿复活」。
- **多代理拆分（≤11/2）**：`diary/11_2` 称 *「多 agent 确实是灾难，各种工具很繁琐，合并了」*。当前单代理设计已正确。
- **Aspose 商业转换（11/2、11/4、11/5）**：试用许可水印，浪费数日。视为沉没成本。勿再以其为功能门槛。
- **大规模模具导入（2,835 `.vss` → `.vssx`，`11_2`–`11_5`）**：库膨胀至 2.34 GB，大量损坏/低质条目；日记明确为时间黑洞。必须修剪。

### 1.4 核心闭环上已知的质量门槛缺口

据日记，编辑→保存→校验循环存在以下**任何重构都必须保护**的未决缺陷：

1. **保存后连接器可见性**（`11_13`）：必须在重新寻址连接器前重开文件。根因是工具调用顺序，非 vsdx 库本身。
2. **推荐模板中的水印污染**（`11_4`）。
3. **组内嵌套形状** 在复杂模板上对 `list_shapes` 不可见（`11_2`）。
4. **浏览器预览保真度** 相对本机 Visio 渲染较差（`11_5`）。
5. **纯中文提示** 降低 Claude/GPT 表现；日记 `11_5`、`11_9` 建议内部译为英文。
6. **结构感知编辑导致的格式损坏**（`11_7`「输出却有了格式上的损坏」）。

---

## 2. 目标状态

### 2.1 分层架构

```
┌─────────────────────────────────────────────────────────┐
│  Agent Skill  (skills/visio/SKILL.md)                   │  ← 工作流、约定、陷阱
├─────────────────────────────────────────────────────────┤
│  MCP Server   (visio_mcp/)                              │  ← 约 12 工具 + 2 资源
│               暴露*能力*，而非*方法*                     │
├─────────────────────────────────────────────────────────┤
│  Core Library (visio_core/ — 自 visio_system 重命名)   │  ← 纯 Python，无 LLM
│   ├ diagram/   builder, shape_identity, edge_manager     │
│   ├ library/   template_manager, stencil_manager,         │
│   │            smart_matcher, scanners                   │
│   ├ render/    visio_render (PNG), preview router        │
│   ├ patches/   vsdx_connector_patch（显式 apply）        │
│   └ schema/    structure_analyzer, layout_config        │
└─────────────────────────────────────────────────────────┘
```

设计规则：**LLM 所需一切均在 MCP+Skill**；`visio_core` 从不被代理直接 import。`my_os.py` 仅保留 CLI/HTTP 接线。

### 2.2 目录约定

```
agent/
├ visio_core/                # 重命名自 visio_system，无 tools/、无 agents/
├ visio_mcp/                 # 新 MCP 服务器（stdio + sse）
│   ├ server.py
│   ├ tools/                 # 薄适配层，调用 visio_core
│   └ resources/             # 实时文档快照、模板索引
├ skills/
│   └ visio/
│       ├ SKILL.md
│       └ checklists/        # 六步模板分析、保存/校验仪式
├ assets/                    # 原 templates/（仅数据）
│   ├ templates/library/
│   ├ templates/stencils/
│   └ indexes/  (轻量 + 完整 JSON 库)
├ tools-offline/             # 自 scripts/ + templates/*.py 迁入
│   └ library_maintenance/   (扫描、轻量化、去重、水印检查)
├ apps/
│   └ agent_os.py            # 原 my_os.py，配置驱动
├ docs/                      # 策展，单一事实来源
├ tests/                     # 基于 pytest
├ .state/                    # 仅运行时，gitignore
│   ├ logs/   (原 log/)
│   ├ dialog/ (原 dialog/)
│   └ sessions.db
└ outputs/                   # 生成物，gitignore
```

### 2.3 MCP 工具面（目标：12 工具，2 资源）

各工具映射、参数粒度与幂等契约见 [CORE_CAPABILITIES_zh.md §2](./CORE_CAPABILITIES_zh.md)。

### 2.4 非目标（明确）

- 商业级模板覆盖（日记 `11_12` 结论：当前投入不可达）。
- 浏览器内 WYSIWYG 级 Visio 保真（日记 `11_5`）。
- 无付费许可的 Aspose 转换。
- 多代理编排。
- 无用户选模板的自动「一句话→图」（`10_30` 刻意保留用户参与）。

---

## 3. 分阶段计划

每阶段可独立交付；靠前阶段降低后续风险。

### 阶段 0 — 冻结与卫生（0.5 天）

目标：重构前先止血。

1. 删除或 git-ignore 已提交的运行时产物：`agent.zip`、`templates.zip`、`agno_sessions.db*`、`.pytest_cache/`、`log/`、`dialog/`、`output/tmp_*/`、`output/test_connect_debug/`、`output/test_connectors/`、`output/test_id_collision.vsdx`、`__pycache__/`、`templates/transformer/`、`templates/transformer_architecture/`。
2. 落实已暂存陈旧报告的删除（`BUG_ANALYSIS.txt` 等）。同时删除空 `.cursorignore`、`copilot-instructions.md`。
3. **将 `my_os.py:21` 硬编码的 DeepSeek API key** 抽到 `.env` / 环境变量。此为已提交密钥；需轮换。
4. 为 `.state/`、`outputs/`、`*.db`、`*.zip`、`__pycache__/` 增加 `.gitignore` 规则。

**验证**：全新 clone + 一次代理运行后 `git status` 干净；密钥扫描通过。

### 阶段 1 — 工具面合并（1–2 天）

目标：将 LLM 可见工具从约 60 缩至 ≤15，且不丢失闭环。

每项合并保留 `visio_core` 底层实现；仅改变 `get_visio_tools()` 导出。

| 合并项 | 动作 | 理由 |
|---|---|---|
| `add_shape` + `add_or_update_shape` | 仅保留 `upsert_shape`（幂等、基于 key）。 | 日记 `11_11` 确认幂等为胜出的模式。 |
| `connect_shapes` + `add_or_update_connector` | 仅保留带胶合点参数的 `upsert_connector`（11/12 EdgeKey 格式）。 | 去掉 `connect_shapes` 可消除整类 11/12 bug。 |
| 5 个文本更新工具 | 保留 `update_text(selector, value)` 与 `batch_update_text(mapping)`。选择器支持 `shape_id`、`node_key` 或文本匹配 dict。 | 5→2。 |
| `remove_shape` + `remove_shape_smart` | 保留 `remove_shape(selector, reconnect="smart"\|"none")`。 | 2→1。 |
| `set_line_width/color`、`set_fill_color` | 合并为 `set_shape_style(selector, style)`。 | 3→1。 |
| `set_shape_position` + `nudge_shape` | 保留 `set_shape_position(selector, x, y, relative=False)`。 | 2→1。 |
| 3 个连接查询工具 | 保留 `analyze_connections(scope)`（scope = page\|shape\|all）。 | 3→1。 |
| 6 个「from_loaded」提示工具包装 | 换为单次 `analyze_template(path)`，原子返回六步打包结果。 | 日记 `11_10`：拆步时模型会跳过。 |
| 诊断 / 会话工具 | 从 LLM 面移除：`cleanup_diagram_connectors` 等及 `layout_diagnostic.*`、`quality_control.*`。 | 迁至离线 CLI / 内部保存后钩子。 |
| `PromptTools.validate_prompt_tools`、`get_available_visio_tools` | 移除 —— 依赖可变工具列表会失步。 | 换为静态 skill 清单。 |

**结果**：最终 `get_visio_tools()` 返回与 [CORE_CAPABILITIES_zh.md §2](./CORE_CAPABILITIES_zh.md) 一致的精选列表。

**验证**：运行 `prompts/idempotent_workflow_prompt.txt` 与 `transformer_flowchart_prompt.txt` 回归流；二者须端到端完成。

### 阶段 2 — 库修剪与水印清理（1 天，多为数据工作）

目标：使 `assets/templates/` 成为可信的 <500 MB 集合。

1. 编写 `tools-offline/library_maintenance/detect_watermarks.py`（启发式：Aspose 试用特定文本框字符串；亦可经 OOXML 嵌入元数据检测）。
2. 移除带水印与零结构模板（`11_4` 删 287 仅为首轮）。
3. 修剪后重跑 `scan_templates.py`，再生 `template_library.json`（完整）与 `template_library_lite.json`。
4. 按 master-hash 对 `stencils/` 去重；日记 `11_3` 记录同事 dump 冗余严重。
5. 保留双层 JSON 设计（日记 `11_3`/`11_7` 已证其价值）；迁至 `assets/indexes/`。

**验证**：`SmartMatcher` 推荐测试（日记 `11_7` 报告完整约 29 秒，轻量优先路径目标 <5 秒）；推荐过程内存占用 ≤200 MB。

### 阶段 3 — 核心库剥离（1 天）

目标：`visio_core` 纯净、可在无 `agno` 时 import。

1. 重命名 `visio_system/` → `visio_core/`。
2. 将 `agents/`、`context/instruction_*.py` 与 `PromptTools` 类**迁出** `visio_core`。`context/session_context.py` 保留（仅为数据类 + JSON 存储）。
3. 使 `patches/__init__.py` **显式** —— 要求调用方 `apply_patches()`，而非副作用 import。记录已运行补丁。
4. 删除 `visio_system/examples/`（4 文件）、`visio_system/docs/`（空）。有价值内容并入 `docs/` 与 `tests/`。
5. 若无具体下游消费者，删除 `quality_control.py`、`layout_diagnostic.py`。（日记普查：无。）
6. 将六步分析逻辑（`utils/template_analyzer.py` / `structure_analyzer.py`）保留为单一公开函数 `analyze_template(path) -> TemplateAnalysis`。

**验证**：`python -c "import visio_core"` 在未安装 `agno` 时成功。单测覆盖：打开→编辑→保存→重载往返；幂等 `upsert_shape/connector`；保存后连接器可见性（`11_13` 场景）。

### 阶段 4 — MCP 服务器（2 天）

目标：将 `visio_core` 暴露为可供 Cursor、Claude Code 及现有 AgentOS 包装使用的 MCP 服务。

1. `visio_mcp/server.py` 使用官方 `mcp` Python SDK。支持 stdio 与 sse 传输（日记 `10_28` 明确规划）。
2. **工具**（确切契约见 CORE_CAPABILITIES_zh.md §2）：`open_document`、`create_from_template`、`save_document`、`render_page`、`list_templates`、`search_templates`、`analyze_template`、`list_stencils`、`search_stencils`、`upsert_shape`、`upsert_connector`、`update_text`、`remove_shape`、`set_shape_style`、`recommend_template`、`generate_edit_plan`。
3. **资源**：`visio://document/current`（实时形状+边+位置快照）、`visio://library/index`（轻量库 JSON）。
4. **错误模型**：统一 `VisioToolError`，机器可读 `code`（`FILE_NOT_FOUND`、`DOC_NOT_OPEN`、`DUPLICATE_KEY`、`CONNECTOR_GLUE_INVALID`、`SAVE_REQUIRES_RELOAD`）。日记 `11_13` 使最后一项为强制。
5. **幂等**：每个变更工具接受稳定 `node_key`/`edge_key`；相同负载重复调用为 no-op。返回：`{status: "created"|"updated"|"unchanged", key: ..., warnings: [...]}`。
6. **会话**：无隐藏全局状态；`open_document` 返回的文档句柄显式传递。AgentOS 包装持久化仍用 `agno` + SqliteDb（日记 `11_5`、`11_9` —— 对 UX 视为不可协商）。

**验证**：MCP 客户端（`mcp` CLI 或 Cursor）仅用 MCP 工具可走通 `prompts/user_login_flow_prompt.txt` 全闭环。代理侧不得直接 Python import `visio_core`。

### 阶段 5 — Agent Skill（0.5 天）

目标：将 340 行指令文件中的过程知识迁出，变为代理按需读取的 skill。

创建 `skills/visio/SKILL.md`，包含：

1. **何时使用**：用户要创建 / 编辑 / 标注 / 推荐 Visio 图。
2. **规范工作流**（合并 `diary/10_28`、`10_30`、`11_7`、`11_10`）：
   1. 调用 `recommend_template`（除非用户已点名）。
   2. 调用 `analyze_template(path)` —— 不可跳过；此为六步打包。
   3. 用 `node_key`/`edge_key` 术语产出*编辑计划*。
   4. `open_document` → 序列化 `upsert_shape` / `upsert_connector` / `update_text` / `remove_shape` —— **始终幂等变体**。
   5. `save_document`，然后在校验连接器前**重开**（`11_13` 教训）。
   6. `render_page` 确认。
3. **硬规则**（陷阱，来自日记）：
   - 勿调用 `connect_shapes`/`add_shape` 原始接口（MCP 中已不存在，仍须强调）。
   - 勿在无水印检查时自动批量导入模具（`11_5`）。
   - 若模型为 Claude/GPT 且用户提示纯中文，规划前内部译英（`11_5`、`11_9`）。
   - 承重连接器始终传胶合点；装饰性连线可用自动模式（`11_12`）。
4. **输出约定**：输出至 `outputs/<session>/`，预览由 `render_page` 返回 data URI（<120 KB）或 URL。
5. **`skills/visio/checklists/` 清单**：
   - `template-analysis.md` —— 六次调用及各返回。
   - `save-verify.md` —— 保存 → 重载 → 校验连接器。
   - `complex-template.md` —— 处理组内嵌套形状（`11_2` 缺口）。

**验证**：仅阅读 SKILL.md 的代理可在无额外内联指令下复现 `transformer_flowchart_prompt.txt` 运行。

### 阶段 6 — 提示与文档清理（0.5 天）

1. `prompts/`：保留 `idempotent_workflow_prompt.txt`、`transformer_flowchart_prompt.txt`（规范示例）。删除其余 13 份及更新摘要；已由 Prompt Agent + Skill 取代。
2. `docs/`：GBK 文件改名，两份匹配过程写并为一篇 `docs/ARCHITECTURE.md`。将 `CONNECTOR_VISIBILITY_FIX_SUMMARY.md` 内容并入 `visio_core/patches/README.md`。
3. `examples/`：缩至 2 个脚本 —— `use_library_system.py`（推荐）与 `idempotent_edit.py`（新建；替代四个临时 demo）。
4. `test/`：换为 `tests/` pytest 套件，覆盖五条日记证实的回归场景（§1.4）。

---

## 4. 风险与验证

| 风险 | 可能性 | 缓解 | 验证挂钩 |
|---|---|---|---|
| 合并工具破坏依赖旧名的未记录提示。 | 中 | 旧方法名保留一个版本的弃用别名；调用时打日志警告。 | CI 中对每条 `prompts/*.txt` 跑新工具列表。 |
| 显式 `apply_patches()` 导致连接器行为回退。 | 中高 | 在 `visio_mcp/server.py` 启动与 `apps/agent_os.py` 中调用 `apply_patches()`；增加未打补丁则失败的 pytest。 | 11/13 回归：三次 `upsert_connector` 建图，保存，重开，断言 `edge_count == 3` 且 PNG 中连接器可见。 |
| 库修剪删掉用户按名引用的模板。 | 低-中 | 修剪写 `removed.json` 清单；`recommend_template` 友好报错回退。 | 对比修剪前后 `template_library_lite.json`。 |
| MCP 迁移弄坏 AgentOS UI。 | 中 | 过渡期 `apps/agent_os.py` 仍直接包装 `visio_core`（不经 MCP）；MCP 场景测试通过后再切换。 | 冒烟：加载 `examples/try.vsdx`，改文本，保存，预览。 |
| 密钥已泄露于 git 历史。 | 确定（`my_os.py:21`）。 | 立即轮换 DeepSeek key；加 pre-commit 密钥扫描。 | 每提交跑 `gitleaks` 或 `trufflehog`。 |
| Web 预览仍弱于本机 Visio。 | 确定（`11_5`）。 | 文档列为非目标；预览 HTML 加「用本机 Visio 打开」链接。 | 人工验收。 |
| 结构感知编辑复现 11/7 格式损坏。 | 中 | 在 `save_document` 中加保存后 OOXML 校验，快速失败。 | `tests/test_save_validity.py`。 |
| 组内嵌套形状（11/2 缺口）仍不可见。 | 中 | `analyze_template` 递归遍历 `Shapes` 子项并返回 `groups` 树；在 skill 清单中说明。 | 对已知分组模板做单测（如 `11_2/animal.png` 来源 VSDX）。 |

### 4.1 重构完成定义（Definition of Done）

- LLM 可见工具数 ≤ 15。
- `git clone` → `pip install -r requirements.txt` → `python apps/agent_os.py` 在 <5 分钟内可跑，且无密钥提交。
- `pytest tests/` 全绿；覆盖 §1.4 全部五种回归场景。
- 11/13 连接器可见性流有显式测试通过。
- `skills/visio/SKILL.md` 自洽，新代理仅 skill + MCP（无系统提示）可生成可用的 `user_login_flow.vsdx`。

---

## 5. 假设与开放问题

列出以减少来回；仅当下游决策依赖时再解决。

1. **假设**：因底层 `vsdx` 包未上游合并，仍需要 `visio_system/patches/*`。证据：`diary/11_12`–`11_13`。通过禁用补丁跑当前测试套件验证 —— 若失败则保留补丁。
2. **假设**：SqliteDb 会话存储（`agno_sessions.db`）仅用于代理对话记忆，非 Visio 文档状态。「当前加载哪个文件」以 `dialog/` 中文档状态 JSON 为准。日记 `11_5`、`11_9` 一致。
3. **假设**：MCP 传输按 `diary/10_28` 为本地 stdio + 远程 sse。问题：是否有具体远程部署目标，还是 sse 仅为推测？若推测，阶段 4 先只发 stdio。
4. **假设**：`diary/11_12` 提到的商业/品牌目标延后。重构面向工程整洁的 MVP，非产品发布。
5. **开放**：`.state/logs/` 与 `.state/dialog/` 保留策略 —— 建议 30 天 TTL + 离线清理脚本；与用户调试习惯确认。
6. **开放**：`layout_diagnostic.py` / `quality_control.py` 是作为 `tools-offline` artifact 保留还是彻底删除。当前建议删除（日记零使用证据）；若需可从 git 历史恢复。
