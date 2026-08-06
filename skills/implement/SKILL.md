---
name: implement
description: 按明确工程请求或 Noctis Task/Subtask 实施功能，并处理用户已确认的审查或验证修复，维护轻量执行记录和本地检查点提交。仅在用户显式调用实现、修复或显式 workflow 包含 implement 时使用；不负责规划细节、代码审查、测试、行为验证、推送或部署。
---

# 实施

只实现功能或集中修复已确认问题。不要执行代码审查、测试或行为验收，也不要调用相应 Skill。

## 阶段守卫

在读取业务代码或修改文件前，先确定目标 Task 或 Subtask 及其当前状态。仅在 `status: active` 且 `stage` 为 `implement` 或 `fix` 时继续。

由 `$noctis` 调度，或与其他原子 Skill 一次性显式调用时，如果当前阶段不属于本 Skill，则返回接力状态 `deferred` 并把控制权交还调用链。不要把它作为错误或完成结论告知用户，不要提问，也不要修改任务状态或文件。任务记录尚不存在时，只有 workflow 首项为 `implement` 才能由本 Skill 创建；本 Skill 不是首项时同样返回 `deferred`。

单独调用本 Skill 且已有任务的阶段不匹配时，报告当前阶段和期望阶段后停止，不要代替其他 Skill 工作。

Noctis 管理的多阶段 workflow 需要推进时，相对于本文件读取 `../noctis/registry.yaml`，用下一 workflow 项的 `entry_stage` 更新任务。只读取注册元数据，不读取下一 Skill；注册表缺失、注册项不一致或当前 Skill 在 workflow 中不唯一时设置 `status: blocked` 并停止。单独执行且 workflow 只有本 Skill 时不依赖注册表。

## 选择执行单元

优先使用用户提供的 Task 或 Subtask 路径。否则相对于本文件定位 `scripts/scan_tasks.py`，使用 `--root <project-root> --status active --format json` 扫描，并选择 `stage` 为 `implement` 或 `fix` 的唯一叶子执行单元。存在多个候选时展示候选，不要猜测。

没有任务记录时，在修改生产文件前于 `Noctis/<primary-domain>/tasks/<yyyyMMdd>-<slug>/` 创建最小任务。仅调用 `$implement` 时 workflow 只包含 `implement`；用户显式列出多个原子 Skill 时使用该精确组合，不自行增加阶段。

```yaml
---
status: active
stage: implement
workflow:
  - implement
---
```

Task 表示整体业务目标，Subtask 表示仓库或独立执行边界，Step 只是执行单元内的可勾选动作。多仓库任务为每个仓库建立直接 Subtask，并在父 `tasks.md` 中记录仓库相对路径及阻塞关系。不要把 Step 当成独立提交或审查单位，也不要代替规划 Skill 扩写详细方案。

`tasks.md` 保存目标、Subtask、依赖和 Step。`implementation.md` 只保留 `Direction`、`Current` 和 `Completed` 三个章节。修改生产文件前，在 `Direction` 和 `Current` 中记录本次执行方向；完成后在 `Completed` 中记录结果、仓库和业务提交哈希。

`scenarios.md` 由规划或 verify 维护。只读取它理解目标，不得改写场景来适配实现。

## 实现功能

仅在 `status: active, stage: implement` 时执行：

1. 读取任务、场景、适用项目规则和相关代码，完成当前叶子执行单元的全部 Step。
2. 保留无关工作树修改，只暂存当前执行单元的业务差异。
3. 检查暂存差异后创建一个 Conventional Commits 本地实现提交，并附加：

   ```text
   Noctis-Task: <domain>/<yyyyMMdd>-<slug>[/<subtask>]
   ```

4. 勾选已完成 Step，在 `implementation.md` 记录实现摘要和提交哈希。适用时同步更新父 Task 的 Subtask 进度。
5. 按 workflow 推进：存在下一注册 Skill 时设为它的 `entry_stage`；没有下一项时设为 `status: completed` 并移除 `stage`。
6. 只提交受影响的 Noctis 记录，使用独立 `docs:` 检查点和相同 `Noctis-Task` trailer。

实现阶段不得因为“顺手验证”运行测试、构建、浏览器操作或静态审查。检查差异和 Git 状态不属于测试。

## 集中修复

仅在 `status: active, stage: fix` 且用户已经批量确认修复范围时执行。修复来源必须是 `review.md` 中标记为 `accepted` 的 finding，或 `verification.md` 中用户明确授权修复的失败场景。

不要重新判断 finding、扩展修复范围或加入防御性增强。一次处理当前批次的全部已确认项；每个受影响仓库只创建一个 `fix:` 业务提交，并在 `implementation.md` 记录提交哈希和对应 finding/scenario ID。

修复后，来源为审查 finding 时返回注册表 `review` 角色的 `entry_stage`。来源为验证且 workflow 包含该 review Skill 时也先返回审查；否则返回 `verification` 角色的 `entry_stage`。没有可用返回阶段时完成任务。随后创建独立 Noctis `docs:` 检查点。

## 谨慎恢复

恢复前读取 `tasks.md`、`implementation.md`、相关工作树以及匹配的 `Noctis-Task` 提交。原地继续尚未提交的工作；业务提交存在但缺少 Noctis 检查点时，先核实范围再补记录。证据不一致时设置 `status: blocked` 并报告，不要重写历史或静默修复状态。

未经单独授权，不要推送、部署或执行外部业务写入。
