# 推进执行生命周期

## 进入记录

`execute-workflow` 始终接收 `entry` 从 `noctis.md` 生成的 ExecutionEntry：首次执行在物化后生成，断点恢复由 Continue 扫描后生成。无论中断、模型或 Agent 来源如何，都先 `orchestration inspect` 读取最新 revision，不信任旧内存状态。

按记录状态处理：

- `pending` 且 ready：确认 required input 已解析，再用 `start` 原子领取。
- `active`：读取该 Task 的能力记录和目标工作树，继续尚未完成的 Step；提交或外部副作用是否发生不确定时阻塞，不盲目重放。
- `blocked`：只在阻塞条件有证据解除后用 `resume`。
- `completed`：不再执行。

多个 ready Task 可以并行。revision 冲突时重新 inspect；只有原目标仍满足状态和依赖条件才继续。

## 分层调度

Task 记录直接调度其唯一 Task。Unit 从 ready 中选择依赖已完成的 Task。Work 启动一个 Unit item 后进入其 `path` 指向的 Unit 记录；只有子 Unit 完成后才完成对应 Work item。

每个 active Task：

1. 激活 binding 中 `before` support。
2. 通过平台 Skill 机制激活 executor；`on-request` support 仅在 executor 实际需要时激活。
3. 把 ExecutionEntry v2 的 `resolvedInputs` 交给 executor；`cardinality: one` 为单个解析结果，`cardinality: many` 为保留全部直接来源的非空数组。文档型输入通过各来源 provider 和 record 句柄读取，不直接改写原生 Markdown。
4. 使用 Task `record.path` 调用所属 Ars 的文档工具。
5. executor 返回 `ExecutorResult v1`；用 `orchestration apply-result --input` 校验并应用，不接受 executor 对 `noctis.md` 的直接写入。

`ExecutorResult v1` 固定包含以下字段，不允许扩展字段：

```json
{
  "version": 1,
  "task": "U01.T01",
  "status": "completed",
  "outcome": "实现已提交并登记",
  "artifacts": {},
  "commits": ["<executor-owned-commit>"],
  "recovery": null
}
```

- `completed | blocked` 由 Exec 原子写入当前 active Task；completed 必须提供全部 required output。
- 每个 Task Skill 的 completed 结果至少包含一个有序的自有提交；Implement/Fix 提交代码与 implementation 记录，Review 提交 review 记录，Verify 提交 verification 记录。`recovery-requested` 也必须先提交其证据记录。
- `deferred` 使用 null outcome、空 artifacts/commits 且不迁移状态。
- `recovery-requested` 保持源 Task active，必须提供 required output；Review 使用 `review-findings`，Verify 使用 `verification-failures`，并在 `recovery.evidenceIds` 提供稳定证据 ID。此时回到 Noctis Exec 主文件，按恢复动作路由；只有 Exec 构造并执行 splice，executor 不得提供 Task 图。

应用 completed 或 blocked 结果后严格按此顺序推进：

1. 重新 inspect，确认写入后的 revision、Task 状态和 ready 集合。
2. 根据 Artifact Binding，把来源 Artifact 和稳定 ID 通过目标 provider 的公开文档工具或 augmentation 写入需要协调的其他 Skill 文档；只写关联、输入、决策或恢复上下文，不复制或改写来源事实。
3. 暂存所属 `noctis.md` 和本轮跨 Skill 协调产生的文档修改，创建独立 `docs:` 编排检查点并附 `Noctis-Task: <task-id>` trailer；不得纳入 executor 已提交的源文档、业务代码或无关改动。
4. 检查点成功后，从 ready 中选择后继；唯一 ready Task 直接 start，多个 ready Task 按既有并行授权领取或交互选择，不重新规划依赖图。
5. start 写入也创建独立编排检查点，再把新的 ExecutionEntry 交给后继 executor。

检查点失败时不要开启后继；保留已完成状态，报告 Git 阻塞并从该 revision 恢复。executor 的代码或自有文档提交与 Exec 的编排检查点是两个职责和两类提交。

每次退出 `execute-workflow` 时，把当前根 `noctis.md` 作为 `noctis.record@3` orchestration Artifact 返回；revision 使用最新文档 revision。

不要读取项目注册表替换既有 Task 快照，也不要直接打开其他 Skill 的 `SKILL.md`。

## 文档与检查点

根据 provider manifest，在能力实际启用时用 `extend insert/upsert/sync` 持久加入 augmentation。不要修改源模板或覆盖未知 extension。

执行 Skill 的代码和来源事实文档提交归对应 Task 和目标仓库；Exec 独占编排与跨 Skill 协调的 `docs:` 检查点。Exec 可以通过公开 Interface 修改 `implementation.md`、`review.md` 或 `verification.md` 中由目标 Skill 声明的协调位置，但不得直接编辑其私有结构、改写来源事实或冒充该 Skill 的判定。executor 不提交 `noctis.md`。

Git 证据由需要提交的 executor 使用其对账脚本判定，不替代通用状态机：原工作树存在未提交变更时继续当前 active Task；存在可达的 `Noctis-Task: <task-id>` 提交而记录未完成时，核对范围后补记并推进；记录已完成但提交不可达时阻塞。切换工作树或机器后，无法获取未提交内容，只能从最后一个可达且已登记的提交检查点重新执行；远端机器必须先通过 fetch、bundle 等方式取得提交。
