---
name: noctis
description: 交互规划编码、数据整理、文档生成等工作的最小 Task、Unit 或 Work 层级，按项目注册表组合 Noctis 原生 Ars、Artifact Binding 与 support，生成并确认 ExecutionPlan 后交给 Noctis Exec。也可用 $noctis continue 路由到 Noctis Continue。仅在用户显式调用 Noctis、要求组合多个 Ars 或需要可恢复编排时使用；不创建或推进执行状态。
---

# Noctis

只规划和路由。不要实现业务、审查代码、运行测试、创建 `noctis.md` 或推进状态。

## 核心 Interface

统一使用：

- Work：范围较大的工作集合，包含多个通常串行的 Unit。
- Unit：一个需求的完整实现，对应一个 Workflow Template，可以跨项目。
- Track：Unit 内按项目或集成范围组织文件的可选分组；没有状态。
- Task：最小调度项，一次原子 Skill 执行；依赖图表达并行与汇合。
- Step：Task 内部动作，仅由 executor 维护。
- Artifact：Task 之间传递的语义产物引用；原生内容仍由产生它的 Ars 管理。

选择能表达需求的最小层级。只有经 Noctis/Exec 启动的单 Task 才进入可恢复生命周期；直接调用原子 Skill 仍保持独立。

## 路由

- `$noctis init`：读取 [initialize.md](references/initialize.md)。
- 新工作、调整计划或 `replan-required`：读取 [create-plan.md](references/create-plan.md)。
- `$noctis continue`：激活 `noctis-continue`，不要读取规划引用。

不要预读 executor、support 或其他 Noctis Skill 正文。显式调用 `$noctis $implement $code-review` 等可以提前加载这些 Skill，但不能省略计划确认或扩大授权。

## 交付计划

生成 ExecutionPlan v2，明确：

- Task、Unit 或 Work 层级和根记录；
- 目标、完成条件及 allowed/forbidden 授权；
- Work/Unit 依赖图、Track 和目标项目；
- 每个 Task 的 capability、executor、support、Artifact Binding 与记录路径。

一次性展示结构、执行顺序、并行组和副作用，提供 `A 启动`、`B 调整`、`C 取消`。只有用户无歧义确认后，才激活 `noctis-exec` 并传递完整计划。

计划不单独持久化；Exec 创建的 `noctis.md` 是恢复入口。范围、依赖、provider、完成条件或授权变化时重新规划，不让 Exec 暗自修订。
