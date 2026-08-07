---
name: noctis-exec
description: 接收 Noctis 已确认的 Task、Unit 或 Work 执行计划，或接收 Noctis Continue 重建的 ExecutionEntry，创建并推进 noctis.md、解析 Artifact Binding、调度已固化的原生 Ars/support、处理阻塞与异常恢复，并维护结构化文档扩展。用于首次进入或继续既有 Noctis 执行生命周期；不负责需求规划或执行具体业务能力。
---

# Noctis Exec

只管理执行生命周期。不要重新规划需求，也不要替代 executor 或 support。

## 核心 Interface

只接受两种入口：

- `start-workflow` 接收 ExecutionPlan v2：由 Noctis 交互确认，包含层级、目标、完成条件、授权、依赖图、Task binding 和 Artifact Binding。
- `resume-workflow` 接收 ExecutionEntry v2：由 Noctis Continue 从已有 `noctis.md` 重建，包含记录路径、revision、最小父级上下文、resolved inputs 和可执行状态。

Task、Unit 与 Work 统一使用 `pending | active | blocked | completed`。Work 只观察 Unit，Unit 只观察 Task；Task 内 Step 由 executor 自己维护。

保持以下不变量：

- 首次写入前用 `orchestration create --dry-run` 校验全部计划记录。
- 每次状态写入都使用刚读取的 `expectedRevision`，冲突时重新读取，不盲目覆盖。
- 沿用 Task 已固化的 capability、executor、support 和记录路径，不用项目注册表替换快照。
- 启动 Task 前解析 required input；完成 Task 时校验并保存声明的 output ArtifactRef。
- Continue 的来源不影响执行语义；断点、换模型、换 Agent 和换对话都进入同一流程。
- 范围、依赖图、provider、完成条件或授权变化时返回 `replan-required`，交回 Noctis。

## 按需加载

根据当前动作只读取一个直接引用：

- 通过 `start-workflow` 接收新的 ExecutionPlan：读取 [start.md](references/start.md)。
- 通过 `resume-workflow` 接收 ExecutionEntry，或推进已有记录：读取 [run.md](references/run.md)。
- Review/Verify 需要插入已授权修复流程：读取 [recover.md](references/recover.md)。

不要从引用继续追读其他引用。动作变化时回到本文件重新路由。

## 使用工具

使用 `scripts/exec.py`：

- `entry`：只读定位项目记录并生成最小 ExecutionEntry。
- `orchestration create/inspect/start/resume/finish/splice/scan`：管理生命周期。
- `extend insert/upsert/sync/remove/read`：管理稳定 Markdown 扩展。

脚本默认输出 JSON；展示正文时才使用 `--format markdown`。参数以 `--help` 为准，不为调用工具读取脚本源码。

显式加载 Exec 不扩大测试、提交、推送、部署或外部写入授权。
