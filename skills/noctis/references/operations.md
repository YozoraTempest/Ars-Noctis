# Runtime Operations

只在执行或恢复 Run 时加载本文件。Git 中 `.ars/runs/<run-id>/` 是唯一持久事实；当前 worktree Git 元数据目录下的 `noctis/cache.sqlite3` 只保存本机 claim 与当前机器授权，天然不会进入提交。

## 创建和推进

```powershell
# 发现 provider 并校验 Plan
python scripts/noctis.py catalog --skills-root <skills-root>
python scripts/noctis.py plan-check --project <project> --plan <plan.json> --skills-root <skills-root>

# 创建 Run；workspace.write 必须和 git.commit 一起请求与授权
python scripts/noctis.py run-create --project <project> --plan <plan.json> --skills-root <skills-root> --grant workspace.write --grant git.commit --grant command.execute --grant-reason "用户要求实现、提交并运行测试" --confirm-high-risk

# 宿主在明确授权下提交并推送 CLI 返回的 checkpoint 文件；Noctis 不自行执行 Git 写入
git add .ars/runs/<run-id>
git commit -m "chore(noctis): 保存运行检查点"
git push

# 领取 Task；Run JSON 和目标 workspace 必须已提交且无本地改动
python scripts/noctis.py task-claim --project <project> --run-id <uuid> --task-id <task-id>

# Provider 完成 workspace.write 时先提交全部产物、确认 workspace 清洁，并在 Result 中返回同 SHA 的 Git Artifact 与 git.commit receipt
python scripts/noctis.py task-finish --project <project> --run-id <uuid> --task-id <task-id> --claim-id <uuid> --expected-revision <n> --result <result.json>

# 再提交并推送 task-finish 返回的 Result/Event 路径，之后才能领取后继 Task
git add .ars/runs/<run-id>
git commit -m "chore(noctis): 记录任务结果"
git push
```

每次 `task-finish`、`task-retry`、`task-cancel`、`grant` 或 `revoke` 都返回 `checkpoint_required`。这些文件与对应业务产物进入可获取分支后，才构成跨机器恢复边界。CLI 的 `checkpoint.pushed` 只依据本地 upstream tracking ref 判断；没有执行 fetch 时不能把它当作远端实时证明。

## 查看和克隆恢复

```powershell
python scripts/noctis.py run-show --project <project>
python scripts/noctis.py run-show --project <project> --run-id <uuid>
python scripts/noctis.py run-events --project <project> --run-id <uuid> --limit 100

# 新 clone 或明确放弃本机执行现场时重建空缓存
python scripts/noctis.py recover --project <project> --run-id <uuid>
```

`recover` 丢弃本机 claim 与活动授权，再从严格 JSON 重放状态。已有合法 Result/Event 的 Task 保持终态；没有持久 Result 的旧执行现场不恢复，对应 Task 按最后提交状态重新成为 `pending`。克隆后 effect-free Task 可直接领取；需要副作用的 Task 必须重新获得当前机器授权。

## 授权、失败和取消

新增授权调用 `grant --effect <effect> --reason <evidence>`。`git.commit`、`git.push`、`network.write`、`deployment` 和 `destructive` 还要求 `--confirm-high-risk`；该标记只是防误操作，不能替代用户授权。首次加入 Run 的 effect 会追加 Grant 事件；新 clone 对已有 effect 再次授权时只激活本机缓存，`checkpoint_required` 为空，不制造重复事件。

用户撤回授权时调用 `revoke --effect <effect> --reason <evidence>`。它立即清除本机授权并追加事件；已经被 provider 使用的副作用不会自动撤销。

恢复异常时遵循：

1. 当前机器存在 working claim 时，先检查 Artifact、提交和外部 effect receipt。
2. 已完成但尚未执行 `task-finish` 时，使用原 claim 提交 Result；如果 claim 已随旧机器丢失，则依据当前证据重新领取或返回 blocked，不伪造旧 claim。
3. 无法证明完成且确需重试时调用 `task-retry --expected-revision <n> --reason <reason>`；可能已有副作用时增加 `--acknowledge-effects`。
4. `failed`、`blocked`、`input-required` 可在原因解决后重试；`completed` 和 `canceled` 不可重开。
5. 取消不会撤销副作用；取消有副作用可能性的本机 claim 时必须传入 `task-cancel --acknowledge-effects`。

不要手工编辑 `.ars/runs/`、不要把本机缓存复制为项目状态，也不要凭工作树干净、文件存在或旧聊天声称来伪造完成状态。
