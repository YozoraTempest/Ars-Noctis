---
name: noctis
description: 规划、执行或从 Git clone 恢复需要多个 Agent Skills、依赖图或持久状态的工作流。用户明确提到 Noctis、要求跨会话或跨机器继续未完成 Task，或一个目标确实需要多个独立能力按依赖组合时使用；不要为单一、可在当前会话直接完成的任务自动引入。
---

# Noctis

把 Noctis 当作协作式状态内核，不当作 Agent 宿主。脚本只发现能力、校验契约和原子推进状态；当前宿主负责加载 provider Skill 并执行 `ars.task/v1`。

## 选择入口

- 单个 Skill 可直接完成时，直接调用该 Skill，不创建 Run。
- 用户要求新建可恢复工作流时，执行“创建 Run”。
- 用户要求继续、恢复或查看进度时，先执行 `run-show`；新 clone 先执行 `recover`，依据 Git 中的持久事实选择入口，不重建旧对话。

## 创建 Run

1. 用 `scripts/noctis.py catalog --skills-root <目录>` 发现 `ars.json`。不要为发现能力读取 provider 的 `SKILL.md`。
2. 创建 `ars.plan/v1`，只保留一个 Run 和一个 Task DAG。每个 Task 绑定 provider、capability、workspace、直接依赖、输入 Artifact、验收条件与实际需要的副作用。
3. 向用户展示目标、Task 图、workspace 范围和待授予副作用。计划或授权会扩大用户请求时先确认。
4. 用 `plan-check` 校验 DAG、provider 与现有输入，再用 `run-create` 写入 `<project>/.ars/runs/<run-id>/`。只有从用户请求中已有明确授权的副作用才能传给 `--grant`；高风险副作用还必须使用 `--confirm-high-risk`。
5. 在领取首个 Task 前，把 Run JSON 作为检查点提交并推送到 Run 所在分支。Noctis 不代替宿主提交或推送。

## 推进 Run

1. 确认 Run JSON 和目标 workspace 都没有未提交内容，再调用 `task-claim` 领取 ready Task，并保留返回的本机 Task envelope。
2. 按 envelope 中精确的 provider ID 加载该 Skill；传递 envelope，不传递旧对话总结或其他 Skill 私有文件。
3. 要求 provider 返回 `ars.result/v1`。产生 `workspace.write` 时，先在授权范围内提交产物，并在 Result 中同时提供匹配的 Git Artifact 与 `git.commit` receipt。
4. 确认 workspace 已无未提交内容，再用 `task-finish` 携带 claim ID 和 expected revision 写入不可变 Result 与追加事件；把 CLI 返回的 checkpoint 文件提交并推送后，该完成状态才可跨机器恢复。
5. 重复领取 ready Task；可以在独立分支并行执行互不依赖的 Task，汇合后再让后继 Task 运行。所有 Task 完成时 Run 自动完成。

Noctis 不直接模拟调用另一个 Agent，也不把工具可用、登录状态或 manifest 的 `effects` 当作授权。它不提交、不推送、不部署业务产物。

用户撤回授权时调用 `revoke`，立即清除本机授权并追加持久事件。已经处于本机 `working` 的 Task 不能被脚本抢占；立即停止调用 provider，并按恢复规则核对已经发生的副作用。

## 恢复与异常

- Git 中的 Plan、Result 与 Event 是唯一持久事实；Git 元数据目录中的 Noctis SQLite 只保存本机 claim 和当前机器授权，不提交。
- 新 clone 调用 `recover` 重建空缓存。没有持久 Result 的旧 claim 不恢复，对应 Task 按最后提交状态重新成为 `pending`；高风险授权也不从旧记录自动激活。
- `run-show` 列出 ready、本机 working 和终态 Task，并报告 checkpoint 是否已提交、是否已知推送。
- 先检查当前 workspace、Artifact、提交或外部系统证据；能够证明原执行完成时提交对应 Result。
- 只有确认需要重试时才调用 `task-retry`。可能已有副作用时必须显式传入 `--acknowledge-effects`，并让 provider 使用 Task 的稳定 `idempotency_key`。
- 缺少用户输入返回 `input-required`；缺少依赖、工具或权限返回 `blocked`；确定性执行错误返回 `failed`。取消使用 `task-cancel`，不删除历史事件。

编写 Plan、Task、Result 或 Artifact 时读取 [references/contracts.md](references/contracts.md)。执行命令或处理恢复时读取 [references/operations.md](references/operations.md)。
