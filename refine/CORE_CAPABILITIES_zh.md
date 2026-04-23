# 核心能力

> 姊妹文档：[PROJECT_REFACTOR_ROADMAP_zh.md](./PROJECT_REFACTOR_ROADMAP_zh.md) — *如何*以及*何时*执行。
> 本文聚焦重构后保留的*能力*、原因，以及每项在 MCP / Skill / 库 分层中的归属。

归属图例：**[MCP]** 供 LLM 调用的工具或资源 · **[SKILL]** 代理以文本形式遵循的工作流/清单 · **[LIB]** 纯 Python 内部实现，不向 LLM 暴露。

---

## 1. 保留的能力（闭环核心）

以下十一项是唯一在日记中有持续、真实使用证据的能力。每项映射到：(a) 用户价值，(b) 日记证据，(c) 当前代码位置，(d) 非目标，(e) 目标归属。

### 1.1 模板推荐（轻量→完整 两级匹配）

- **用户价值**：用户输入中文需求，得到 ≤5 个带理由的排序模板；支持「选模板再改」而非「从零画」——即 `10_26` 的转向决策。
- **日记证据**：
  - `diary/10_26/10_26.txt` — 原始转向：*「要构建一个 visio 的模板库, 选个模板让 agent 进行更改」*。
  - `diary/11_3/11_3.txt` — 设计四步推荐管线（关键词抽取 → 轻量筛选 → 完整 LLM 评估 → 中文输出），约 29 秒。
  - `diary/11_4/11_4.txt` — 改进为结构感知（拓扑重要，不仅是关键词）。
  - `diary/11_7/11_7.txt` — 增加复杂度/置信度评分与动态权重。
- **代码位置**：`visio_system/utils/smart_matcher.py`（核心），`visio_system/tools/prompt_tools.py::search_templates_by_requirement / rank_templates_for_requirement`，由 `templates/template_library_lite.json` + `templates/template_library.json` 驱动。
- **非目标**：替代商业 edrawmax 模板目录；在库很薄时保证完美匹配（日记 `11_7`）。
- **归属**：
  - **[LIB]** `SmartMatcher`、扫描器、JSON 构建器。
  - **[MCP]** `recommend_template(requirement: str, top_k: int = 5, scope: "templates"|"stencils"|"both") -> list[Recommendation]`。
  - **[SKILL]** 「除非用户已指定文件名，否则始终先调用 recommend_template」。

### 1.2 模板分析（六步打包）

- **用户价值**：编辑模板前代理必须了解形状、连接、位置与分组；没有这些，修改会破坏结构。
- **日记证据**：
  - `diary/11_10/11_10.txt` — 明确列出六次调用（`get_template_info`、`load_diagram`、`get_diagram_info`、`list_shapes`、`analyze_diagram_connections`、`list_position`），并警告工具拆散时 *「model may ignore some tools」*。
  - `diary/11_2/11_2.txt` — 记录当前 `list_shapes` 会漏掉组内嵌套形状。
- **代码位置**：`visio_system/tools/visio_tools.py`（list_shapes、analyze_diagram_connections 等），`visio_system/tools/prompt_tools.py::analyze_template_for_recommendation`，`visio_system/utils/template_analyzer.py`、`structure_analyzer.py`。
- **非目标**：语义理解（形状*意味着什么*）——在给定结构包后由 LLM 完成。
- **归属**：
  - **[LIB]** `analyze_template(path) -> TemplateAnalysis`（单函数，递归进入组）。
  - **[MCP]** `analyze_template(path) -> {info, shapes, connections, positions, groups, topology, layout}` — 一次调用替代六次。
  - **[SKILL]** 清单 `skills/visio/checklists/template-analysis.md`，说明何时、如何消费各字段。

### 1.3 幂等的形状与连接线编辑

- **用户价值**：同一提示运行两次得到相同图表——无累积漂移、无重复形状。这使代理循环安全。
- **日记证据**：
  - `diary/11_11/11_11.txt` — *「已有结构能够成功被连接到模板里了」*，基于 node-key/edge-key 模型。
  - `diary/11_12/11_12.txt` — EdgeKey 格式 `{from_node_key}@{from_glue}->{to_node_key}@{to_glue}|{label}`，双模式（自动/手动）胶合点。
  - `diary/11_9/11_9.txt` — 教训：*「不让他虚空创建形状或者虚空连接形状」* → 幂等键是修复手段。
