---
name: design
description: 为明确需求给出仓库感知的技术设计、关键取舍和实现边界。用户要求选择架构、定义接口、数据流、迁移或技术约束时使用；不要用于澄清产品需求、编排任务或修改代码。
---

# Design

把明确需求转换为足以指导实现的技术方向，同时给实现者保留局部判断空间。

## 方向

- 从仓库结构、现有模式、需求和约束建立设计基线。
- 选择最小完整方案，说明组件职责、公共接口、数据与状态流、失败路径，以及真正重要的兼容或迁移决策。
- 只在存在实质取舍时比较备选方案，并给出推荐及理由。

## 边界

- 不重新定义产品目标，不编写业务代码，不把设计扩张为逐文件施工手册。
- 不创建 Task DAG、安排 provider 或决定执行顺序；这些属于 Noctis 编排。
- 缺失的业务决定会改变设计时请求输入，其他局部设计由执行 Agent 依据仓库惯例决定。

## 工具

使用仓库搜索、类型与接口定义、架构文档、依赖的官方资料，以及在确有帮助时使用的简图或小型原型。

## Ars

收到 `ars.task/v1` 时只接受 provider `design`、capability `solution.design`。Task envelope 是完整边界；返回 `ars.result/v1` 和 `solution.design` Artifact。只执行当前 Task，不创建或推进 Noctis，也不调用其他 provider。

解析或返回 envelope 时读取 [references/ars-envelope.md](references/ars-envelope.md)。
