# Public Contracts

只在创建 Plan 或组装 Task/Result 时加载本文件。所有契约都是严格 JSON；未知字段和非法状态会被拒绝。

## Catalog v1

`catalog` 返回 `ars.catalog/v1`，其中每个 provider 包含 `id`、`version`、发现时的 `source` 和 capability 列表。同 ID 的不同目录视为歧义。创建 Run 时只快照被 Plan 使用的 provider ID、版本和 capability，不持久化安装路径。

## Plan v1

```json
{
  "schema": "ars.plan/v1",
  "title": "实现并审查配置加载修复",
  "objective": "修复空配置崩溃并给出独立审查结论",
  "workspaces": [{"id": "main", "root": "."}],
  "tasks": [
    {
      "id": "implement-fix",
      "provider": "implement",
      "capability": "code.change",
      "workspace": "main",
      "needs": [],
      "instructions": "修复空配置崩溃，保留现有兼容行为。",
      "inputs": [],
      "acceptance": ["空配置返回默认值", "现有测试通过"],
      "effects": ["command.execute", "git.commit", "workspace.write"]
    },
    {
      "id": "review-fix",
      "provider": "code-review",
      "capability": "code.review",
      "workspace": "main",
      "needs": ["implement-fix"],
      "instructions": "审查本 Run 的实现产物。",
      "inputs": [],
      "acceptance": ["所有发现包含证据和优先级"],
      "effects": []
    }
  ]
}
```

Workspace root 必须是项目根目录内的相对 POSIX 路径。Task ID 在一个 Run 内唯一；`needs` 必须形成无环图。声明 `workspace.write` 的 Task 必须同时声明 `git.commit`，使完成结果可以被新 clone 验证。Noctis 自动把直接前置 Task 的 Artifact 解析为后继 Task 输入，不传递聊天历史。

## Artifact v1

Artifact 固定包含 `id`、`type`、`media_type`、`locator`、`digest`。`digest` 为 `null` 或 `sha256:<hex>`。

Locator 四选一：

```json
{"kind": "workspace", "workspace": "main", "path": "reports/review.json"}
{"kind": "git", "workspace": "main", "commit": "0123456789abcdef0123456789abcdef01234567"}
{"kind": "uri", "uri": "https://example.test/evidence/123"}
{"kind": "inline", "value": {"verdict": "passed"}}
```

Workspace 路径必须精确指向当前存在的文件或目录，不允许绝对路径或 `..`。Git locator 必须使用当前仓库可解析的完整 40 位 commit。HTTP(S) URI 只验证结构，不声称远端可达。

## Task v1

`task-claim` 生成 Task，不手工构造。它包含 `run_id`、`task_id`、本机 `claim_id`、`attempt`、持久 `revision`、固定 provider 版本、绝对 workspace、当前 Git `checkpoint.commit`、resolved inputs、acceptance、已授权 effects 和稳定 `idempotency_key`。

每个 resolved input 使用 `{"source": ..., "artifact": ...}`。Plan 显式输入的 source 为 `{"kind": "plan"}`；前置 Task 产物的 source 为 `{"kind": "task", "run_id": "...", "task_id": "..."}`。不要只凭 Artifact ID 猜测生产者。

## Result v1

```json
{
  "schema": "ars.result/v1",
  "run_id": "<uuid>",
  "task_id": "implement-fix",
  "claim_id": "<uuid>",
  "attempt": 1,
  "status": "completed",
  "summary": "修复并完成定向测试。",
  "artifacts": [
    {
      "id": "implementation-commit",
      "type": "code.change",
      "media_type": "application/vnd.git.commit",
      "locator": {"kind": "git", "workspace": "main", "commit": "0123456789abcdef0123456789abcdef01234567"},
      "digest": null
    }
  ],
  "evidence": [],
  "effects": [
    {
      "type": "workspace.write",
      "target": "main",
      "receipt": "src/config.py",
      "idempotency_key": "<run-id>/implement-fix"
    },
    {
      "type": "git.commit",
      "target": "main",
      "receipt": "0123456789abcdef0123456789abcdef01234567",
      "idempotency_key": "<run-id>/implement-fix"
    }
  ]
}
```

`status` 只能是 `completed`、`failed`、`blocked`、`input-required`。完成结果至少提供一个 Artifact 或 evidence。Effect receipt 只能记录 Task 已声明且当前机器已授权的实际副作用。完成 `workspace.write` 时，workspace 必须无未提交内容，Result 必须提供指向当前 workspace HEAD 的 `git.commit` receipt 和同 SHA 的 Git Artifact；`task-finish` 随后写入 Result 与 Event，宿主再把它们提交为状态检查点。

## Git-backed Run and Event

每个 Run 使用以下公开持久布局：

```text
.ars/runs/<run-id>/
├── run.json
├── plan.json
├── events/<event-id>.json
└── results/<task-id>/attempt-<n>.json
```

`run.json` 使用 `ars.run-record/v1`，保存 Run ID、不可变 Plan 引用、provider 快照、初始授权记录、创建提交和 durable ref。每个 `ars.event/v1` 是独立追加文件，包含 UUID、Run/Task ID、事件类型、`previous_revision`、`revision`、UTC 时间和类型相关 data。相同 Task revision 出现多个事件、revision 不连续、Result 缺失或事件与 Result 状态不一致时，恢复必须失败。

`run-show` 返回 `ars.run-list/v1` 或 `ars.run/v1`。Run 状态由 Plan、Result 与 Event 重放派生；`ready` 只包含全部直接依赖均 completed 的 pending Task。`working`、claim 和当前机器授权来自当前 worktree Git 元数据目录中的 Noctis SQLite，不是持久事实。`run-events` 返回按新到旧排序的 `ars.event-list/v1`。Provider 不得直接修改 `.ars/runs/`。
