# Noctis Runtime Binding

只在需要配置 Codex App profile、模型、推理强度或 Agent 模式时加载本文件。

## Codex App Runtime

个人 profile 默认保存在 `<git-common-dir>/ars-noctis/app-profile.json`，跨同一仓库的 worktree 持久存在，但不进入工作树或 Git 历史。初始化内容为空，表示默认继承主 Agent：

```json
{
  "schema": "ars.app-profile/v1",
  "skills": {}
}
```

按 Skill 保存偏好：

```powershell
python scripts/ars_noctis.py app-profile-init --project <project>
python scripts/ars_noctis.py app-profile-set --project <project> --skill implement --agent-mode multi --model gpt-5.6-sol --reasoning-effort high
python scripts/ars_noctis.py app-profile-show --project <project>
```

`--clear-agent-mode`、`--clear-model` 和 `--clear-reasoning-effort` 删除对应偏好，使解析继续回退到下一层。`model` 与 `reasoning_effort` 可显式写 `inherit`，表示在该层终止回退并继承主 Agent。`agent_mode` 只接受 `single` 或 `multi`。

Run 配置使用 `ars.app-run-config/v1`，当前用户提示生成的最高优先级配置使用 `ars.app-explicit-config/v1`；两者都严格包含 `default`、`providers` 和 `tasks`，每个配置值可按需省略字段：

```json
{
  "schema": "ars.app-run-config/v1",
  "default": {"agent_mode": "single", "model": "inherit"},
  "providers": {"code-review": {"agent_mode": "multi", "model": "gpt-5.6-terra"}},
  "tasks": {"verify-change": {"model": "gpt-5.6-sol", "reasoning_effort": "high"}}
}
```

每个字段独立按以下顺序取第一个已声明值：

```text
显式配置（Task > Provider > default）
  > 仓库 profile 的 Skill 偏好
  > Run 配置的 Task
  > Run 配置的 Provider
  > Run 配置的 default
  > 主 Agent（model/reasoning_effort=inherit，agent_mode=single）
```

解析结果连同来源写入 executor snapshot。ID 包含完整 snapshot digest 的短前缀，因此同 provider/version 使用不同模型时不会碰撞。模型名和推理强度不硬编码在 adapter；Codex App 派发前必须用当前宿主实际公开的可用组合校验。显式请求不可用时阻塞，不静默替换。

`single` 由当前 Agent 执行，只能使用当前模型和推理强度；`multi` 由当前 Agent 用干净上下文的 subagent 执行。默认使用 `single + inherit`，模式必须来自上述配置，不由 adapter 猜测。宿主没有 subagent 能力时 multi Claim 阻塞，不回退为独立 CLI 对话。

## App Dispatch

领取 Claim 后，Codex App 主 Agent 根据当前任务能力构造临时宿主快照。该文件只用于本次派发，不写入 Noctis 状态：

```json
{
  "schema": "ars.app-host/v1",
  "current_agent": {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "high",
    "explicit_skills": ["ars", "implement"]
  },
  "subagents": {
    "available": true,
    "models": [
      {"id": "gpt-5.6-sol", "reasoning_efforts": ["low", "medium", "high"]},
      {"id": "gpt-5.6-terra", "reasoning_efforts": ["low", "medium", "high"]}
    ]
  }
}
```

模型 ID 和推理强度来自当前宿主，不是 adapter 的永久允许列表。`subagents.models` 列出允许显式覆盖的模型及推理强度；`spawn` 省略模型时使用宿主原生继承，不要求主模型出现在该覆盖列表。`explicit_skills` 只列出用户在当前 App 任务中显式选择的 Skills，不把可发现或由 Agent 推测的 Skill 算进去。当前 Agent 无法可靠获知自身值时可写 `null`；冻结配置要求具体值时，dispatch 会阻塞。

```powershell
python scripts/ars_noctis.py claim-dispatch --project <project> --claim <noctis-claim.json> --host <app-host.json> > <app-dispatch.json>
```

输出 `ars.app-dispatch/v1`。`ready/single` 的 `spawn` 为 `null`，且 provider 必须存在于 `explicit_skills`；当前 Agent 按 `invocation` 执行已显式选择的 Skill。`ready/multi` 的 `spawn` 可直接映射到 Codex App 的 subagent 调用。`fork_turns` 固定为 `none`，确保 provider 只接收 `$<provider>` 和完整 Task；继承项不会出现在 `spawn` 中。`blocked` 输出稳定 blocker code，调用方不得自行降级模式或模型。Adapter 只生成并校验派发决策，不启动 Agent。

当前 App 无法在同一回合中程序化激活另一个显式 Skill。组合 Run 使用 `single` 时，用户必须同时显式选择 `$ars` 和 provider；不希望 provider 内容进入主上下文时，将该 provider 配置为 `multi`。

dispatch 阻塞不会自动改变 Noctis 持久状态，也不能修改 Claim 中已冻结的 executor。停止执行并直接取消旧 Task；`task-cancel` 会清除该 Task 的本机 Claim：

```powershell
python <noctis>/scripts/noctis.py task-cancel --project <project> --run-id <uuid> --task-id <id> --expected-revision <n> --reason "App runtime binding is unavailable"
```

若 Task 有 requirements，取消时按 Noctis 提示核对潜在外部行为并增加 `--acknowledge-requirements`。提交取消 checkpoint 后，使用更正后的 App 配置创建新 Run；若仍需保留现有 Run 历史，则通过 Extension 增加使用新 executor snapshot 的替代 Task。Retry 不会改变冻结绑定。
