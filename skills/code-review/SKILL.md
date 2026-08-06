---
name: code-review
description: 对 Noctis Task 或 Subtask 记录的精确业务提交执行一次独立静态代码审查，记录 P0-P2 finding，并在用户确认后复核集中修复。仅在用户显式调用代码审查、任务处于 review 阶段或显式组合包含 code-review 时使用；不修改业务代码、不运行测试或行为验收。
---

# 代码审查

只审查代码并记录结论。不要修复代码、运行测试、构建应用或执行页面验收。

## 阶段守卫

在读取业务差异或创建审查记录前，先确定目标 Task 或 Subtask 及其当前状态。仅在 `status: active, stage: review` 时继续。

由 `$noctis` 调度，或与其他原子 Skill 一次性显式调用时，如果当前阶段尚未到 `review`，则返回接力状态 `deferred` 并把控制权交还调用链。不要把它作为错误或完成结论告知用户，不要提问，也不要创建 `review.md` 或修改任务状态。任务记录尚不存在且显式 workflow 中存在更早阶段时同样返回 `deferred`。

单独调用本 Skill 且任务阶段不匹配时，报告当前阶段和期望的 `review` 阶段后停止，不要代替其他 Skill 工作。

Noctis 管理的多阶段 workflow 需要推进时，相对于本文件读取 `../noctis/registry.yaml`，用下一 workflow 项的 `entry_stage` 更新任务。只读取注册元数据，不读取下一 Skill；注册表缺失、注册项不一致或当前 Skill 在 workflow 中不唯一时设置 `status: blocked` 并停止。单独执行且 workflow 只有本 Skill 时不依赖注册表。

## 确定审查单元

优先使用用户指定的 Task 或 Subtask。否则定位唯一满足 `status: active` 且 `stage: review` 的任务；存在多个候选时展示候选，不要猜测。

读取适用的 `AGENTS.md`、目标 `tasks.md` 和 `scenarios.md`。场景只说明预期行为，不代表已经验证。只从 `implementation.md` 提取仓库路径和提交哈希，忽略 `Direction`、`Current`、`Completed` 中的实现理由。

使用 `implementation.md` 登记的精确业务提交作为唯一审查范围：

- Subtask 初审：审查该 Subtask 的实现提交。
- Subtask 修复复核：只审查该 Subtask 的 fix 提交，并结合已接受 finding。
- Task 初审：汇总全部 Subtask 的实现与 fix 提交，只检查整体需求和跨 Subtask 集成。
- Task 修复复核：只审查 Task fix 阶段产生的提交。

排除 Noctis `docs:` 检查点。哈希缺失、无法解析或记录范围不一致时，将任务设为 `status: blocked, stage: review` 并停止，不得扩大到整个分支或工作树。

## 执行一次静态审查

平台支持独立或 Detached reviewer 时，只启动一个独立 reviewer，并只传递任务目标、场景、适用规则、精确提交差异及必要源码上下文。不要传递实现者的方案解释或审查预期答案，也不要启动多 reviewer、分轴审查或自动复审循环。平台不支持独立上下文时，在当前上下文执行一次审查，并明确说明独立性降低。

检查完整差异及理解它所必需的调用方、契约、配置和现有测试代码。Subtask 审查聚焦局部实现正确性；Task 只执行集成审查，检查需求完整性、跨仓库契约、数据流、依赖顺序和组合后的冲突，不重复局部审查。

只有同时满足以下条件时才记录 finding：

- 差异引入具体行为错误、安全或数据风险，或违反适用的明确契约；
- 能从代码、调用方、规则或场景证明触发路径可达；
- 能说明实际后果、精确位置和最小修复方向。

不得报告契约排除的输入、无证据的未来风险、纯风格偏好、可选重构、机械工具能够处理的问题或“可以更保险”的建议。不要输出 P3、nit 或 advisory。

使用以下优先级：

- `P0`：安全边界失效、不可逆数据损坏或核心系统不可用。
- `P1`：主要业务路径、权限、公开契约或跨 Subtask 协作错误。
- `P2`：受支持且可达的局部或边界场景错误，影响有限。

## 记录并确认 finding

首次审查时创建当前 Task 或 Subtask 唯一的 `review.md`。每个 finding 使用稳定 ID 和独立小节：

```markdown
## F01 [P1] <title>

- Location: `<path>:<line>`
- Scenario: `SC01`
- Evidence: <reachable code evidence>
- Impact: <actual consequence>
- Minimal fix: <smallest correction>
- Decision: pending
- Resolution: pending
```

无 finding 时只写“未发现代码级问题”，不得声称行为验证通过。按 workflow 推进到下一注册 Skill 的 `entry_stage`；没有后续阶段时设为 `completed`。

存在 finding 时保持 `status: active, stage: review`，一次性展示完整清单并等待用户批量确认。用户确认后原地标记 `accepted` 或 `rejected`；存在 accepted finding 时推进到 `fix`，全部 rejected 时按相同的注册 workflow 规则推进。不得替用户决定或逐条触发修复。

每次初审、用户决定和修复复核结束后，只提交 `review.md` 与任务状态，使用 `docs:` 摘要和对应 `Noctis-Task` trailer。

## 复核集中修复

存在 accepted finding 和新登记的 fix 提交时执行一次定向修复复核。逐项确认原问题是否解决，并只检查 fix diff 直接造成的回归；不得重新扫描旧代码或提出无关 finding。

全部解决时更新 `Resolution: resolved`，然后按相同的注册 workflow 规则进入下一阶段或完成。存在未解决问题或直接回归时记录证据，设置 `status: blocked, stage: review` 并停止。不要自动启动第二轮修复或复核。
