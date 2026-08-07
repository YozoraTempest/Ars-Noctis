---
name: code-review
description: 对 Task 登记的精确提交执行静态代码审查，记录可达且有证据的 P0-P2 finding，并在集中修复后通过新的 Review Task 做一次定向复核。用于显式代码审查或 Noctis Exec 中 capability 为 review 的 active Task；不修改业务代码、不运行测试，也不执行实际行为验收。
---

# Code Review

只审查代码。不要修复、运行测试、构建应用或把代码阅读描述成行为验证。

## 确定范围

由 Noctis Exec 调度时，用 `orchestration inspect --id <task-id>` 读取 Task。仅在 `status: active` 且 capability 为 `review` 时继续；否则返回 deferred。独立调用时按用户给出的提交、差异或范围审查，不注入其他 Task。

局部审查优先从 `resolvedInputs.implementation` 取得单个 ArtifactRef。集成审查从 `resolvedInputs.implementations` 或 `resolvedInputs.reviews` 取得多来源数组，逐项通过来源 provider 已注册的文档工具读取；不得丢弃其中任何直接依赖。没有这些可选输入的独立审查，再按用户明确范围确定提交。通过已加载的结构化工具读取：

- Unit `noctis.md` 中当前 Review Task 的依赖、目标和预期结果；
- 对应 Track 的 `implementation.md` 所登记的精确业务提交；
- Unit `scenarios.md` 的预期行为，仅作为契约证据，不当作已验证结果。

不要直接编辑或通篇解析这些 Markdown。排除 Noctis docs: 检查点。提交缺失、不可解析或记录范围不一致时阻塞，不得擅自扩大到整个分支或工作树。

每个项目 Track 可在 Implement 后安排局部 Review Task。所有局部分支完成后，再安排一个依赖它们的集成 Review Task，只检查需求完整性、跨仓库契约、数据流、发布顺序和组合冲突，不重复局部检查。

## 执行静态审查

平台支持独立 reviewer 时只启用一个，并仅传递任务预期、适用规则、精确 diff 和必要源码上下文；不传实现者的自我辩护或预设答案。平台不支持时在当前上下文审查，并注明独立性限制。

只记录满足全部条件的问题：

- 差异引入具体正确性、安全、数据或明确契约问题；
- 从代码、调用方、规则或场景可证明触发路径可达；
- 能说明实际后果、精确位置和最小修复方向。

忽略纯风格、无证据的未来风险、契约外输入、可选重构、机械工具问题和“更保险”的防御性建议。只使用：P0 安全/不可逆数据/核心可用性；P1 主要业务、权限、公开契约或跨 Track 错误；P2 受支持且可达的局部边界错误。

## 维护审查记录

使用 `scripts/review.py` 管理 Task `record.path` 指向的 `review.md`，不要直接编辑。每个 finding 使用稳定 ID，记录 priority、location、scenario、evidence、impact、minimal fix、decision 和 resolution。

无 finding 时记录“未发现代码级问题”，不得声称测试或行为验证通过，然后完成当前 Review Task，并把最终 `review.md` 发布为 `ars.review@1` ArtifactRef。

有 finding 时一次性展示完整清单，由用户批量决定 accepted/rejected。存在 accepted 时，使用 Noctis Exec `orchestration splice` 的 `sourceArtifacts` 原子完成当前 Review Task并发布 `review` Artifact，再插入 Fix 与一次新 Review Task；原有 pending 后继改为依赖新 Review。全部 rejected 时通过普通 finish 发布同一 Artifact 并完成当前 Task。Review 不自行修复。

## 定向复核

修复后的新 Review Task 只复核已接受 finding 对应的 Fix diff，并检查该 diff 直接造成的回归。不要重扫旧代码或提出无关问题。

全部解决时标为 resolved 并完成 Task。仍未解决或产生直接回归时记录证据并阻塞；一次修复后只复核一次，不自动插入第二轮 Fix/Review，需要继续处理时交由用户决定。

审查记录的本地检查点使用 `docs:` 和 `Noctis-Task: <task-id>` trailer。未经明确授权不修改业务代码、不测试、不验证、不推送、不部署。
