---
name: verify
description: 基于用户逐项确认的独立场景执行实际行为验收，组合人工、AI 与 AI 辅助模式，并记录可观察证据和判定。用于显式验收或 Noctis 的 verify stage；不编写业务代码、单元测试，也不做静态代码审查。
---

# Verify

只验证实际行为。不要修改实现、编写单元测试或把代码检查当作验收证据。

## 阶段守卫

由 Noctis 调度时先用 task 工具 inspect。仅在 `status: active, stage: verify` 时继续；否则返回 `deferred`，不创建记录、操作环境或迁移状态。独立调用时只执行用户明确要求的验收，不注入 review 或 fix。

使用已加载的 scenarios 文档 provider 读取场景。规划 Skill 已生成 `scenarios.md` 时必须沿用；没有 provider 或文件时，才使用本 Skill 的 `scripts/scenarios.py` 创建后备场景文档。不得覆盖既有场景，也不得根据实现细节反向编写容易通过的场景。

## 确认验收方案

所有场景都需要用户确认。每个场景使用稳定 ID 和 Given/When/Then，覆盖用户选择的正常、异常与边界行为；不要把多个独立结果藏在一个场景中。

为每个场景推荐一种模式：

- `human`：用户操作并最终判定，AI 只记录用户报告。
- `ai`：AI 使用获准工具执行，并按客观可观察结果判定。
- `assisted`：AI 负责打开、导航、准备或截图，用户最终判定。

一次性展示场景、模式、步骤、预期证据、环境和副作用。用户可增删或调整；整批明确确认后才执行。若启用 Noctis augmentation，用 `extend sync` 将 `verify:verified` 扩展同步到每个 `scenarios.item.after`，不直接改写场景正文。

## 有界授权

确认内容必须明确环境、目标、允许的状态变更、测试数据和清理方式。授权只覆盖当前批次。登录状态不是额外权限；切换环境、出现未列明写入或无法确认数据归属时立即停止。生产、权限变更、批量操作和不可逆删除必须另行明确授权。

## 执行与记录

使用 `scripts/verification.py` 管理 `verification.md`，不要直接编辑。先在 `Plan` 记录确认后的场景、模式与证据策略，再按稳定 ID 向 `Results` 追加结果。

证据策略：

- `none`：仅记录文字观察，适合普通 AI 验收；
- `local`：存入任务相对路径 `evidence/` 且不提交，适合 assisted；
- `git`：仅在审计或交接需要时使用，先检查敏感信息，并再次确认后才能提交。

每项记录 executor、可观察 evidence、verdict owner 和 `passed | failed | blocked | pending`。工具不可用就记 blocked，不伪造或静默降级；只打开页面、看到元素或存在测试代码均不算通过。除未授权写入、数据破坏或安全风险需立即停止外，执行完整个已确认安全批次后统一汇总。

## 结果迁移

- 全部 passed：按任务快照进入下一 stage 或 completed。
- 有 failed：一次性让用户确认修复范围；确认后由 Noctis 转到 `fix`。原 workflow 含 review 时 resume 为 `review verify`，否则为 `verify`。
- 有 blocked：保留 verify 并将任务设为 blocked。
- 有 pending：保持 active/verify，等待人工判定。

修复后只重验失败场景和 fix 直接影响的场景；再次一次性确认范围，不自动循环。

场景方案、整批结果和延后人工判定分别创建必要的 `docs:` 检查点并附 `Noctis-Task` trailer。未经授权不提交敏感证据、不修改业务代码、不推送、不部署。