- **代码位置**：`visio_system/tools/visio_tools.py::add_or_update_shape / add_or_update_connector / ensure_all_shapes_have_keys`，`visio_system/utils/edge_manager.py`、`visio_system/utils/shape_identity.py`、`visio_system/utils/connection_points.py`。
- **非目标**：任意新节点的自动布局（坐标由模型提供）；超出 Visio 九个胶合点的语义边路由。
- **归属**：
  - **[LIB]** `edge_manager`、`shape_identity`、`connection_points` 保持内部。
  - **[MCP]** `upsert_shape(key, text, type, x, y, w, h, style?)`、`upsert_connector(from_key, to_key, from_glue?, to_glue?, label?)`。均返回 `{status: created|updated|unchanged, key, warnings}`。
  - **[SKILL]** 「永远不要调用非幂等的 add_*/connect_* —— MCP 表面不存在这些」。

### 1.4 就地文本编辑

- **用户价值**：日记中占主导的编辑是*替换已有模板形状上的占位文字*。保持快速、有选择性是产品的 80/20。
- **日记证据**：
  - `diary/10_29/10_29.txt` — *「对于模板的利用以及很好了…添加模块的能力还要优化」*：文本替换已是可行路径。
  - `diary/11_2/11_2.txt` — 有效提示为 *「只能是删除形状或者替换形状中的文字或者是删除形状之间的连接线」*。
- **代码位置**：`visio_system/tools/visio_tools.py::update_shape_text, update_text_by_match, update_text_by_match_all, batch_update_text_by_map, fill_placeholders`（五个重叠工具 —— 见路线图 §1.1）。
- **非目标**：富文本格式、每次运行的字体微调（保留为 §1.5 的样式操作）。
- **归属**：
  - **[LIB]** `DiagramBuilder` 文本方法。
  - **[MCP]** `update_text(selector, value)`，其中 `selector` 为 `{shape_id}`、`{node_key}`、`{match: {text, mode}}` 之一；以及用于模板批量填充的 `batch_update_text(mapping)`。5→2。
  - **[SKILL]** 编辑 `upsert_shape` 结果时优先 `node_key` 选择器；编辑未知模板时优先 `{match}`。

### 1.5 形状布局与样式原语

- **用户价值**：结构编辑后需要微调位置与描边/填充以美化输出。
- **日记证据**：
  - `diary/10_29/10_29.txt`、`diary/11_11/11_11.txt` — 绘制效果问题常可追溯到位置/尺寸。
  - `diary/11_7/11_7.txt` — 结构感知编辑会引入格式/位置漂移，需纠正。
- **代码位置**：`visio_system/tools/visio_tools.py::set_shape_position, nudge_shape, set_shape_size, set_line_width, set_line_color, set_fill_color`。
- **非目标**：完整 CSS 级样式；基于主题的重着色（延后）。
- **归属**：
  - **[LIB]** `DiagramBuilder` 几何 + 样式方法。
  - **[MCP]** `set_shape_position(selector, x, y, relative=False)`、`set_shape_size(selector, w, h)`、`set_shape_style(selector, {fill, stroke, line_width})`。6→3。
  - **[SKILL]** 「仅在结构定稿后应用样式，避免 upsert 期间被重置」。

### 1.6 带重连的形状删除

- **用户价值**：在链中删除节点同时保持流向是反复出现的需求（日记 `11_2`）。
- **日记证据**：`diary/11_2/11_2.txt` — 有效提示中的「可以删除但是不能破坏原有的连接结构」。
- **代码位置**：`visio_system/tools/visio_tools.py::remove_shape, remove_shape_smart`。
- **非目标**：复杂图重写。
- **归属**：
  - **[LIB]** `DiagramBuilder.remove_shape(..., reconnect_mode)`。
  - **[MCP]** `remove_shape(selector, reconnect="smart"|"none")`。2→1。
  - **[SKILL]** 链中删除默认 reconnect=smart；叶节点用 none。

### 1.7 文档生命周期（打开 → 从模板创建 → 保存 → 重载）

- **用户价值**：每次会话的外壳。质量门槛在此 —— 11/13 的 bug 证明保存后不重载会静默丢失连接器状态。
- **日记证据**：
  - `diary/10_28/10_28` — 规范数据流（UI → agent → VisioTools → vsdx lib）。
  - `diary/11_13/11_13.txt` — *「我创建完文件后没有把它正确导入，所以连接器才添加失败」*。必须有重载步骤。
