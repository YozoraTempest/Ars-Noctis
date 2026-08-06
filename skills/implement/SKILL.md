---
name: implement
description: 实现明确的工程任务，或集中修复用户已经接受的审查问题和已授权的验证失败；通过独立脚本维护 implementation.md、执行 Step 并创建边界清晰的本地提交。用于显式实现、修复或 Noctis 的 implement/fix stage；不负责规划、测试、代码审查、行为验证、推送或部署。
---

# Implement

只实现或修复。不要在过程中扮演审查者，也不要运行测试、构建或浏览器验收。

## 进入执行单元

由 Noctis 调度时，先通过已加载的 Noctis task 工具 inspect 目标 Task/Subtask。仅在 `status: active` 且 stage 为 `implement` 或 `fix` 时继续；不匹配则返回 `deferred`，不修改文件或状态。使用任务快照决定后续 stage，不读取项目注册表或其他 Skill 正文。

独立调用时只执行用户指定的实现或修复，不增加 review、verify 或其他阶段。若用户给出了 Noctis 任务路径，仍用 task 工具读取目标和 Step；没有 Noctis 上下文时，不伪造编排状态。

优先完成唯一叶子 Subtask。多仓库任务以仓库或独立交付边界拆分 Subtask；父 Task 只统筹依赖与进度。一个 Subtask 可有多个 Step，但 Step 不是独立提交或审查单位。

## 维护实现记录

使用本 Skill 的 `scripts/implementation.py` 管理任务目录中的 `implementation.md`，不要直接编辑结构化文档。脚本提供 `create/read/update/append`，默认 JSON 输出，写入需要 `--expected-revision`；参数以 `--help` 为准。

开始修改前记录：

- `Direction`：本执行单元的方向、边界和关键约束；
- `Current`：本轮正在处理的 Step、仓库和已知阻塞。

完成后在 `Completed` 追加稳定 ID 条目，记录结果、仓库、业务提交哈希和对应 Step。记录事实，不写审查结论或行为通过声明。基础写入必须保留其他能力加入的扩展块。

## Implement 阶段

1. 读取任务目标、已确认场景、适用项目规则和完成当前 Step 所需的源码。
2. 在既定范围内实现，不加入防御性增强、可选重构或未经确认的兼容策略。
3. 检查差异与工作树，保留用户的无关修改，只暂存当前执行单元。
4. 每个完成的 Subtask 在其所属仓库创建一个 Conventional Commit，并附加 `Noctis-Task: <task-path>` trailer。
5. 用 implementation 工具登记提交，再用 Noctis task 工具勾选 Step、同步父任务进度并迁移 stage。
6. Noctis 记录位于另一个仓库时，用独立 `docs:` 检查点提交；最后一个 Subtask 的完成和父任务的相应推进放在同一记录检查点。

差异检查、语法定位和 Git 状态不属于测试；不要借此宣称行为已验证。

## Fix 阶段

只修复已经由用户批量接受的 review finding，或已经授权修复的 verification failure。通过已加载的 review/verification 文档工具读取稳定 ID、证据和最小修复范围，不直接解析它们的 Markdown，也不重新审查问题。

一次处理当前批准批次；每个受影响仓库创建一个 `fix:` 提交，在 `Completed` 关联 finding/scenario ID。不得扩展修复范围或顺手加固。

修复完成后用 Noctis task `transition --use-resume` 返回快照中的恢复队列。没有有效 resume 时停止并报告编排错误，不猜测 review/verify 顺序。

## 恢复与边界

恢复时通过脚本读取 task 和 implementation 状态，再核对工作树及登记的 `Noctis-Task` 提交。未提交工作原地继续；提交存在但记录缺失时，核实范围后补记。证据冲突时阻塞任务，不改写历史。

未经单独授权，不运行测试、审查、行为验收、推送、部署或外部业务写入。
