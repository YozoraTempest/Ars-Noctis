# Advanced Noctis Operations

只在动态扩展、低层 Claim/Result 调试或迁移旧 `.ars/runs` 时加载本文件。普通生命周期使用 `scripts/ars_host.py create|next|finish`。

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

Adapter 会携带扩展中使用的 provider 快照。Noctis 对完全相同的 executor 去重；版本或快照改变时使用新 ID，不修改旧快照。

## Claim and Result

以下命令只用于调试、迁移或由调用方自行保管 Claim 的集成：

```powershell
python <noctis>/scripts/noctis.py task-claim --project <project> --run-id <uuid> --task-id <id> > <noctis-claim.json>
python scripts/ars_noctis.py claim-dispatch --project <project> --claim <noctis-claim.json> --host <app-host.json> > <app-dispatch.json>

# 宿主执行 ready dispatch 指定的 provider Skill，得到 ars-result.json

python scripts/ars_noctis.py result-adapt --project <project> --claim <noctis-claim.json> --result <ars-result.json> > <noctis-result.json>
python <noctis>/scripts/noctis.py task-finish --project <project> --run-id <uuid> --task-id <id> --claim-id <uuid> --expected-revision <n> --result <noctis-result.json>
```

`claim-dispatch` 接受历史 `ars.executor-snapshot/v1` 和带 App runtime 的 v2，要求 executor kind 为 `ars`、快照 digest 匹配、workspace 清洁，并验证 Plan 输入及前置 Ars Result 的 Artifact 证据。`result-adapt` 验证 Ars Result、实际 effect receipt、Git Artifact 和 workspace 清洁，再把完整 Ars Result 作为 opaque output 保存。

## Legacy Migration

旧运行不会被 Noctis 自动发现。先检出包含完整旧状态的分支，再执行：

```powershell
python scripts/ars_noctis.py migrate-run --project <project> --run-id <uuid>
git add .noctis/runs/<uuid>
git commit -m "chore(noctis): 迁移旧 Ars 运行"
```

迁移把 `ars.plan/v1`、catalog snapshot、`ars.event/v1` 和 `ars.result/v1` 转换为对应 Noctis 数据；原 `.ars/runs/<uuid>` 保留不动。迁移完成并提交前不要领取新 Task。若旧事件、Result 或 workspace 证据不完整，先对账，不伪造终态。
