---
name: visio-core-execution
description: Core Visio operations, basics, constraints, Chinese instruction mapping, and standard workflows. Use when directly editing, saving, or rendering Visio documents using the 16 public tools.
---

# Visio 图表操作核心执行规则与工作流

## 1. 智能任务识别与全局显示策略

根据用户的输入，自动识别需要使用的功能：
- 翻译请求：'翻译', 'translate', '帮我翻译', '英文怎么说'
- Visio 操作：'创建图表', '修改形状', '列出模板', '预览图表'
- 建图 / 规划类需求：'推荐模板', '帮我设计流程图', '画流程图', '生成 prompt'（除非用户只要文本脚本，否则一律 **直接调用工具执行**，不把长篇「可执行 Prompt」当默认回复）
- 通用对话：其他所有对话和任务

**全局显示策略（最高优先级）**：
- 默认仅提供 vsdx 文件的预览链接，不在聊天UI渲染图片。
- 仅当用户明确要求在聊天UI显示时，才调用 `render_page` 并输出图片。
- **预览链接是强制项，绝对不能忘记。** 任何涉及 `.vsdx` 的回复都必须以 markdown 预览链接结尾：
  `[文件名](http://localhost:7777/api/visio/preview?path=<完整路径>)`。
  该链接打开的页面默认走 `fit_window` 渲染，能保证用户看到完整图像；裸图片或 `outputs/static/visio/...` 直链不能替代它。

## 2. Visio 图表操作基础（面向 16 工具公开表面）

核心概念：
- **模板 (Template)**：一个完整的 Visio 文件（.vsdx），含预设形状、连接与布局，是新图表的起点。模板库位于 `assets/templates/library/`。
- **形状库 (Stencil)**：形状集合（.vssx），可在任意图表中使用。形状库位于 `assets/templates/stencils/`。

公开工具表面（且仅此 16 个）：
1. `recommend_template(requirement, top_k=5)`
2. `search_templates(keywords=None)`
3. `analyze_template(path)`
4. `search_stencils(keywords=None)`
5. `get_stencil(name)`
6. `open_document(path)`
7. `create_from_template(template_name, output_path)`
8. `save_document(path=None)` (之后必须 open_document 再读连接器)
9. `fit_page_to_drawing(page=0, margin=0.5)` — 类似 Visio“适应绘图”，按内容平移并重设页面尺寸。
10. `render_page(page=0, scale=2.0, mode="data"|"url")` — 单次调用即返回 **inline 图片 + 交互预览链接**。两者必须原样转发给用户，预览链接不得删除。
11. `upsert_shape(node_key, text, type, x, y, width?, height?, ...)`
12. `upsert_connector(from_node_key, to_node_key, label?, router?, from_port?, to_port?)`
13. `update_text(selector, new_text)`
14. `remove_shape(selector, reconnect_mode?)` (默认保守删除关联连接线；仅在明确要求保留流向时才重连)
15. `edit_shape(shape_id, patch)` (patch: {text?, node_key?, position?, size?, style?})
16. `insert_from_stencil(master_name, stencil_name, x, y, text?)`

**`edit_shape` patch 完整 schema**：
```json
{
  "text":     "新文字（替换显示文本；必须保持单行，不要手动插入换行）",
  "node_key": "stable_key（为模板形状绑定稳定 key，供 upsert_connector 引用）",
  "position": {"x": 4.0, "y": 3.0, "relative": false},
  "size":     {"width": 2.0, "height": 0.8},
  "style":    {"line_width": 1.0, "line_color": "#000000", "fill_color": "#CCE5FF"}
}
```
任意子集均有效；`text` 和 `node_key` 是新增字段，专为模板骨架复用设计。

选择器 (selector) 约定：
- 优先 `node_key` —— 任何经 `upsert_shape` 或 `edit_shape(patch.node_key)` 绑定的形状都有稳定 key。
- 退化 `{match: {text, mode}}` —— 来自模板但未打 key 的形状。
- 永远不要依赖原始 `shape_id` 跨 save/reload。

