---
name: ars-noctis
description: 保留 Ars-Noctis 的个人 Skill 路由入口并报告当前注册状态。用户显式要求查看或使用 Ars-Noctis 路由时使用；当前没有原子 Skill 注册，不要用于执行领域任务或持久任务编排。
---

# Ars-Noctis Router

只负责路由。当前原子 Skill 集合已清理，等待重新设计。

## 当前行为

- 被显式调用时，说明当前没有已注册的原子 Skill 或可执行路由。
- 不推断、读取或调用已经删除的旧 Skill。
- 不把通用 Agent 能力冒充为 Ars-Noctis 路由结果。
- 用户要重新设计路由或原子 Skill 时，以当前请求为独立设计任务处理。

## 注册约束

- 新原子 Skill 必须作为 `skills/<name>/` 下可独立安装的完整 Skill。
- 只有原子 Skill 的 interface 和职责经过确认后，才把它加入此路由器。
- 路由规则只负责选择和排序，不复制原子 Skill 的方法正文。
- 单个原子 Skill 能完成的任务不得仅为形式统一而拆分。

路由器不创建 Task DAG、状态文件、handoff envelope、subagent 或恢复协议。
