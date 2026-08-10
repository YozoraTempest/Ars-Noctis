# Noctis Adapter

只在 Ars 工作要进入 Noctis，或迁移旧 `.ars/runs` 时加载本文件。Adapter 位于 `scripts/ars_noctis.py`，只使用 Ars Skill 内部实现；它不按固定路径导入 Noctis。

## 依赖边界

```text
ars.json + ars.plan/v1
        |
        v
  Ars adapter  <---->  Noctis public JSON
        |
        v
ars.task/v1 + ars.result/v1
```

Noctis Core 不发现 provider，不知道 capability、workspace、Artifact 或 effect。Adapter 必须在数据进入 Core 前校验并冻结这些语义，在 Claim 离开 Core 和 Result 返回 Core 时再次校验边界。

## Plan

```powershell
python scripts/ars_noctis.py catalog --skills-root <skills-root>
python scripts/ars_noctis.py app-profile-init --project <project>
python scripts/ars_noctis.py plan-adapt --project <project> --plan <ars-plan.json> --skills-root <skills-root> --run-config <app-run-config.json> --explicit-config <app-explicit-config.json> > <noctis-plan.json>
```

`plan-adapt` 执行：

1. 严格校验 `ars.plan/v1`、workspace、Task DAG、provider capability 与 effect 上界。
2. 只为实际使用的 provider/runtime 组合创建 executor；同一 provider 可因 Task 的模型或 Agent 模式不同产生多个 executor。
3. 将 provider ID、版本、capability 和 Codex App runtime 固定到 `ars.executor-snapshot/v2`；不保存安装路径。
4. 将每个 Ars Task 变为 Noctis Task。`ars.binding/v1` 放入 opaque request，effects 映射为 Noctis requirements。

输出可直接交给 `noctis.py plan-check` 和 `run-create`。

## Codex App Runtime

个人 profile 默认保存在 `<git-common-dir>/ars-noctis/app-profile.json`，因此跨同一仓库的 worktree 持久存在，但不进入工作树或 Git 历史。初始化内容为空，表示默认继承主 Agent：

```json
{
  "schema": "ars.app-profile/v1",
  "skills": {}
}
```

按 Skill 保存偏好：

```powershell
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

`single` 由当前 Agent 执行，只能使用当前模型/推理强度；`multi` 由当前 Agent 用干净上下文的 subagent 执行。默认使用 `single + inherit`，模式必须来自上述配置，不由 adapter 猜测。宿主没有 subagent 能力时 multi Claim 阻塞，不回退为独立 CLI 对话。

## App Dispatch

领取 Claim 后，Codex App 主 Agent 根据当前任务实际能力构造临时宿主快照。该文件只用于本次派发，不写入 Noctis 状态：

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

输出 `ars.app-dispatch/v1`。`ready/single` 的 `spawn` 为 `null`，且 provider 必须存在于 `explicit_skills`；当前 Agent 按 `invocation` 执行已显式选择的 Skill。`ready/multi` 的 `spawn` 可直接映射到 Codex App 的 subagent 调用。`fork_turns` 固定为 `none`，确保 provider 只接收 `$<provider>` 和完整 Task；继承项不会出现在 `spawn` 中。`blocked` 输出稳定 blocker code，调用方不得自行降级模式或模型。Python adapter 只生成并校验派发决策，不启动 Agent。

当前 App 没有在同一回合中程序化激活另一个显式 Skill 的公开宿主契约。因此组合 Run 使用 `single` 时，用户必须在当前任务同时显式选择 `$ars` 和 provider；若不希望 provider 内容进入主上下文，把该 provider 配置为 `multi`。

dispatch 阻塞不会自动改变 Noctis 持久状态，也不能修改 Claim 中已冻结的 executor。停止执行并直接取消旧 Task；`task-cancel` 会清除该 Task 的本机 Claim：

```powershell
python <noctis>/scripts/noctis.py task-cancel --project <project> --run-id <uuid> --task-id <id> --expected-revision <n> --reason "App runtime binding is unavailable"
```

若 Task 有 requirements，取消时按 Noctis 提示核对潜在外部行为并增加 `--acknowledge-requirements`。提交取消 checkpoint 后，使用更正后的 App 配置创建新 Run；若仍需保留现有 Run 历史，则通过 Extension 增加使用新 executor snapshot 的替代 Task。Retry 不会改变冻结绑定。

## Dynamic Extension

Ars 扩展输入：

```json
{
  "schema": "ars.noctis-extension/v1",
  "origin": {"kind": "user", "summary": "User requested verification.", "reference": null},
  "workspaces": [{"id": "main", "root": "."}],
  "tasks": [
    {
      "id": "verify-change",
      "provider": "verify",
      "capability": "behavior.verify",
      "workspace": "main",
      "needs": ["implement-change"],
      "instructions": "Verify the observable behavior.",
      "inputs": [],
      "acceptance": ["Return an evidence-backed verdict"],
      "effects": ["command.execute"]
    }
  ]
}
```

转换并追加：

```powershell
python scripts/ars_noctis.py extension-adapt --project <project> --extension <ars-extension.json> --skills-root <skills-root> --run-config <app-run-config.json> --explicit-config <app-explicit-config.json> > <noctis-extension.json>
python <noctis>/scripts/noctis.py run-extend --project <project> --run-id <uuid> --extension <noctis-extension.json> --expected-run-revision <n>
```

Adapter 会携带扩展中使用的 provider 快照。Noctis 若已有完全相同的 executor 会去重；版本或快照改变时使用新的 executor ID，不修改旧快照。

## Claim and Result

```powershell
python <noctis>/scripts/noctis.py task-claim --project <project> --run-id <uuid> --task-id <id> > <noctis-claim.json>
python scripts/ars_noctis.py claim-dispatch --project <project> --claim <noctis-claim.json> --host <app-host.json> > <app-dispatch.json>

# 宿主执行 ready dispatch 指定的 provider Skill，得到 ars-result.json

python scripts/ars_noctis.py result-adapt --project <project> --claim <noctis-claim.json> --result <ars-result.json> > <noctis-result.json>
python <noctis>/scripts/noctis.py task-finish --project <project> --run-id <uuid> --task-id <id> --claim-id <uuid> --expected-revision <n> --result <noctis-result.json>
```

`claim-adapt` 接受历史 `ars.executor-snapshot/v1` 和带 App runtime 的 v2，要求 executor kind 为 `ars`、快照 digest 匹配、workspace 清洁，并验证 Plan 输入及前置 Ars Result 的 Artifact 证据。`result-adapt` 验证 Ars Result、实际 effect receipt、Git Artifact 和 workspace 清洁，再把完整 Ars Result 作为 opaque output 保存。

## Legacy Migration

旧运行不会被 Noctis 自动发现。先检出包含完整旧状态的分支，再执行：

```powershell
python scripts/ars_noctis.py migrate-run --project <project> --run-id <uuid>
git add .noctis/runs/<uuid>
git commit -m "chore(noctis): 迁移旧 Ars 运行"
```

迁移把 `ars.plan/v1`、catalog snapshot、`ars.event/v1` 和 `ars.result/v1` 转换为对应 Noctis 数据；原 `.ars/runs/<uuid>` 保留不动。迁移完成并提交前，不要领取新 Task。若旧事件、Result 或 workspace 证据不完整，先对账，不伪造终态。