## 3. 重要约束与最佳实践

**严格路径执行**：
- 绝对路径 / 相对路径一旦给出，必须原样使用；不做路径"纠正"或回退。
- 保存失败时抛出明确错误；禁止静默写到不同位置、临时目录或默认名。
- 模板只允许从 `assets/templates/library/` 的子目录搜索；绝不从 `outputs/` 推荐模板。

**幂等编辑纪律**：
- 形状 / 连接器一律走 `upsert_shape` / `upsert_connector`；同 key 反复调用不会重复。
- 几何 / 样式改动一律用 `edit_shape(shape_id, patch)`。
- `edit_shape(patch.text)` / `update_text(new_text)` 默认写单行文本；不要在同一个文本字段里自动插入换行，长句应优先改尺寸、换形状或简化措辞。
- 删除形状用 `remove_shape`，不要绕过它手动接边。
- 对“只删除指定内容”的需求，默认使用 `remove_shape(..., reconnect_mode="remove_connectors")`；
  只有当用户明确要求“删掉节点但保留上下游流向/主链不断”时，才允许
  `smart_reconnect`。
- 删除模板残留或局部改坏的旧形状后，默认假设仍可能存在引用已删除
  `Sheet.<id>` 的连接器；要依赖删除后的连接线清理，并在汇报时明确写出
  "相关连接线已清理"、"已列出残留连接线" 或 "已执行 orphan 检查"，不要只说
  "形状已删除"。

**范围化删除纪律（严格按用户点名执行）**：
- 先把“要删的对象”收敛成明确集合：仅删除文本、分组、节点或局部容器中
  与用户明确点名内容直接对应的元素。
- 标题栏、分隔框、共享箭头、公共主干连接线、仍服务于保留内容的父级容器，
  默认视为“保留对象”，除非用户明确要求一起删除。
- 连接线只有在以下情形才可删除：
  1. 连接线本身被用户点名；
  2. 连接线两端都在删除集合中；
  3. 连接线完全属于被删局部分支，且不会影响任何保留元素。
- 若连接线一端仍连接保留内容，默认保留；不要因为“语义相关”就顺带删掉共享线。
- 若无法确认某条线是否共享，先分析/核对再删；不确定时宁可保留或先向用户确认。

**模板骨架复用纪律（Workflow E 强制）**：
- 使用模板时，**绝不在执行 edit_shape / remove_shape 清理旧形状之前调用 upsert_shape**。
- `upsert_shape` 仅允许在步骤 7（analyze_template 已确认该角色在模板中不存在）后使用。
- 每个需要被 `upsert_connector` 引用的形状，都必须先用 `edit_shape(id, {node_key: "..."})` 绑定 key。

**保存 / 重载仪式（MCP 强制）**：
- `save_document(path)` 后必须紧跟 `open_document(path)` 才能再次写或读取连接器，否则会抛 `SAVE_REQUIRES_RELOAD`。

**分析纪律**：
- 结构分析一律调用 `analyze_template(path)` 一次，返回 info / shapes / connections / positions / groups / topology 六段。

**渲染 / 预览纪律（强制）**：
- 预览图片一律走 `render_page`，禁止自己拼接 `outputs/static/visio/...` 直链。
- `render_page` 内部走 `render_and_cache_preview`，与 `/api/visio/preview` 页面同源，PNG 字节完全一致，能保证 fit_window 缩放后图像完整不裁切。
- `render_page` 的返回值已经包含两段内容（inline 图片 + `[Open interactive preview](...)` 链接）；必须**整段原样**贴回给用户，绝不删掉链接、绝不只贴图片。
- 默认 `mode="url"`；仅在用户明确要求"离线 / 嵌入式 / 不联网"场景下才用 `mode="data"`，且小图（<120 KB）才内联，否则同样回退到 URL。

## 4. 中文指令理解

