---
name: visio-prompt-generation
description: Plan Visio edits using the 16-tool surface, then execute with MCP tools—do not dump the plan as the main user reply. Use when building or editing a diagram from requirements (same workflow as “prompt generation”, but execution-first).
---

# Visio 执行规划（面向 16 工具公开表面）

目标：
1. 理解用户需求（中英文）；
2. 从模板库中推荐最合适的模板；
3. **以内部分析为准**，按下方 Workflow E / B 顺序 **直接调用** 公开 16 工具完成建图或改图；
4. **不要把「可执行 Prompt」整条贴在对话里当作交付物**——用户要的是成图与预览链接，不是脚本说明书。

**对用户可见内容的默认**：
- 简短说明你在做什么（选了哪个模板、走了骨架复用还是从零搭建）；
- 工具结果中的预览链接、`render_page` 返回的 inline 图 + 交互链接（按 `visio-core-execution`）；
- 保存路径、门禁未命中时的诚实说明。

**仅当用户明确要求**「生成 prompt / 把步骤写出来 / 给我可复制脚本」时，才额外附上 Markdown 代码块形式的步骤草稿。

可用工具（任何其他名称都不存在）：
  recommend_template, search_templates, analyze_template,
  search_stencils, get_stencil,
  open_document, create_from_template, save_document, fit_page_to_drawing, render_page,
  upsert_shape, upsert_connector, update_text, remove_shape, edit_shape,
  insert_from_stencil

## 步骤 1：理解需求
- 识别关键词：流程图 / 架构图 / 组织图 / 网络图 / 时序图 / ……
- 判断复杂度、方向（横 / 纵）、拓扑（链 / 树 / 网 / 分层）。

## 步骤 2：智能检索模板
- 首选 `recommend_template(user_requirement, top_k=5)`：LLM 语义排序。
- 次选 `search_templates(keywords=[...])`：关键词确定时更快。
- 严禁用 `search_templates()` 空查询当"模板发现"——仅当用户要求"列出所有模板"时使用。
- 对 `recommend_template` 的结果，优先相信其中基于**用户原话核心词**通过门禁后的正式推荐；
- 若工具返回 `must_match_terms` 但 `recommendations` 为空，只出现 `alternatives` / `备选列表`，说明模板库里没有命中用户真实场景的模板：
  - 不要把这些备选项包装成“最佳推荐”；
  - 应明确告诉用户“目前没有严格命中核心词的模板”，必要时再请用户确认是否接受近似模板。
- 向用户展示每个候选时，务必包括：
  * 模板完整路径（必须是 `assets/templates/library/...` 下的真实路径）；
  * 综合评分与各维度评分；
  * 结构描述（拓扑 / 布局 / 连接）；
  * Markdown 预览链接 `[文件名](URL)`（仅 .vsdx，不得省略扩展名与空格）。

## 步骤 3：选定模板
- 用户已指定路径或文件名 → 使用该模板。
- 用户只说「帮我画 / 做一个 xxx 图」且未指定模板 → **自动采用排序第一的合规推荐**（或 `recommend_template` 返回的唯一首选），无需先把一长串候选脚本发给用户再等待确认。
- 仅在「多条候选都合理且门禁宽松」或用户表达「你帮我从这几个里挑」时，再用一两句话列出差异并请用户选；即便如此也不要用「整份 Prompt」代替工具调用。

## 步骤 4：深度分析（一次调用）
- 调用 `analyze_template(template_path)` 一次，获得：
  info、shapes、connections、positions、groups、topology。
- 绝不拆成 6 个旧的子工具调用——那些名称不存在。
- 重点记录：
  * 每个形状的 `id` / 文本 / 可能的 `node_key`；
  * 连接的 from/to 与 label；
  * groups 树（分组模板必备）；
  * topology 与 positions（用于输出布局建议）。
- 记录 `template_shape_count`（shapes 列表长度），用于决策：
  * 若模板形状数 ≥ 目标形状数的 60%，走 **Workflow E（骨架复用）**；
  * 若模板形状数 < 20% 或结构完全不符，走 **Workflow B（从零搭建）**。

## 步骤 5：按 Workflow E / B **执行**（本节的 Python 块是顺序备忘，不是默认要发给用户的正文）

以下代码块表示 **调用工具的先后顺序与参数意图**。正常情况下应在对话中 **逐项变为真实的工具调用**，而不是一次性粘贴全文。

### 默认骨架：Workflow E（模板骨架复用）

```python
# Step 1: 创建文档并立即重载
create_from_template("<template_name>", "outputs/<output>.vsdx")
open_document("outputs/<output>.vsdx")

# Step 2: 分析工作文件，获取实时形状清单
# analyze_template 返回 shapes 列表，每项含 id / text / position
analyze_template("outputs/<output>.vsdx")

# Step 3: 将角色映射到模板形状（同步完成文本替换 + key 绑定）
# 坐标由模板继承，无需手动设置 x/y
edit_shape("<id-from-analysis>", patch={"text": "客户提出业务申请", "node_key": "start"})
edit_shape("<id-from-analysis>", patch={"text": "验证身份信息",     "node_key": "verify_id"})
edit_shape("<id-from-analysis>", patch={"text": "信息是否通过验证？","node_key": "decision_pass"})
# ... 继续处理其他模板形状 ...

# Step 4: 删除多余的模板形状
# remove_shape 会先判断目标类型；若命中 connector，会自动分流到连接线删除
# 删除模板形状后，不要把“shape 已删除”当成连接线已经干净的同义词；
# 交付说明里必须明确写出相关连接器已清理，或说明已做 orphan 检查
remove_shape("<extra-shape-id>")

# Step 5: 仅为在模板中确认缺席的角色添加新形状
upsert_shape(node_key="new_node", text="新增节点", type="Rectangle", x=4.0, y=2.0)

# Step 6: 建立连接（所有端点必须已绑定 node_key）
upsert_connector(from_node_key="start",         to_node_key="verify_id",     from_port="Bottom", to_port="Top")
upsert_connector(from_node_key="verify_id",     to_node_key="decision_pass", from_port="Bottom", to_port="Top")
upsert_connector(from_node_key="decision_pass", to_node_key="reject",        label="不通过", from_port="Left", to_port="Right")
upsert_connector(from_node_key="decision_pass", to_node_key="process",       label="通过",   from_port="Bottom", to_port="Top")
# ...

# Step 7: 保存 → 重载 → 渲染（render_page 同时返回 fit_window 图片 + 交互预览链接）
save_document("outputs/<output>.vsdx")
open_document("outputs/<output>.vsdx")   # 硬约束，不得省略
render_page(page=0, scale=2.0, mode="url")  # 默认 url 模式，PNG 与 /api/visio/preview 一致
```

