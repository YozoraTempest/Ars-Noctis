---
name: noctis-continue
description: 在当前执行者缺少可信对话上下文时，从项目既有 noctis.md 恢复最小执行入口、Artifact 输入和来源句柄并交给 Noctis Exec。用于断点恢复、上下文压缩后继续、切换对话、切换模型或更换 Agent；也可由 $noctis continue 路由调用。不规划新任务、不判断执行状态、不修改任何生命周期记录。
---

# Noctis Continue

只恢复入口，然后退出。不要根据上下文丢失的原因创建不同流程。

## 恢复入口

1. 激活 `noctis-exec`，使用其 `scripts/exec.py entry` 执行只读定位。
2. 用户提供记录路径时传入 `--record`；提供明确 Task 时再传入 `--id`。
3. 未提供记录时从当前目录向上定位最近的 `Noctis/registry.yaml`，只扫描该项目。
4. 唯一未完成根记录直接使用；多个候选展示路径、目标和状态并让用户选择；没有候选或记录损坏时报告事实，不新建计划。
5. 把返回的 ExecutionEntry 原样交给 `noctis-exec`，由 Exec 判断 `pending`、`active`、`blocked` 或 `completed` 并继续生命周期。

ExecutionEntry v2 只包含当前记录、revision、父级目标与完成条件、授权、active/ready/blocked 列表，以及明确目标的 binding、记录路径、直接前置结果、resolvedInputs 和 unresolvedInputs。

## 保持边界

- 不创建额外 continue 文件，不依赖旧对话摘要。
- 不记录模型、Agent、原对话或中断原因。
- 不选择 executor/support，不读取其 `SKILL.md`。
- 不修改 `noctis.md`、业务文件、Git 或外部系统。
- 不提供 owner、租约或超时；revision 并发保护归 Exec。