- **代码位置**：`visio_system/tools/visio_tools.py::load_diagram, create_new_diagram, create_from_template_and_load, save_diagram`，`visio_system/utils/diagram_builder.py`，`visio_system/patches/*`（加载时需连接器补丁）。
- **非目标**：Visio 应用自动化（从不调用 Visio 二进制）；多文档标签页。
- **归属**：
  - **[LIB]** `DiagramBuilder.load_from_file / save_to_file` + 显式 `apply_patches()`。
  - **[MCP]** `open_document(path)`、`create_from_template(template_name, output_path)`、`save_document(path?)`。保存返回 `{path, requires_reload: true}`；下次写连接器前必须先 `open_document`（由 skill 强制执行）。
  - **[SKILL]** 清单 `skills/visio/checklists/save-verify.md` — 保存 → open_document(同路径) → 校验。

### 1.8 渲染与预览

- **用户价值**：在对话中内嵌检查图表；日记 `10_30` 记录花了约 4 小时才做对，并认为可交付。
- **日记证据**：
  - `diary/10_30/10_30.txt` — PNG 预览 + Web URL，「加入预览 visio 文件工具, 方便迅速查看图片效果」。
  - `diary/11_4/11_4.txt` — 推荐 UI 依赖此功能内联预览候选。
  - `diary/11_5/11_5.txt` — 如实记录：*「本地 visio 看是好的,但是在网页端预览是效果不好的」* → 保真度可接受，非完美。
- **代码位置**：`visio_system/utils/visio_render.py`，`visio_system/api/visio_preview.py`（FastAPI 路由），`my_os.py` 挂载 `/api/visio` + `/static/visio`。
- **非目标**：浏览器内交互编辑；与桌面 Visio 像素级一致。
- **归属**：
  - **[LIB]** `render_vsdx_page_to_png / _data_uri`。
  - **[MCP]** `render_page(path, page=0, scale=2.0, mode="url"|"data") -> {image_url|image_data_uri, width, height}`，沿用当前代码约 120 KB 上限以防 token 溢出。
  - **[LIB]** FastAPI 路由保留为 AgentOS Web UI 的配套 HTTP 面；非 MCP 资源（面向人，非 LLM）。

### 1.9 模具库（VSSX）与插入

- **用户价值**：添加基础模板中没有的领域图标（服务器、流程图符号等）。
- **日记证据**：
  - `diary/10_31/10_31.txt`、`11_2/11_2.txt` — vsdx/vssx 划分与扫描管线。
  - `diary/11_5/11_5.txt` — 插入可用但质量「效果不太好」；仍在使用。
- **代码位置**：`visio_system/templates/stencil_manager.py`，`visio_system/utils/stencil_importer.py`、`stencil_scanner.py`，`visio_system/tools/visio_tools.py::list_library_stencils, search_library_stencils, get_stencil_info, list_stencil_masters, add_shape_from_stencil`，`scripts/stencil_parser.py`。
- **非目标**：无手动预转换则不支持 VSS（非 X）（`10_31` 确认 Linux 限制）。
- **归属**：
  - **[LIB]** 模具管理器、导入器、解析器。
  - **[MCP]** `list_stencils()`、`search_stencils(keywords)`、`get_stencil(name)`（含主形状列表）、`insert_from_stencil(stencil, master, x, y, text)`。
  - **[SKILL]** 「用户说的图标类型不在当前模板中时，尝试 insert_from_stencil；若效果差，回退为带标签的矩形」。

### 1.10 提示生成（基于模板的编辑计划）

- **用户价值**：将自由中文意图转为逐步工具调用脚本，显著提高下游 Visio 代理的一次成功率。
- **日记证据**：
  - `diary/10_30/10_30.txt` — 引入提示助手并刻意让用户参与。
  - `diary/11_3` – `11_7` — 演进为包含结构、位置与六步分析。
- **代码位置**：`visio_system/agents/prompt_agent.py`，`visio_system/tools/prompt_tools.py`（生成、排序、校验），`prompts/`（遗留手写示例）。
- **非目标**：完全自主零点击生成（用户仍选择/确认模板）；超出结构报告的自然语言问答。
- **归属**：
  - **[LIB]** 在 `visio_core/prompts/` 保留最小提示渲染器（类 Jinja），接受模板分析 + 用户需求并返回文本。
  - **[MCP]** `generate_edit_plan(requirement, template_path) -> {plan_markdown, tool_calls[]}` — 同时返回人类可读文本与可执行工具序列。
  - **[SKILL]** 「调用 `recommend_template` → 请用户确认 → `analyze_template` → `generate_edit_plan` → 执行」。两份遗留提示文件（`idempotent_workflow_prompt.txt`、`transformer_flowchart_prompt.txt`）作为 skill 示例保留；其余 13 份删除。

