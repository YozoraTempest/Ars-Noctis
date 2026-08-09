---
name: noctis
description: 创建、扩展、推进或从 Git clone 恢复协议无关的持久 Task DAG。用户明确提到 Noctis、要求跨会话或跨机器继续、需要有依赖的可恢复任务，或在运行中动态加入新 Task 时使用；不要为当前会话可直接完成的单一任务引入，也不要用它发现或执行特定 Agent Skill 协议。
---

# Noctis

把 Noctis 当作协议无关的持久状态内核，不当作 Agent 宿主。Core 只校验 executor、opaque request/output、requirement、DAG 和状态转换；外部 adapter 负责领域发现、执行与业务证据。

## 选择入口

- 当前会话能直接完成时直接执行，不创建 Run。
- 新建可恢复工作流时创建 `noctis.plan/v1`。
- 运行中出现新目标时追加 `noctis.extension/v1`，不改写 Plan 或已有 Task。
- 查看或继续时先调用 `run-show`；新 clone 或明确丢弃本机现场时调用 `recover`。

## 创建 Run

1. 让调用方或 adapter 提供 executor 快照。Noctis 不扫描 provider，也不读取其他 Skill。
2. 创建一个 Plan，包含目标、executor 列表和初始 Task DAG。Task 只声明 ID、依赖、executor、opaque request 和 requirement。
3. 展示目标、依赖图和待授权 requirement；超出当前用户请求的授权先确认。
4. 用 `plan-check` 校验，再用 `run-create` 写入 `<project>/.noctis/runs/<run-id>/`。
5. 在领取 Task 前提交 CLI 返回的 JSON checkpoint。Noctis 不自行提交或推送。

## 推进 Run

1. 调用 `task-claim` 领取 ready Task。返回的 `noctis.claim/v1` 固定 executor 快照、request、前置 Result、checkpoint 和本机 claim。
2. 把 Claim 交给对应 executor 或 adapter。不要让 Core 推断 opaque request 的含义。
3. executor 返回 `noctis.result/v1`；`output` 是严格 JSON，但对 Core 不透明。
4. 用 claim ID 和 expected Task revision 调用 `task-finish`。提交 Result/Event checkpoint 后，后继 Task 才能跨机器领取。
5. 重复直到当前所有 Task 进入终态。`working` 仅来自本机 claim，不是持久状态。

## 动态加入 Task

1. 记录来源 `origin.kind`、`origin.summary` 和可选 reference。
2. 新 executor 不在 Run 中时，在 Extension 中附带不可变快照；已有 executor 只引用其 ID。
3. 新 Task 可依赖任意未取消的已有或同批新增 Task，但不能替换已有 ID、修改历史或制造环。
4. 先调用 `extension-check`，再用当前 `run_revision` 调用 `run-extend`。单个 Task 可用 `task-add` 简写。
5. 提交追加事件。缺少 requirement 时先显式 `grant`，再领取 Task。

Run 已经 completed 也可追加 Task；追加后状态重新派生为 submitted。`fix`、`verify`、返工或用户临时目标都只是普通 Task，Noctis 不为任何名字或 executor 预置流程。

## 恢复与控制

- Git 中的 Plan、Result 与 Event 是唯一持久事实；Git 元数据目录中的 SQLite 只保存同一 worktree 的 mutation mutex、本机 claim 和当前机器授权。
- `recover` 清空所有本机 claim 与活动授权，再严格重放 JSON。记录过的授权不会在新机器自动激活。
- `grant` 和 `revoke` 管理任意 requirement 标识；Core 不把 requirement 解释成权限、副作用或工具。
- `failed`、`blocked`、`input-required` 可在对账后 `task-retry`；`completed` 和 `canceled` 不可重开。
- 重试或取消可能已使用 requirement 的本机 claim 时，显式传入 `--acknowledge-requirements`。这只是对账确认，不会撤销外部行为。
- 不手工编辑 `.noctis/runs/`，不把缓存复制为项目状态，不用旧聊天或外部文件替代 Result/Event。

创建 JSON 时读取 [references/contracts.md](references/contracts.md)。执行命令、扩展或恢复时读取 [references/operations.md](references/operations.md)。
