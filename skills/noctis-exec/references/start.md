# 启动执行计划

只通过 `start-workflow` 接收 Noctis 已经展示并由用户确认的 ExecutionPlan v2。缺少确认、目标、完成条件、授权、Task binding 或 Artifact Binding 时返回 `replan-required`，不要在 Exec 内补规划。

## 校验计划

要求顶层只包含 `version: 2`、根记录 `root` 和非空 `records`。每条记录只包含：

- `level`：`task`、`unit` 或 `work`；
- 相对项目根的 `path`；
- `input`：包含 id、标题、目标、完成条件、allowed/forbidden 授权，以及对应层级数据。

确认 `root` 精确匹配其中一条记录。使用 `orchestration create --dry-run` 逐条校验，并确认路径均位于项目 `Noctis/` 内且尚未存在。Work 计划先校验全部 Unit 和 Work，并确认每个 Unit path 指向计划中的 Unit 记录；随后创建 Unit，最后创建 Work 根记录。

## 选择记录位置

- 单 Task：`Noctis/<domain>/tasks/<task-id>/noctis.md`。
- 单 Unit：`Noctis/<domain>/units/<unit-id>/noctis.md`。
- Work：`Noctis/<domain>/work/<work-id>/noctis.md`，子 Unit 位于其 `units/` 下。

只有通过 Noctis/Exec 启动的单 Task 才创建任务级记录；独立调用原子 Skill 时不要增加 Noctis 文件。

## 进入生命周期

创建后立即 `inspect`，核对 revision、层级和 ready 与已确认计划一致。再按普通运行规则启动可执行项。ExecutionPlan 只是入口数据，不另存一份计划文件；`noctis.md` 是后续恢复的权威状态。
