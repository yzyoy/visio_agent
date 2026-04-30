---
name: visio-prompt-generation
description: Generate an executable Visio Prompt strictly using the 15 public tools surface. Use when you need to plan the sequence of actions to build or edit a diagram.
---

# Prompt 生成流程（面向 15 工具公开表面）

目标：
1. 理解用户需求（中英文）；
2. 从模板库中推荐最合适的模板；
3. 输出一份可直接执行、只使用公开 15 工具的 Visio Prompt。

可用工具（任何其他名称都不存在）：
  recommend_template, search_templates, analyze_template,
  search_stencils, get_stencil,
  open_document, create_from_template, save_document, render_page,
  upsert_shape, upsert_connector, update_text, remove_shape, edit_shape,
  insert_from_stencil

## 步骤 1：理解需求
- 识别关键词：流程图 / 架构图 / 组织图 / 网络图 / 时序图 / ……
- 判断复杂度、方向（横 / 纵）、拓扑（链 / 树 / 网 / 分层）。

## 步骤 2：智能检索模板
- 首选 `recommend_template(user_requirement, top_k=5)`：LLM 语义排序。
- 次选 `search_templates(keywords=[...])`：关键词确定时更快。
- 严禁用 `search_templates()` 空查询当"模板发现"——仅当用户要求"列出所有模板"时使用。
- 向用户展示每个候选时，务必包括：
  * 模板完整路径（必须是 `assets/templates/library/...` 下的真实路径）；
  * 综合评分与各维度评分；
  * 结构描述（拓扑 / 布局 / 连接）；
  * Markdown 预览链接 `[文件名](URL)`（仅 .vsdx，不得省略扩展名与空格）。

## 步骤 3：用户选定模板
等待用户指定；如用户要求直接代选，取推荐第一条。

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

## 步骤 5：生成可执行 Prompt

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
# 若 remove_shape 返回 IS_CONNECTOR，说明是连接线，直接跳过
remove_shape("<extra-shape-id>")

# Step 5: 仅为在模板中确认缺席的角色添加新形状
upsert_shape(node_key="new_node", text="新增节点", type="Rectangle", x=4.0, y=2.0)

# Step 6: 建立连接（所有端点必须已绑定 node_key）
upsert_connector(from_node_key="start",         to_node_key="verify_id",     from_port="Bottom", to_port="Top")
upsert_connector(from_node_key="verify_id",     to_node_key="decision_pass", from_port="Bottom", to_port="Top")
upsert_connector(from_node_key="decision_pass", to_node_key="reject",        label="不通过", from_port="Left", to_port="Right")
upsert_connector(from_node_key="decision_pass", to_node_key="process",       label="通过",   from_port="Bottom", to_port="Top")
# ...

# Step 7: 保存 → 重载 → 渲染
save_document("outputs/<output>.vsdx")
open_document("outputs/<output>.vsdx")   # 硬约束，不得省略
render_page(page=0, scale=2.0, mode="data")
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

# Step 5: 保存 → 重载 → 渲染
save_document("outputs/<output>.vsdx")
open_document("outputs/<output>.vsdx")   # 硬约束，不得省略
render_page(page=0, scale=2.0, mode="data")
```

要求：
- 每个形状的 `node_key` 唯一、与连接器引用一致；
- 所有连接仅引用已经绑定过 node_key 的形状（经 edit_shape 或 upsert_shape）；
- 连接器写完必须 `save_document` → `open_document`，否则后续校验会报 `SAVE_REQUIRES_RELOAD`；
- 几何 / 样式只通过 `edit_shape` 的 patch，不要找别的"位置/尺寸/颜色"工具；
- 文本只通过 `update_text` 或 `edit_shape(patch.text)`，不要找旧的 5 个文本变体。

**质量约束（必须在每个生成的 Prompt 中满足）**：
- `upsert_connector` 的每个端点必须在同一 Prompt 中被 `edit_shape(patch.node_key)` 或 `upsert_shape` 赋予过 node_key；
- 不得把裸 `shape_id`（如 "254"）直接传给 `upsert_connector`；
- 生成的 Prompt 形状总数不得超过模板原有形状数 + 新增必要角色数（防止重复堆叠）。

## 步骤 6：交付
- 完整的可执行 Prompt 放在独立 Markdown 代码块中；
- 同时提供模板的预览链接（Markdown 格式）；
- 除非用户明确要求，不主动 `render_page` 到聊天 UI。

## 预览链接格式（仅 .vsdx）
  `[文件名](http://localhost:7777/api/visio/preview?path=<完整路径>)`

- 路径必须包含完整文件名和 `.vsdx` 扩展名，保留空格；
- 模板路径前缀 `assets/templates/library/...`，输出路径前缀 `outputs/...`；
- `.vssx` 严禁提供预览链接；
- 绝不使用 "预览链接: URL" 的裸 URL 写法——含空格的文件名会被 Markdown 截断。

## 质量清单
- 只用 15 个公开工具；
- 优先走 Workflow E（模板骨架复用），退化到 Workflow B（从零搭建）；
- 每个需要连接的形状都有稳定 node_key（来自 edit_shape 或 upsert_shape）；
- 连接器都有显式 from/to/label；
- 形状 → 连接 → 样式 → 保存 → 重载 → 渲染，次序不颠倒；
- 输出的 Prompt 里的路径与真实模板路径完全一致。
