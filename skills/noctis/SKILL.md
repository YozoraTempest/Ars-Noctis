---
name: noctis
description: 创建、扩展、推进或从 Git clone 恢复协议无关的持久 Task DAG。用户明确提到 Noctis、要求跨会话或跨机器继续、需要有依赖的可恢复任务，或在运行中动态加入新 Task 时使用；不要为当前会话可直接完成的单一任务引入，也不要用它发现或执行特定 Agent Skill 协议。
---

# Noctis

把 Noctis 当作 Git 支撑的持久 Task DAG，不当作 Agent 宿主。Core 只校验 executor、opaque request/output、requirement、DAG 和状态转换；adapter 负责领域发现、执行与业务证据。

## 使用边界

- 只为跨会话或跨机器恢复、真实 Task 依赖或运行中扩展创建 Run；当前会话能直接完成时不要使用 Noctis。
- Task 表达独立结果或恢复边界，不按 `spec`、`design`、`test` 等角色机械拆分。设计、局部诊断和相称检查通常留在当前 Task 内。
- 保持 DAG 最小。同一昂贵验证只执行一次；同一范围内发现的工作继续由当前 executor 完成，独立的新结果才追加 Task。
- executor 只完成领取的 Task。Noctis 不扫描 Skill、不解释领域数据、不执行 executor，也不提交或推送。

## 计划与确认

1. 让调用方或 adapter 提供 executor 快照，创建只含必要 Task、依赖、opaque request 和 requirement 的 `noctis.plan/v1`。
2. 运行 `plan-check --preview`，在调用 `run-create` 前展示以下内容，并等待用户明确确认：

```text
目标：
Task：
依赖：
新增 requirement：
高成本操作：
```

用户选择 Noctis、确认工作方向或授权前序讨论，不等于确认尚未展示的 Plan。确认后运行 `run-create` 并提交初始 checkpoint。

## 执行与恢复

- 开始或继续时先调用 `run-show`。已有 Run 只展示当前状态、下一 Task 和新增 requirement，不重新规划或重复确认已有 Plan。
- 用 `task-claim` 领取 ready Task，把 Claim 交给对应 executor，再用 `task-finish` 接收 `noctis.result/v1`。
- 创建时提交 Run 目录；后续只提交 CLI 返回的 `checkpoint_required` 路径。后继 Task 必须等前置 Result/Event 成为 Git checkpoint。
- `failed`、`blocked` 或 `input-required` 时报告事实。只有出现新输入、修复或证据后才重试，不重复相同执行。
- 新 clone 或明确丢弃本机现场时调用 `recover`；`working` 是本机 claim，不是持久状态。

## 扩展与控制

- 用 `noctis.extension/v1` 追加独立结果，不修改 Plan 或历史 Task。扩大目标、一次加入多个独立结果或引入新 requirement 时，展示增量并等待确认；已确认目标内的单个细化 Task 展示增量后即可继续。
- `grant` 和 `revoke` 只记录 opaque requirement。新机器必须重新激活授权；重试或取消已领取且带 requirement 的 Task 前先对账外部行为。
- `completed` 和 `canceled` 不可重开。Run 完成后仍可追加 Task，状态由事件重新派生。
- 不手工编辑 `.noctis/runs/`，不复制本机缓存，也不用聊天记录替代 Result/Event。

创建 JSON 时读取 [references/contracts.md](references/contracts.md)。执行命令、扩展或恢复时读取 [references/operations.md](references/operations.md)。
