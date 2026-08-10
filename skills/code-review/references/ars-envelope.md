# Ars Provider Envelope v1

只在编写可组合 provider，或 provider 收到 `ars.task/v1` 时加载本文件。Envelope 使用严格 JSON；不要增加未声明字段。

## Task

先验证 `provider.id`、`provider.version` 和 `capability` 与当前 Skill 的 `ars.json` 一致，再执行 Task：

- 把 `run_id`、`task_id`、`claim_id`、`attempt` 和 `idempotency_key` 原样保留到 Result 或 effect receipt。
- 只在 `workspace.root` 内工作；`checkpoint.commit` 是领取 Task 时已封存的 Git 基线。
- `instructions` 定义本次工作，`acceptance` 定义完成条件。
- `inputs` 中每项包含 `source` 和已校验的 `artifact`；只消费当前 Task 或直接前置 Task 提供的输入。
- 只执行 `effects.granted` 中列出的副作用。缺少必要授权时返回 `blocked`，不要扩大目标或重放不确定的外部行为。

## Result

返回且只返回以下字段：

```json
{
  "schema": "ars.result/v1",
  "run_id": "copy task.run_id",
  "task_id": "copy task.task_id",
  "claim_id": "copy task.claim_id",
  "attempt": 1,
  "status": "completed",
  "summary": "Describe the actual outcome.",
  "artifacts": [],
  "evidence": [
    {
      "id": "outcome",
      "type": "execution.evidence",
      "media_type": "application/json",
      "locator": {"kind": "inline", "value": {"observed": true}},
      "digest": null
    }
  ],
  "effects": []
}
```

- `attempt` 原样复制 Task 的整数值。
- `status` 只能是 `completed`、`failed`、`blocked` 或 `input-required`。
- `completed` 至少提供一个 Artifact 或 evidence；其他状态也应在 `summary` 中说明原因和下一步。
- `artifacts` 表达业务产物，`evidence` 表达验证依据；两个列表分别保持 Artifact ID 唯一。

## Artifact

每个 Artifact 严格包含 `id`、`type`、`media_type`、`locator` 和 `digest`：

```json
{
  "id": "result",
  "type": "example.result",
  "media_type": "application/json",
  "locator": {"kind": "inline", "value": {"ok": true}},
  "digest": null
}
```

`id` 和 `type` 使用小写字母开头的稳定标识；每个点号或连字符后的分段也以小写字母开头，其余字符可为小写字母或数字。Locator 只使用以下一种精确结构：

- Workspace：`{"kind":"workspace","workspace":"<workspace-id>","path":"<relative-path>"}`。路径必须存在、不可逃逸；文件可附 `sha256:<64-lowercase-hex>` digest。
- Git：`{"kind":"git","workspace":"<workspace-id>","commit":"<40-lowercase-hex>"}`。Commit 必须在该 workspace 中可达。
- URI：`{"kind":"uri","uri":"https://example.test/resource"}`。只接受绝对 HTTP(S) URI。
- Inline：`{"kind":"inline","value":<strict-json>}`。

## Effect Receipt

只为实际发生的副作用返回 receipt：

```json
{
  "type": "command.execute",
  "target": "workspace-or-external-target",
  "receipt": "truthful command, commit, or external receipt",
  "idempotency_key": "copy task.idempotency_key"
}
```

- `type` 必须存在于 Task 的 `effects.granted`；`target` 和 `receipt` 必须非空并对应实际事实。
- `git.commit` 的 `target` 必须是 workspace ID，`receipt` 必须是该 workspace 当前 HEAD 的完整 SHA。
- 若完成的 Task 请求 `workspace.write`，Result 必须同时包含 `git.commit` receipt，以及指向同一 commit 的 Git Artifact。
