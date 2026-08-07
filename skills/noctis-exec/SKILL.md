---
name: noctis-exec
description: 接收 Noctis 已确认的 Task、Unit 或 Work 执行计划，或接收 Noctis Continue 重建的 ExecutionEntry，创建并推进 noctis.md、解析 Artifact Binding、调度已固化的原生 Ars/support、处理阻塞与异常恢复，并维护结构化文档扩展。用于首次进入或继续既有 Noctis 执行生命周期；不负责需求规划或执行具体业务能力。
---

# Noctis Exec

只管理执行生命周期。不要重新规划需求，也不要替代 executor 或 support。

## 核心 Interface

区分发现、物化与执行三个能力：

- `discover-entries` 接收可选 orchestration Artifact，用 `entry --list` 返回状态机实例及其 Task/Unit 入口候选，不推进状态。
- `materialize-workflow` 接收用户确认的 ExecutionPlan v2，只把完整计划原子写成初始 `pending` 的 `noctis.md`。
- `execute-workflow` 只接收 ExecutionEntry v2。无论是新计划还是断点恢复，都先由 `entry` 从 `noctis.md` 生成相同的执行输入。

`discover-entries` 发布 `noctis.execution-entry-set@1`；`materialize-workflow` 和 `execute-workflow` 发布当前根 `noctis.md` 的 `noctis.record@3` orchestration Artifact。Exec 不选择 Workflow Template，也不直接执行 ExecutionPlan。

Task、Unit 与 Work 统一使用 `pending | active | blocked | completed`。Work 只观察 Unit，Unit 只观察 Task；Task 内 Step 由 executor 自己维护。

保持以下不变量：

- 首次写入前用 `orchestration create --dry-run` 校验全部计划记录。
- 每次状态写入都使用刚读取的 `expectedRevision`，冲突时重新读取，不盲目覆盖。
- 沿用 Task 已固化的 capability、executor、support 和记录路径，不用项目注册表替换快照。
- 启动 Task 前解析 required input；完成 Task 时校验并保存声明的 output ArtifactRef。
- executor 只返回 `ExecutorResult v1`，不得直接写编排状态；只有 Exec 可以应用结果、提交编排检查点和选择后继。
- 跨 Skill 文档协调只消费已发布 Artifact 和稳定 ID，并通过目标 provider 已注册的文档工具或 augmentation 写入；不直接拼接原生 Markdown，不代替来源 Skill 改写事实。
- Continue 的来源不影响执行语义；断点、换模型、换 Agent 和换对话都进入同一流程。
- 范围、依赖图、provider、完成条件或授权变化时返回 `replan-required`，交回 Noctis。

## 按需加载

根据当前动作只读取一个直接引用：

- 通过 `materialize-workflow` 接收新的 ExecutionPlan：读取 [start.md](references/start.md)。
- 通过 `execute-workflow` 接收 ExecutionEntry 并推进已有记录：读取 [run.md](references/run.md)。
- Review/Verify 需要插入已授权修复流程：读取 [recover.md](references/recover.md)。

不要从引用继续追读其他引用。动作变化时回到本文件重新路由。

## 使用工具

使用 `scripts/exec.py`：

- `workflow materialize`：整体校验并创建已确认 ExecutionPlan 的全部 pending 记录，返回根 orchestration Artifact；
- `entry --list`：只读返回 ExecutionEntrySet；选定后用 `entry --record ... --id ...` 生成唯一 ExecutionEntry。
- `orchestration create/inspect/start/resume/apply-result/finish/splice/scan`：管理生命周期；正常 executor 返回统一使用 `apply-result`，`finish` 只保留给低层恢复与维护。
- `extend insert/upsert/sync/remove/read`：管理稳定 Markdown 扩展。

脚本默认输出 JSON；展示正文时才使用 `--format markdown`。参数以 `--help` 为准，不为调用工具读取脚本源码。

显式加载 Exec 不扩大测试、提交、推送、部署或外部写入授权。
