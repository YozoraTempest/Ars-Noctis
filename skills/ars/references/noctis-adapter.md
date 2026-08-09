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
python scripts/ars_noctis.py plan-adapt --project <project> --plan <ars-plan.json> --skills-root <skills-root> > <noctis-plan.json>
```

`plan-adapt` 执行：

1. 严格校验 `ars.plan/v1`、workspace、Task DAG、provider capability 与 effect 上界。
2. 只为实际使用的 provider 创建 `ars.executor-snapshot/v1`。
3. 将 provider ID、版本和 capability 固定到 executor snapshot；不保存安装路径。
4. 将每个 Ars Task 变为 Noctis Task。`ars.binding/v1` 放入 opaque request，effects 映射为 Noctis requirements。

输出可直接交给 `noctis.py plan-check` 和 `run-create`。

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
python scripts/ars_noctis.py extension-adapt --project <project> --extension <ars-extension.json> --skills-root <skills-root> > <noctis-extension.json>
python <noctis>/scripts/noctis.py run-extend --project <project> --run-id <uuid> --extension <noctis-extension.json> --expected-run-revision <n>
```

Adapter 会携带扩展中使用的 provider 快照。Noctis 若已有完全相同的 executor 会去重；版本或快照改变时使用新的 executor ID，不修改旧快照。

## Claim and Result

```powershell
python <noctis>/scripts/noctis.py task-claim --project <project> --run-id <uuid> --task-id <id> > <noctis-claim.json>
python scripts/ars_noctis.py claim-adapt --project <project> --claim <noctis-claim.json> > <ars-task.json>

# 宿主按 ars-task.json 中固定的 provider 执行 Skill，得到 ars-result.json

python scripts/ars_noctis.py result-adapt --project <project> --claim <noctis-claim.json> --result <ars-result.json> > <noctis-result.json>
python <noctis>/scripts/noctis.py task-finish --project <project> --run-id <uuid> --task-id <id> --claim-id <uuid> --expected-revision <n> --result <noctis-result.json>
```

`claim-adapt` 要求 executor kind 为 `ars`、快照 digest 匹配、workspace 清洁，并验证 Plan 输入及前置 Ars Result 的 Artifact 证据。`result-adapt` 验证 Ars Result、实际 effect receipt、Git Artifact 和 workspace 清洁，再把完整 Ars Result 作为 opaque output 保存。

## Legacy Migration

旧运行不会被 Noctis 自动发现。先检出包含完整旧状态的分支，再执行：

```powershell
python scripts/ars_noctis.py migrate-run --project <project> --run-id <uuid>
git add .noctis/runs/<uuid>
git commit -m "chore(noctis): 迁移旧 Ars 运行"
```

迁移把 `ars.plan/v1`、catalog snapshot、`ars.event/v1` 和 `ars.result/v1` 转换为对应 Noctis 数据；原 `.ars/runs/<uuid>` 保留不动。迁移完成并提交前，不要领取新 Task。若旧事件、Result 或 workspace 证据不完整，先对账，不伪造终态。
