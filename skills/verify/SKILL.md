---
name: verify
description: 根据用户确认的独立场景执行实际行为验收，按场景组合人工、AI 和 AI 辅助模式，并持久记录操作、证据与结果。仅在用户显式调用、Noctis workflow 包含 verify 或任务处于 verify 阶段时使用；不编写业务代码、单元测试或静态代码审查。
---

# 行为验证

只验证实际行为并记录证据。不要修改业务代码、设计单元测试或把静态代码阅读描述为验收。

## 阶段守卫

在提出场景方案或执行任何验证前，先确定目标 Task 或 Subtask 及其当前状态。仅在 `status: active, stage: verify` 时继续。

由 `$noctis` 调度，或与其他原子 Skill 一次性显式调用时，如果当前阶段尚未到 `verify`，则返回接力状态 `deferred` 并把控制权交还调用链。不要把它作为错误或完成结论告知用户，不要提问，也不要创建验证记录、操作环境或修改任务状态。任务记录尚不存在且显式 workflow 中存在更早阶段时同样返回 `deferred`。

单独调用本 Skill 且任务阶段不匹配时，报告当前阶段和期望的 `verify` 阶段后停止，不要代替其他 Skill 工作。

Noctis 管理的多阶段 workflow 需要推进时，相对于本文件读取 `../noctis/registry.yaml`，用下一 workflow 项的 `entry_stage` 更新任务。只读取注册元数据，不读取下一 Skill；注册表缺失、注册项不一致或当前 Skill 在 workflow 中不唯一时设置 `status: blocked` 并停止。单独执行且 workflow 只有本 Skill 时不依赖注册表。

## 准备场景方案

优先使用用户指定的 Task 或 Subtask。否则定位唯一满足 `status: active` 且 `stage: verify` 的任务；存在多个候选时展示候选，不要猜测。

读取 `tasks.md` 和已有 `scenarios.md`，不要读取实现者的实现理由。规划 Skill 优先维护 `scenarios.md`；文件不存在时，根据任务目标提出独立的 Given/When/Then 场景，经用户确认后创建。不得根据实现细节反向设计只会通过的场景，也不得由 implement 或 code-review 改写场景。

为每个场景生成稳定 `Vxx` 编号，关联 `SCxx`，并单独推荐模式：

- `human`：用户执行并判定；只能记录用户报告的结果。
- `ai`：AI 使用可用工具执行并依据客观可观察结果判定。
- `assisted`：AI 打开页面、导航、准备状态或截图，用户最终判定。

一次性展示全部场景、模式、执行步骤、预期证据、目标环境和副作用。用户可以增删或调整；全部明确确认后才创建 `verification.md` 并执行。

## 获得有界授权

将有界授权纳入场景方案，明确环境、目标、场景、允许的状态变更、测试数据和清理方式。用户确认整批方案后，授权只在本批次内有效。

不得把现有登录状态扩展为其他权限。跳转到不同环境、出现未列明写入或无法确认数据归属时立即停止。生产环境、权限变更、批量操作及不可逆删除必须另行获得明确授权。

## 执行并记录证据

使用最小且合适的手段执行已确认场景，例如人工操作、浏览器插件、已有命令或 API。工具不可用时记录 `blocked`，不得伪造或静默降级。仅打开页面、看到元素或已有测试代码均不等于场景通过。

每个场景记录：

```markdown
## V01 <title>

- Scenario: `SC01`
- Mode: `assisted`
- Executor: AI
- Evidence Policy: `local`
- Evidence: <observation or relative path>
- Verdict by: user
- Result: pending
```

为每个场景选择证据策略：

- `none`：只记录文字观察；默认用于普通 AI 验收。
- `local`：保存到 Task 相对路径 `evidence/`，不进入 Git；默认用于辅助验收。
- `git`：仅在需要审计或交接时使用；截图生成后检查敏感信息，并再次获得用户确认才能提交。

不要记录 URL 查询参数、令牌或会话信息，也不要硬编码工作区绝对路径。

## 汇总结果

使用 `passed`、`failed`、`blocked` 或 `pending`。除出现未授权写入、数据破坏或安全风险必须立即停止外，执行完整个已确认的安全场景集，再统一汇总。

- 全部 `passed`：存在下一注册 Skill 时推进到它的 `entry_stage`；没有下一项时设置 `status: completed` 并移除 `stage`。
- 存在 `failed`：保持 `status: active, stage: verify`，一次性等待用户确认修复范围。
- 存在无法继续的 `blocked`：设置 `status: blocked, stage: verify`。
- 存在 `pending`：保持 `status: active, stage: verify`，等待对应人工判定。

用户确认修复后推进到 `fix`，记录授权范围并提交任务状态检查点，再由 implement 集中修改；若 workflow 包含 code-review，则修复后先执行定向修复复核，再返回 verify。重验失败场景及修复直接影响的场景，重新一次性确认范围，不自动循环。

## 创建检查点

在场景方案确认后提交一次 `verification.md` 和任务状态；整批执行结束或安全停止后再提交一次。延后的人工判定到达时追加结果检查点。使用 `docs:` 摘要和对应 `Noctis-Task` trailer，不提交业务代码；`git` 证据除外且必须已经单独确认。
