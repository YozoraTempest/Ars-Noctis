# Runtime Operations

只在执行、扩展或恢复 Run 时加载本文件。以下命令均使用 `scripts/noctis.py`；Git 中 `.noctis/runs/<run-id>/` 是唯一持久事实。

## 创建与推进

```powershell
python scripts/noctis.py plan-check --plan <noctis-plan.json>
python scripts/noctis.py run-create --project <project> --plan <noctis-plan.json>

git add .noctis/runs/<run-id>
git commit -m "chore(noctis): 保存运行检查点"

python scripts/noctis.py task-claim --project <project> --run-id <uuid> --task-id <task-id>
python scripts/noctis.py task-finish --project <project> --run-id <uuid> --task-id <task-id> --claim-id <uuid> --expected-revision <n> --result <noctis-result.json>

git add .noctis/runs/<run-id>
git commit -m "chore(noctis): 记录任务结果"
```

Plan 创建时已有明确授权的 requirement 可传给 `run-create --grant <id> --grant-reason <reason>`。Noctis 只记录标识和理由，不判断其风险；调用方仍负责真实授权边界。

领取要求 Run 当前 JSON 已提交。`task-finish` 要求当前 HEAD 继承领取时 checkpoint，并返回需要提交的 Result/Event 路径。Noctis 不执行 executor、不提交、不推送，也不检查 opaque output 的领域正确性。

## 动态扩展

批量追加：

```powershell
python scripts/noctis.py extension-check --project <project> --run-id <uuid> --extension <extension.json>
python scripts/noctis.py run-extend --project <project> --run-id <uuid> --extension <extension.json> --expected-run-revision <n>
git add .noctis/runs/<run-id>
git commit -m "chore(noctis): 追加运行任务"
```

追加单个 Task：

```powershell
python scripts/noctis.py task-add --project <project> --run-id <uuid> --task <task.json> --origin-kind user-request --reason "用户新增验收任务" --expected-run-revision <n>
```

若 Task 使用新的 executor，同时传 `--executor <executor.json>`。`extension-check` 返回当前 `run_revision`、新增项和 `missing_grants`。`run-extend` 使用 optimistic concurrency；revision 冲突时重新读取 Run、合并新变化，再提交新的 Extension。

不要把新增目标伪装成 retry，也不要修改 Plan。Retry 表示同一 Task 的同一 request 再尝试；Extension 表示 Run 获得了新的工作。

## 查看与恢复

```powershell
python scripts/noctis.py run-show --project <project>
python scripts/noctis.py run-show --project <project> --run-id <uuid>
python scripts/noctis.py run-events --project <project> --run-id <uuid> --limit 100
python scripts/noctis.py recover --project <project> --run-id <uuid>
```

`recover` 严格重放 Git JSON，然后清空整个 worktree 的本机 claim 和活动授权缓存。已有合法 Result/Event 的 Task 保持终态；没有持久 Result 的执行现场回到最后的持久状态。新 clone 必须重新激活当前机器授权。

## Requirement

```powershell
python scripts/noctis.py grant --project <project> --run-id <uuid> --requirement <id> --reason <reason>
python scripts/noctis.py revoke --project <project> --run-id <uuid> --requirement <id> --reason <reason>
```

首次 grant 会追加持久 Run Event 并激活本机授权；已记录 requirement 在新机器再次 grant 时只激活本机缓存。Revoke 追加事件并立即移除本机授权。每个事件都必须提交后才成为跨机器事实。

## 重试与取消

```powershell
python scripts/noctis.py task-retry --project <project> --run-id <uuid> --task-id <id> --expected-revision <n> --reason <reason>
python scripts/noctis.py task-cancel --project <project> --run-id <uuid> --task-id <id> --expected-revision <n> --reason <reason>
```

本机存在 claim 且 Task 有 requirements 时，重试或取消还需 `--acknowledge-requirements`。先核对 executor 可能已经产生的外部行为；该开关不会回滚它们。取消会级联到 pending 后继，但不会删除历史。

不要手工编辑 `.noctis/runs/`，不要复制 `.git/noctis/cache.sqlite3`，不要把工作树干净或外部对象存在等同于 Task 已完成。
