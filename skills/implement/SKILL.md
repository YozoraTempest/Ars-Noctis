---
name: implement
description: 实现明确的工程任务，或集中修复用户已经接受的审查问题和已授权的验证失败；通过独立脚本维护 implementation.md、执行 Task 内部 Step 并创建边界清晰的本地提交。用于显式实现、修复或 Noctis Exec 中 capability 为 implement/fix 的 active Task；不负责规划、测试、代码审查、行为验证、推送或部署。
---

# Implement

只实现或修复。不要在过程中扮演审查者，也不要运行测试、构建或浏览器验收。

## 进入 Task

由 Noctis Exec 调度时，用已加载的 `orchestration inspect --id <task-id>` 读取目标 Task。仅在 `status: active` 且 capability 为 `implement` 或 `fix` 时继续；否则返回 deferred，不修改文件或状态。使用 Task 固化的 Track、binding 和 record，不读取项目注册表或其他 Skill 正文。

独立调用时只执行用户指定的实现或修复，不增加 Review、Verify 或其他 Task。没有 Noctis 上下文时，不伪造编排状态。

一个 Task 可以包含多个实施 Step。Step 只用于当前实现记录和断点恢复，不是 Noctis 调度项。跨项目工作应拆成不同 Track 的 Task，以便分别提交和并行；不要在 Implement 内再次发明父子任务。

## 维护实现记录

使用 `scripts/implementation.py` 管理 Task 的 `record.path` 指向的 `implementation.md`，不要直接编辑结构化文档。脚本提供 `create/read/update/append`，默认 JSON 输出，写入需要 `--expected-revision`。

开始修改前记录：

- Direction：本 Task 的方向、边界和关键约束；
- Current：本轮 Step、目标仓库和已知阻塞。

完成后以稳定 Task ID 向 Completed 追加结果、仓库、业务提交哈希和已完成 Step。记录事实，不写审查结论或行为通过声明。一个 Track 的后续 Fix Task 可以复用同一文档，但必须使用新的 Task ID。

## Implement Task

1. 读取 Task 目标、Unit 场景、适用项目规则和完成 Step 所需的源码。
2. 在既定范围内实现，不加入防御性增强、可选重构或未经确认的兼容策略。
3. 检查差异与工作树，保留用户无关修改，只暂存当前 Task。
4. 每个完成的 Task 在所属仓库创建一个 Conventional Commit，并附 `Noctis-Task: <task-id>` trailer。
5. 登记提交和完成方式，再用 Noctis Exec `orchestration finish` 把 Task 标为 `completed`。

差异检查、语法定位和 Git 状态不属于测试；不要借此宣称行为已验证。

## Fix Task

只修复已由用户批量接受的 Review finding，或已授权的 Verify failure。通过已加载的 Review/Verification 文档工具读取稳定 ID、证据和最小修复范围，不直接解析 Markdown，也不重新审查问题。

一次处理当前批准批次；每个受影响仓库使用独立 Fix Task 和 `fix:` 提交，在 Completed 关联 finding/scenario ID。不得扩展修复范围或顺手加固。完成后正常结束 Fix Task；后继复审或重验由 Unit 依赖图调度，不自行计算返回顺序。

## 恢复与边界

恢复时读取 Unit Task 和 implementation 状态，再核对工作树及登记的 Noctis-Task 提交。未提交工作原地继续；提交存在但记录缺失时，核实范围后补记。证据冲突时阻塞 Task，不改写历史。

未经单独授权，不运行测试、审查、行为验收、推送、部署或外部业务写入。