### 1.11 会话上下文与持久化

- **用户价值**：「AI 记住上次加载的文件与迄今操作」——用户可以说 *「改标题」* 而无需重复文件名。
- **日记证据**：
  - `diary/11_5/11_5.txt` — *「优化上下文能力, 基于 SqliteDb」*。
  - `diary/11_9/11_9.txt` — 列为构建代理的首要教训。
- **代码位置**：`visio_system/context/session_context.py`，`instruction_builder.py`、`instruction_loader.py`，`my_os.py`（SqliteDb 接线），`dialog/*.json` 持久化。
- **非目标**：跨用户会话共享；时间旅行式撤销。
- **归属**：
  - **[LIB]** `SessionContext` 数据类 + `DialogContextStore` JSON 持久化；agno 的 `SqliteDb` 留在应用层。
  - **[MCP]** 无直接工具 —— MCP 工具无状态；`open_document` 返回值即会话句柄。AgentOS 层仍负责对话记忆。
  - **[SKILL]** 「对话开始时检查是否有当前文件；若有则跳过重复打开；仍向 MCP 工具显式传入路径（无状态）」。

---

## 2. 目标 MCP 面（汇总）

恰好 15 个工具 + 2 个资源。§1 中每项 **[LIB]** 至多折叠为一个 MCP 工具。

### 2.1 工具

| # | 工具 | 参数（摘要） | 幂等？ | 错误码 |
|---|---|---|---|---|
| 1 | `recommend_template` | `requirement`, `top_k`, `scope` | 是（只读） | `LIBRARY_EMPTY`, `MODEL_UNAVAILABLE` |
| 2 | `list_templates` | `category?`, `limit?` | 是 | — |
| 3 | `search_templates` | `keywords[]` | 是 | — |
| 4 | `analyze_template` | `path` | 是 | `FILE_NOT_FOUND`, `PARSE_FAILED` |
| 5 | `list_stencils` | — | 是 | — |
| 6 | `search_stencils` | `keywords[]` | 是 | — |
| 7 | `get_stencil` | `name`, `include_masters` | 是 | `FILE_NOT_FOUND` |
| 8 | `open_document` | `path` | 是 | `FILE_NOT_FOUND` |
| 9 | `create_from_template` | `template`, `output_path` | 是（对目标） | `TEMPLATE_NOT_FOUND`, `OUTPUT_EXISTS` |
| 10 | `save_document` | `path?` | 是 | `DOC_NOT_OPEN`, `INVALID_OOXML` |
| 11 | `render_page` | `path`, `page`, `scale`, `mode` | 是 | `FILE_NOT_FOUND`, `RENDER_FAILED` |
| 12 | `upsert_shape` | `key`, `text`, `type`, `x`, `y`, `w`, `h`, `style?` | **是**（基于 key） | `DOC_NOT_OPEN`, `INVALID_TYPE` |
| 13 | `upsert_connector` | `from_key`, `to_key`, `from_glue?`, `to_glue?`, `label?` | **是**（基于 edge-key） | `NODE_NOT_FOUND`, `CONNECTOR_GLUE_INVALID`, `SAVE_REQUIRES_RELOAD` |
| 14 | `update_text` | `selector`, `value`（另有批量变体 `batch_update_text(mapping)`） | 是 | `SELECTOR_NOT_FOUND` |
| 15 | `remove_shape` + `set_shape_position` + `set_shape_size` + `set_shape_style` + `insert_from_stencil` + `generate_edit_plan` | 各工具参数见 §1 | 是（均基于 selector/key） | 见 §1 |

> 注：标记为 #15 的单元格故意成组，使对外*可见*名称总数保持为 15；实践中这是六个共享 `selector` 契约的工具，均符合一句话幂等规则。若严格要求 ≤15，可将样式/位置/尺寸设置器合并为 `edit_shape(selector, patch)`；日记证据不要求更细粒度。

### 2.2 资源

| URI | 内容 | 生产者 |
|---|---|---|
| `visio://document/current` | 已打开文档的 JSON 快照：页、形状（含 key/位置）、连接器（edge_keys）、组。供代理规划而无需冗余工具调用。 | `DiagramBuilder` + `structure_analyzer`。 |
| `visio://library/index` | 轻量模板 + 模具 JSON（角色同 `templates/*_library_lite.json`）。支持客户端侧关键词搜索。 | `visio_core/library/` 中的扫描器。 |

