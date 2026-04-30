---
name: visio-requirement-analysis
description: Analyze user requirements for Visio diagrams, extract keywords, identify chart types, complexity, and structural characteristics. Use when the user asks to draw or create a diagram to understand their needs before selecting a template.
---

# 关键词提取与需求分析 (Keyword Extraction & Requirement Analysis)

请深入分析用户的绘图或建图需求，提取关键词并理解需求的具体特征。

## 第一步：理解需求特征
分析并识别以下信息：
1. **图表类型**：流程图、架构图、网络图、组织图、时序图等
2. **规模估算**：
   - 简单（3-5个元素/节点）
   - 中等（6-15个元素/节点）
   - 复杂（16-30个元素/节点）
   - 大型（30+个元素/节点）
3. **架构特征**：
   - 层次结构（如：三层架构、多层级组织）
   - 线性流程（如：顺序流程、管道）
   - 网状结构（如：网络拓扑、关系网）
   - 矩阵结构（如：多维度对比、跨职能团队）
4. **具体场景**：业务流程、技术架构、组织管理、网络设计等

## 第二步：提取关键词和结构特征
基于需求特征，提取5-10个最相关的英文关键词，包括：
- 核心术语（技术/业务词汇）
- 图表类型关键词
- 规模相关词（simple/complex/detailed/comprehensive等）
- 领域特定词汇

同时识别图表的结构特征：
- **拓扑类型**：分析图表的连接结构（hierarchical_tree=树状层次, linear_chain=线性链, network=网状, star=星型, hybrid=混合型, isolated_nodes=独立节点）
- **布局方向**：判断主要布局方向（vertical=垂直, horizontal=水平, mixed=混合）
- **连接类型**：识别连接方式（sequential=顺序连接, branching=分支连接, bidirectional=双向连接, mesh=网状互联, star_topology=星型连接）

## 输出格式要求：
请按以下JSON格式返回（只返回JSON，不要其他内容）：

```json
{
  "keywords": "keyword1, keyword2, keyword3, ...",
  "chart_type": "图表类型（英文）",
  "complexity": "simple/medium/complex/large",
  "estimated_shapes": "预估需要的形状数量范围",
  "architecture_pattern": "架构模式描述（英文）",
  "specific_requirements": ["需求要点1", "需求要点2", "..."],
  "topology_type": "拓扑类型（从以下选择：hierarchical_tree, linear_chain, network, star, hybrid, isolated_nodes）",
  "layout_direction": "布局方向（从以下选择：vertical, horizontal, mixed）",
  "connection_type": "连接类型（从以下选择：sequential, branching, bidirectional, mesh, star_topology）"
}
```

## 关于 template_shape_count 的使用说明

分析完成后，规划器将 `estimated_shapes` 与模板评分阶段返回的 `template_shapes_count` 进行对比：
- 若模板形状数 ≥ `estimated_shapes` 下限的 60%，推荐 **Workflow E（骨架复用）**；
- 若模板形状数 < 20%，推荐 **Workflow B（从零搭建）**。

在 JSON 输出中确保 `estimated_shapes` 是一个清晰的数字范围（如 "8-12"），以便准确做出此判断。

## 关于 estimated_shapes 字段的特别说明：

**返回格式**：应根据用户输入的详细程度返回不同精度的范围估算

1. **简短输入**（如"画个流程图"）：
   - 返回宽泛范围，例如："5-20"
   - 表示不确定规模，提供较大的灵活空间

2. **适中输入**（如"用户登录的流程图"）：
   - 返回中等范围，例如："8-15"
   - 基于常见场景进行合理估算

3. **详细输入**（如"创建包含用户、认证服务器、数据库、缓存的登录流程图，需要展示完整的认证流程和异常处理"）：
   - 返回精确范围，例如："12-15" 或 "18-22"
   - 基于明确提及的组件和流程进行精确计算

**计算方法**：
- 明确提及的组件/步骤：每个计数1个形状
- 连接关系：如有N个组件，通常需要N-1到N个连接器（但不单独计数）
- 决策点、异常处理等：每个额外计数1-2个形状
- 注释、标题等辅助元素：酌情增加1-3个形状