当用户使用中文指令时，请识别并调用对应的公开工具（绝不调用其他内部名称）：
- 打开/加载/读取 .vsdx       → `open_document`
- 从模板创建/复制模板         → `create_from_template`
- 保存/存储/写入             → `save_document`
- 渲染/预览/展示（.vsdx）    → `render_page`
- 搜索模板（按需求）          → `recommend_template`
- 列出/关键词检索模板         → `search_templates`
- 分析模板结构（一次性六合一）→ `analyze_template`
- 添加/新增/创建形状          → `upsert_shape`（仅当模板无此角色时）
- 连接/链接形状              → `upsert_connector`
- 修改/更新文本（已有模板形状）→ `edit_shape(id, {text: "...", node_key: "..."})` （推荐）或 `update_text`
- 删除/移除形状              → `remove_shape(..., reconnect_mode="remove_connectors")`（默认）
- 移动/改尺寸/改样式          → `edit_shape`
- 从形状库插入形状            → `insert_from_stencil`

## 5. 标准工作流

A) 在已有模板上原位改文字
  1) `recommend_template` (若用户尚未指定模板)
  2) `analyze_template`
  3) `open_document`
  4) `update_text`
  5) `save_document`
  6) `open_document` (强制再次打开才能读连接器)
  7) `render_page`

B) 从零搭建图表
  1) `recommend_template`
  2) `analyze_template`
  3) `create_from_template`
  4) `upsert_shape` (所有形状都必须先存在)
  5) `upsert_connector`
  6) `edit_shape` (调整样式/大小)
  7) `save_document`
  8) `open_document`
  9) `render_page`

C) 插入形状库中的形状
  1) `search_stencils`
  2) `get_stencil`
  3) `insert_from_stencil`

D) 删除节点并保留上下游流向（仅用户明确要求时）
  1) `remove_shape(..., reconnect_mode="smart_reconnect")`
  2) `save_document` + `open_document`
  3) `analyze_template` (核对 connections；若是模板清理场景，明确确认连接线清理结果)

E) **模板骨架复用（DEFAULT — 用户选定模板后必须走此流程）**
  1) `recommend_template` → 用户未指定模板时 **默认取第一条合规推荐并继续**，无需先把整份执行脚本发给用户；仅在用户明确要求挑选时再停顿确认
  2) `analyze_template(template_path)` — 了解原始模板结构
  3) `create_from_template(template, "outputs/<name>.vsdx")`
  4) `open_document("outputs/<name>.vsdx")`
  5) `analyze_template("outputs/<name>.vsdx")` — 获取工作文件的**实时形状清单**（含 shape_id）
  6) 将每个需要的角色映射到模板中已有的 shape_id：
     `edit_shape(shape_id, {"text": "目标文字", "node_key": "stable_key"})`
     — 在此步骤中同时完成文本替换和 key 绑定，坐标由模板继承，无需手动填写 (x, y)
  7) 对每个多余的模板形状：`remove_shape(shape_id, reconnect_mode="remove_connectors")`
     — 仅删除明确属于目标删除范围的形状；共享标题、公共骨架、仍服务于保留内容的连接线不得顺带删除；
       若该 ID 是连接线，会自动分流到 connector 删除；对用户汇报时必须同时说明相关连接线已清理，或说明已做 orphan 检查
  8) 仅当步骤 5 确认模板中**没有**对应角色时：
     `upsert_shape(node_key, text, type, x, y)`
  9) `upsert_connector(from_node_key, to_node_key, label?, from_port?, to_port?)`
     — 所有端点必须已在步骤 6 或 8 中绑定了 node_key
  10) `save_document("outputs/<name>.vsdx")`
  11) `open_document("outputs/<name>.vsdx")` — 强制重载（MCP 约束）
  12) `render_page(page=0, scale=2.0, mode="url")` — 把返回的 **inline 图片 + 交互预览链接** 整段贴回给用户；链接是默认 fit_window 视图的唯一可靠入口，绝不能省略。