### 退化骨架：Workflow B（从零搭建，模板结构完全不符时）

```python
# Step 1: 创建文档并立即重载
create_from_template("<template_name>", "outputs/<output>.vsdx")
open_document("outputs/<output>.vsdx")

# Step 2: 先建形状（所有引用在后续 upsert_connector 前必须存在）
upsert_shape(node_key="n1", text="...", type="Rectangle", x=..., y=...)
upsert_shape(node_key="n2", text="...", type="Diamond",   x=..., y=...)
# ...

# Step 3: 再建连接
upsert_connector(from_node_key="n1", to_node_key="n2",
                 label="yes", router="right_angle",
                 from_port="Bottom", to_port="Top")
# ...

# Step 4: 统一样式 / 布局（可选）
edit_shape("n1", patch={"style": {"fill_color": "#CCE5FF"}})
edit_shape("n2", patch={"size":  {"width": 2.0, "height": 1.0}})

# Step 5: 保存 → 重载 → 渲染（render_page 同时返回 fit_window 图片 + 交互预览链接）
save_document("outputs/<output>.vsdx")
open_document("outputs/<output>.vsdx")   # 硬约束，不得省略
render_page(page=0, scale=2.0, mode="url")  # 默认 url 模式，PNG 与 /api/visio/preview 一致
```

要求：
- 每个形状的 `node_key` 唯一、与连接器引用一致；
- 所有连接仅引用已经绑定过 node_key 的形状（经 edit_shape 或 upsert_shape）；
- 连接器写完必须 `save_document` → `open_document`，否则后续校验会报 `SAVE_REQUIRES_RELOAD`；
- 几何 / 样式只通过 `edit_shape` 的 patch，不要找别的"位置/尺寸/颜色"工具；
- 文本只通过 `update_text` 或 `edit_shape(patch.text)`，不要找旧的 5 个文本变体。
- `edit_shape(patch.text)` / `update_text(new_text)` 一律按单行文本生成；不要在一个 patch 的文本里主动插入换行符。

**质量约束（必须在每次实际执行中满足）**：
- `upsert_connector` 的每个端点必须在同一执行序列中被 `edit_shape(patch.node_key)` 或 `upsert_shape` 赋予过 node_key；
- 不得把裸 `shape_id`（如 "254"）直接传给 `upsert_connector`；
- 最终图中的形状总数不得超过模板原有形状数 + 新增必要角色数（防止重复堆叠）。
- 任何模板清理 / `remove_shape` 场景都要把 connector cleanup 写进说明：默认假设旧连接线可能仍引用已删除 `Sheet.<id>`，直到清理或 orphan 检查明确确认。

## 步骤 6：交付（执行优先）
- **默认**：交付物是 **已写入的 `.vsdx` 路径** + **预览 Markdown 链接**（模板候选阶段对每个 `.vsdx` 候选仍应用 `[文件名](http://localhost:7777/api/visio/preview?path=...)` 说明布局）；完成编辑后按 `visio-core-execution` 提供输出文件的预览链接。
- 若已调用 `render_page`，把工具返回的 **inline 图片 + 交互预览链接** 整段原样转交，不得只贴图片或只贴链接。
- 除非用户明确要求，不主动 `render_page` 到聊天 UI——但涉及文件的回复必须具备可打开的预览链接。
- **禁止**把「完整可执行 Prompt」作为默认主要内容抛给用户；仅在用户索要可复制步骤时再附代码块。

## 预览链接格式（仅 .vsdx，强制）
  `[文件名](http://localhost:7777/api/visio/preview?path=<完整路径>)`

- 路径必须包含完整文件名和 `.vsdx` 扩展名，保留空格；
- 模板路径前缀 `assets/templates/library/...`，输出路径前缀 `outputs/...`；
- `.vssx` 严禁提供预览链接；
- 绝不使用 "预览链接: URL" 的裸 URL 写法——含空格的文件名会被 Markdown 截断；
- 该 URL 打开的页面默认 `fit_window` 视图（CSS 自动缩放至窗口可视区域），保证图像完整可见，绝不会被裁切。

## 质量清单
- 只用 16 个公开工具；
- 优先走 Workflow E（模板骨架复用），退化到 Workflow B（从零搭建）；
- 每个需要连接的形状都有稳定 node_key（来自 edit_shape 或 upsert_shape）；
- 连接器都有显式 from/to/label；
- 形状 → 连接 → 样式 → 保存 → 重载 → 渲染，次序不颠倒；
- 工具调用中的路径与真实模板 / 输出路径完全一致；
- **预览链接已附加**——交付物末尾必须有 `[文件名](http://localhost:7777/api/visio/preview?path=...)`，且其 path 与 `save_document` 写入的路径完全一致（含子目录与扩展名）。
