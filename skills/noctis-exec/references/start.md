# 启动执行计划

只通过 `materialize-workflow` 接收当前 Agent 已经用 Noctis 展示并由用户确认的 ExecutionPlan v2。这个能力只物化状态机，不启动 Task。Exec 不读取注册表选择 Workflow Template；缺少确认、目标、完成条件、授权、Task binding 或 Artifact Binding 时返回 `replan-required`，不要在 Exec 内补规划。

## 校验计划

要求顶层只包含 `version: 2`、根记录 `root` 和非空 `records`。每条记录只包含：

- `level`：`task`、`unit` 或 `work`；
- 相对项目根的 `path`；
- `input`：包含 id、标题、目标、完成条件、allowed/forbidden 授权，以及对应层级数据。

确认 `root` 精确匹配其中一条记录。使用 `workflow materialize --dry-run` 整体校验，并确认路径均位于项目 `Noctis/` 内且尚未存在。Work 计划必须让每个 Unit path 指向计划中的 Unit 记录。

## 选择记录位置

- 单 Task：`Noctis/<domain>/tasks/<task-id>/noctis.md`。
- 单 Unit：`Noctis/<domain>/units/<unit-id>/noctis.md`。
- Work：`Noctis/<domain>/work/<work-id>/noctis.md`，子 Unit 位于其 `units/` 下。

只有通过 Noctis/Exec 启动的单 Task 才创建任务级记录；独立调用原子 Skill 时不要增加 Noctis 文件。

## 进入生命周期

用户确认后使用 `workflow materialize --confirmed` 原子创建全部记录；任何记录失败时不得保留部分 `noctis.md`。所有 Task 都是 pending，根状态也是 pending。然后立即对根记录调用 `entry`，把生成的 ExecutionEntry 原样交给 `execute-workflow`。ExecutionPlan 只是物化输入，不另存一份计划文件；`noctis.md` 是后续恢复的权威状态。