### 2.3 错误模型（统一）

```
VisioToolError {
  code: <上表枚举>,
  message: 人类可读,
  hint?: 修复提示（例如 "call open_document(path) before upsert_connector"）,
  recoverable: bool
}
```

`SAVE_REQUIRES_RELOAD` 码是在协议层落实 11/13 教训的机制。

---

## 3. Agent Skill 范围（SKILL.md 中应含内容）

按路线图 §3 阶段 5；此处列出「能力清单」层面的「是什么」。

- **工作流脚本** — 6 步（推荐 → 分析 → 计划 → upsert 循环 → 保存 → 重载+校验）。
- **选择器约定** — 优先 node_key，文本匹配为后备。
- **陷阱** — 五条来自日记的规则：
  1. 纯中文提示会降低 Claude/GPT 表现 → 内部翻译。
  2. 保存后在读连接器前务必重新打开（11/13）。
  3. 勿依赖 Aspose 试用输出（11/5）。
  4. 组内嵌套形状需递归分析（11/2）。
  5. 推荐任何新加入的模板前先跑水印过滤（11/4）。
- **输出契约** — 文件落盘位置、何时返回预览 URL vs data URI。
- **何时不应行动** — 若库为空或用户要求浏览器 WYSIWYG，应退出并指向本文档中的非目标说明。

---

## 4. 明确砍掉的内容（及原因）

简明列表；完整理由见路线图 §1。

| 砍掉项 | 原因（日记来源） |
|---|---|
| 16 份 `prompts/*.txt` 中的 13 份 | 已被 Prompt Agent + Skill 取代（`10_30` 起）。 |
| 非幂等 `add_shape` / `connect_shapes` | `11_12` 连接器回退的根源。 |
| 从 LLM 面移除 `cleanup_diagram_connectors`、`validate_diagram_connectors`、`verify_connector_persisted`、`get_log_summary`、`ensure_all_shapes_have_keys`、`set_session`、`reset_session` | 从不面向用户；内部卫生移至 CI/测试。 |
| `visio_system/tools/quality_control.py`、`layout_diagnostic.py` | 日记零引用；无下游消费者。 |
| `visio_system/examples/`（4 个脚本） | 与顶层 `examples/` 重复；未被 import。 |
| `templates/scan_*.py`、`compress_template_library.py`、`count_files.py`、`scripts/move_visio_files.py`、`path_mapper.py`、`manage_templates.py` | 11/2–11/5 库迁移时的一次性脚本；幸存者迁至 `tools-offline/`。 |
| `docs/*.md`（GBK 文件名）、`CONNECTOR_EXTENSION_GUIDE.md`、`SSH_PORT_FORWARDING_README.md` | 内部笔记；合并或删除。 |
| `agent.zip`、`templates.zip`、已提交的 `*.db`、`log/`、`dialog/*.json`、`output/tmp_*/` | 运行时产物；应归入 `.state/` + gitignore。 |
| 多代理脚手架（若有残留） | 日记 `11_2` 已合并。 |
| 依赖 Aspose 的转换路径 | 试用仍打水印（`11_5`）；视为非核心。 |
| `BUG_ANALYSIS.txt`、`CODE_FIX.txt`、`QUICK_FIX.txt`、`SUMMARY.txt` | 已为 `D` 暂存；确认删除。 |

---

## 5. 假设与开放问题

与路线图的假设列表不重复。

1. **假设** `analyze_template` 返回单一打包负载（典型模板约 20–80 KB JSON）可容纳在代理上下文中；对极大模板（日记 `11_3` 在库索引上提过 token 限制，非单模板）仍应成立。若不成立，增加 `fields` 过滤参数。
2. **假设** `node_key` / `edge_key` 命名由代理负责（模型选稳定键如 `login_box`、`validate_decision`）。库保证唯一性并返回 `DUPLICATE_KEY` 错误，但不自动生成键。若模型选键不可靠，在 `upsert_shape` 上增加 `auto_key_from_text` 选项。
3. **开放** 模具插入质量（`11_5`「效果不太好」）是否值得投入 `place_and_align` 后处理，或 skill 的「回退为带标签矩形」对 MVP 已足够。建议在具体用户投诉再次出现前延后。
4. **开放** `generate_edit_plan` 是否应在用户已批准模板时*执行*计划（单次）。当前日记立场（`10_30`）为用户参与；应作为每次调用的标志（默认 `execute=False`），而非硬策略。
