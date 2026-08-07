# 推进执行生命周期

## 进入记录

首次执行使用刚创建的记录；无上下文恢复通过 `resume-workflow` 接收 Continue 返回的 ExecutionEntry。无论中断、模型或 Agent 来源如何，都先 `orchestration inspect` 读取最新 revision，不信任旧内存状态。

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
3. 把 ExecutionEntry v2 的 `resolvedInputs` 交给 executor；文档型输入通过来源 provider 和 record 句柄读取，不直接改写原生 Markdown。
4. 使用 Task `record.path` 调用所属 Ars 的文档工具。
5. executor 返回后重新 inspect；根据事实用 `finish --artifacts` 写入 `completed` 或 `blocked`、outcome 和 ArtifactRef。completed 时缺少 required output 必须失败。

不要读取项目注册表替换既有 Task 快照，也不要直接打开其他 Skill 的 `SKILL.md`。

## 文档与检查点

根据 provider manifest，在能力实际启用时用 `extend insert/upsert/sync` 持久加入 augmentation。不要修改源模板或覆盖未知 extension。

执行 Skill 的业务提交归对应 Task 和目标仓库；编排记录使用独立 `docs:` 检查点。不要把多个仓库的业务改动混入一个提交。
