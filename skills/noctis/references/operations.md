# Runtime Operations

只在执行、扩展或恢复 Run 时加载本文件。以下命令使用 `scripts/noctis.py`；Git 中 `.noctis/runs/<run-id>/` 是唯一持久事实。

## 创建与推进

```powershell
python scripts/noctis.py plan-check --plan <noctis-plan.json> --preview
# 展示 preview 和调用方识别的高成本操作，等待用户确认
python scripts/noctis.py run-create --project <project> --plan <noctis-plan.json>

git add .noctis/runs/<run-id>
git commit -m "chore(noctis): 保存运行检查点"

python scripts/noctis.py task-claim --project <project> --run-id <uuid> --task-id <task-id>
python scripts/noctis.py task-finish --project <project> --run-id <uuid> --task-id <task-id> --claim-id <uuid> --expected-revision <n> --result <noctis-result.json>

git add -- <task-finish 返回的 checkpoint_required 路径>
git commit -m "chore(noctis): 记录任务结果"
```

`preview` 不包含 opaque request 或 executor snapshot。只在用户确认已展示的 Plan 后调用 `run-create`。已有明确授权的 requirement 可传给 `run-create --grant <id> --grant-reason <reason>`；Noctis 不判断其含义。领取要求 Run JSON 已提交，`task-finish` 要求当前 HEAD 继承领取时 checkpoint。

## 动态扩展

批量追加：

```powershell
python scripts/noctis.py extension-check --project <project> --run-id <uuid> --extension <extension.json>
python scripts/noctis.py run-extend --project <project> --run-id <uuid> --extension <extension.json> --expected-run-revision <n>
git add -- <run-extend 返回的 checkpoint_required 路径>
git commit -m "chore(noctis): 追加运行任务"
```

追加单个 Task：

```powershell
python scripts/noctis.py task-add --project <project> --run-id <uuid> --task <task.json> --origin-kind user-request --reason "用户新增验收任务" --expected-run-revision <n>
```

若 Task 使用新的 executor，同时传 `--executor <executor.json>`。`extension-check` 返回当前 `run_revision`、新增项和 `missing_grants`。revision 冲突时重新读取 Run，在最新状态上重新提交 Extension；不同 clone 的冲突不会自动合并。

不要把新增目标伪装成 retry，也不要修改 Plan。Retry 表示同一 Task 的同一 request 再尝试；Extension 表示 Run 获得了新的工作。

## 查看与恢复

```powershell
python scripts/noctis.py run-show --project <project>
python scripts/noctis.py run-show --project <project> --run-id <uuid>
python scripts/noctis.py run-events --project <project> --run-id <uuid> --limit 100
python scripts/noctis.py recover --project <project> --run-id <uuid>
```

已有 Run 优先使用 `run-show`，不要重新规划。`recover` 严格重放 Git JSON 并清空本机 claim 和活动授权；新 clone 必须重新激活当前机器授权。

## Requirement

```powershell
python scripts/noctis.py grant --project <project> --run-id <uuid> --requirement <id> --reason <reason>
python scripts/noctis.py revoke --project <project> --run-id <uuid> --requirement <id> --reason <reason>
```

首次 grant 会追加持久 Event 并激活本机授权；新机器再次 grant 只激活本机缓存。每个事件提交后才成为跨机器事实。

## 重试与取消

```powershell
python scripts/noctis.py task-retry --project <project> --run-id <uuid> --task-id <id> --expected-revision <n> --reason <reason>
python scripts/noctis.py task-cancel --project <project> --run-id <uuid> --task-id <id> --expected-revision <n> --reason <reason>
```

本机存在 claim 且 Task 有 requirements 时，重试或取消还需 `--acknowledge-requirements`。该开关只确认已核对外部行为，不会回滚它们。取消会级联到 pending 后继，但不会删除历史。

不要手工编辑 `.noctis/runs/`，不要复制 `.git/noctis/cache.sqlite3`，不要把工作树干净或外部对象存在等同于 Task 已完成。
