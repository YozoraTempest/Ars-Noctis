# Public Contracts

只在创建或审查 Noctis JSON 时加载本文件。所有对象都是严格 JSON；未知字段、NaN、重复 ID 和非法状态都会被拒绝。

## Executor

```json
{
  "id": "example:worker:1",
  "kind": "example",
  "snapshot": {"schema": "example.executor/v1", "endpoint": "local"},
  "digest": "sha256:<64-lowercase-hex>"
}
```

`id` 和 `kind` 是稳定标识。`snapshot` 是 adapter 定义的任意严格 JSON。`digest` 可为 `null`；不为 `null` 时必须等于 snapshot 的 canonical JSON SHA-256。Noctis 保存并回传快照，不解释其中字段。

## Plan v1

```json
{
  "schema": "noctis.plan/v1",
  "title": "Transform and inspect data",
  "objective": "Produce one transformed value and inspect it.",
  "executors": [
    {
      "id": "example:worker:1",
      "kind": "example",
      "snapshot": {"schema": "example.executor/v1"},
      "digest": null
    }
  ],
  "tasks": [
    {
      "id": "transform",
      "needs": [],
      "executor": "example:worker:1",
      "request": {"operation": "transform", "value": 42},
      "requirements": ["command.execute"]
    },
    {
      "id": "inspect",
      "needs": ["transform"],
      "executor": "example:worker:1",
      "request": {"operation": "inspect"},
      "requirements": []
    }
  ]
}
```

Plan 至少包含一个 executor 和一个 Task。Task ID 唯一，executor 必须存在，`needs` 必须形成 DAG。`request` 可以是任意严格 JSON。`requirements` 是去重的稳定标识列表；含义和授权依据由调用方定义。

首次 Git checkpoint 同时封存 `run.json` 和 `plan.json`。之后只能追加 Event/Result，不能修改初始 Plan。

## Extension v1

```json
{
  "schema": "noctis.extension/v1",
  "origin": {
    "kind": "user-request",
    "summary": "User requested an additional acceptance check.",
    "reference": null
  },
  "executors": [],
  "tasks": [
    {
      "id": "acceptance-check",
      "needs": ["transform"],
      "executor": "example:worker:1",
      "request": {"operation": "acceptance-check"},
      "requirements": ["browser.read"]
    }
  ]
}
```

`origin` 记录为何加入工作，`reference` 为可选字符串。`executors` 只需要包含 Run 中尚不存在的快照；重复的相同 executor 会被忽略，试图改变同 ID executor 会被拒绝。`tasks` 至少一个，不能重用已有 ID，也不能依赖 canceled Task。

Extension 通过 `run.tasks-added` 事件持久化，使用独立的 Run revision。Task 自身的 revision 不因其他 Task 或 Run 扩展而变化。

## Claim v1

`task-claim` 生成 Claim，不手工构造：

```json
{
  "schema": "noctis.claim/v1",
  "run_id": "<uuid>",
  "task_id": "inspect",
  "claim_id": "<uuid>",
  "attempt": 1,
  "revision": 0,
  "run_revision": 1,
  "executor": {"id": "example:worker:1", "kind": "example", "snapshot": {}, "digest": null},
  "request": {"operation": "inspect"},
  "dependencies": [
    {
      "task_id": "transform",
      "result": {
        "schema": "noctis.result/v1",
        "run_id": "<uuid>",
        "task_id": "transform",
        "claim_id": "<uuid>",
        "attempt": 1,
        "status": "completed",
        "summary": "Transformation completed.",
        "output": {"value": 42}
      }
    }
  ],
  "requirements": {"required": [], "granted": []},
  "checkpoint": {"commit": "<40-character-sha>"},
  "idempotency_key": "<run-id>/inspect"
}
```

每个直接依赖携带完整的持久 Noctis Result。Adapter 决定如何从前置 output 解析领域输入。Claim 只存在于当前 worktree 的 Git 元数据缓存；同一 Task 同时只能有一个本机 claim。

## Result v1

```json
{
  "schema": "noctis.result/v1",
  "run_id": "<uuid>",
  "task_id": "inspect",
  "claim_id": "<uuid>",
  "attempt": 1,
  "status": "completed",
  "summary": "Inspection completed.",
  "output": {"schema": "example.result/v1", "verdict": "passed"}
}
```

`status` 只能是 `completed`、`failed`、`blocked` 或 `input-required`。`output` 是任意严格 JSON，包括 `null`。run、Task、claim、attempt 必须与本机 Claim 一致。Result 文件不可覆盖；对应 Event ID 等于 claim ID，Event 类型必须和 Result 状态一致。

## Run and Event

```text
.noctis/runs/<run-id>/
├── run.json
├── plan.json
├── events/<event-id>.json
└── results/<task-id>/attempt-<n>.json
```

`noctis.run-record/v1` 保存创建提交、durable ref、初始 grants 与不可变 Plan 引用。`noctis.event/v1` 支持：

- Run：`run.granted`、`run.revoked`、`run.tasks-added`。
- Task：`task.completed`、`task.failed`、`task.blocked`、`task.input-required`、`task.retried`、`task.canceled`。

Run Event 使用连续 `run_revision`；每个 Task Event 使用该 Task 独立的连续 revision。同一 worktree 的 CLI mutation 使用本机 SQLite transaction 串行化校验与写入。不同 clone 合并后若在相同 previous revision 上出现两个 Event，或出现 Result 缺失、路径逃逸、状态不匹配，重放失败。
