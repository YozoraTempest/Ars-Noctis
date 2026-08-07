---
name: implement
description: 实现明确的工程任务，或集中修复用户已经接受的审查问题和已授权的验证失败；创建边界清晰的本地业务提交，并在 Noctis 模式维护 implementation.md 和返回执行结果。用于显式实现、修复或 Noctis Exec 中 capability 为 implement、fix-review、fix-verification 的 active Task；不负责规划、测试、代码审查、行为验证、编排状态、推送或部署。
---

# Implement

只实现或修复。不要在过程中扮演审查者，也不要编写或运行测试、构建或浏览器验收；测试由独立 Test Skill 承担，避免实现者用自写测试证明自身实现。

## 进入 Task

由 Noctis Exec 调度时，用已加载的 `orchestration inspect --id <task-id>` 读取目标 Task。仅在 `status: active` 且 capability 为 `implement`、`fix-review` 或 `fix-verification` 时继续；否则返回 deferred，不修改文件或状态。使用 Task 固化的 Track、binding、record 和 `resolvedInputs`；只读取声明接受的 Artifact，不修改上游原生产物，也不读取项目注册表或其他 Skill 正文。

独立调用时只执行用户指定的实现或修复，不要求 `noctis.md`、Unit 场景或 Task `record.path`，也不增加 Review、Verify 或其他 Task。没有 Noctis 上下文时，不创建或伪造编排状态；除非用户明确要求持久记录，否则直接返回改动与提交摘要。

一个 Task 可以包含多个实施 Step。Step 只用于当前实现记录和断点恢复，不是 Noctis 调度项。跨项目工作应拆成不同 Track 的 Task，以便分别提交和并行；不要在 Implement 内再次发明父子任务。

## 维护实现记录

仅在 Noctis Task 或用户明确要求实现记录时，使用 `scripts/implementation.py` 管理 `record.path` 指向的 `implementation.md`，不要直接编辑结构化文档。脚本提供 `create/read/update/append`，默认 JSON 输出，写入需要 `--expected-revision`。

开始修改前记录：

- Direction：本 Task 的方向、边界和关键约束；
- Current：本轮 Step、目标仓库和已知阻塞。

完成后以稳定 Task ID 向 Completed 追加结果、仓库、有序业务提交哈希和已完成 Step。记录事实，不写审查结论或行为通过声明。一个 Track 的后续 Fix Task 可以复用同一文档，但必须使用新的 Task ID。保留脚本返回的 document revision，用于发布 `ars.implementation@1` ArtifactRef。

## Implement Task

1. 读取当前目标、适用项目规则和完成 Step 所需的源码；Noctis Task 另读取已解析输入及适用 Unit 场景。
2. 在既定范围内实现，不加入防御性增强、可选重构或未经确认的兼容策略。
3. 检查差异与工作树，保留用户无关修改，只暂存当前 Task。
4. 每个完成的 Noctis Task 在所属仓库至少创建一个边界清晰的 Conventional Commit；需要多个连贯提交时保持有序，并为每个提交附 `Noctis-Task: <task-id>` trailer。
5. Noctis Task 登记提交和完成方式后，向调用方返回 `ExecutorResult v1`；完成结果的 `commits` 至少包含一个有序业务提交，`implementation` Artifact 指向 Task `record.path`，revision 使用最终实现记录 revision。独立调用直接返回业务结果与提交，不返回伪造的编排结果。

不要调用 Noctis Exec 的 `finish`、`splice` 或其他生命周期写命令。Implement 只提交业务代码和自己拥有的实现记录；Noctis Exec 校验 `ExecutorResult`、完成 Task、提交编排状态并选择后继。

差异检查、语法定位和 Git 状态不属于测试；不要借此宣称行为已验证。

## Fix Task

`fix-review` 只消费 required `resolvedInputs.review`，修复用户批量接受的 finding；`fix-verification` 只消费 required `resolvedInputs.verification`，修复已授权 failure。通过来源文档工具读取稳定 ID、证据和最小修复范围，不直接解析 Markdown，也不重新审查问题。

一次处理当前批准批次；每个受影响仓库使用独立 Fix Task 和至少一个边界清晰的 `fix:` 提交，在 Completed 关联 finding/scenario ID。不得扩展修复范围或顺手加固。完成后正常结束 Fix Task；后继复审或重验由 Unit 依赖图调度，不自行计算返回顺序。

## 恢复与边界

恢复时读取 Unit Task 和 implementation 状态，再运行 `scripts/reconcile_task.py --repo <repo> --task-id <id> [--recorded-commit <sha> ...]`，按记录顺序为每个提交重复参数。按脚本状态处理：`continue-uncommitted` 原地继续；`repair-record-from-commit` 核实范围和产物后，使用 `--action plan-record-repair --record-revision <revision>` 获取确定性的 implementation 工具调用并补记全部有序提交；`consistent` 进入下一阶段；`rerun-from-checkpoint` 从最后一个完成检查点重做；`blocked-evidence-conflict` 阻塞且不改写历史。切换工作树或机器前先通过 fetch、bundle 等方式取得提交，不能把“另一台机器工作树干净”误判为任务完成。

未经单独授权，不运行测试、审查、行为验收、推送、部署或外部业务写入。
