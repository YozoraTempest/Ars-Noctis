---
name: implement
description: 按明确的工程请求或 Noctis 任务逐项实施，维护轻量执行记录，并为每个完成任务创建本地检查点提交。仅在用户明确调用并要求实施、任务跟踪和提交时使用；不隐含规划、测试、评审、推送或部署。
---

# 实施

每次只实施一个任务。保留工作树中的无关修改，并确保每个提交只覆盖当前任务。

## 从任务开始

1. 优先使用用户提供的任务路径。否则，相对于本文件定位 `scripts/scan_tasks.py`，并使用 `--root <project-root> --status open --format json` 扫描任务。
2. 只有一个 `open` 任务时直接使用；存在多个时展示候选任务，不要自行猜测；不存在时，在修改生产文件前，于 `Noctis/<primary-domain>/tasks/<yyyyMMdd>-<slug>/` 创建最小任务记录。
3. 多仓库项目将 `Noctis` 放在工作区根目录，单仓库项目将其放在仓库根目录。选择对最终业务行为负责的领域作为主领域。

每个任务目录只包含一个 `tasks.md` 和一个 `implementation.md`：

```text
<task>/
├── tasks.md
└── implementation.md
```

在 `tasks.md` frontmatter 中仅使用 `status: open` 或 `status: completed`。`implementation.md` 仅保留 `Direction`、`Current` 和 `Completed` 三个章节。

```markdown
---
status: open
---

## Tasks

- [ ] T01 <deliverable>
```

任务涉及多个仓库时，为每个仓库建立一个直接子任务。在父任务的 `tasks.md` 中记录各子任务、相对于项目根目录的仓库路径及其阻塞关系。无阻塞关系的任务可以独立推进，不要为此构建调度器。

```markdown
| Subtask | Repository | Blocked by |
| --- | --- | --- |
| S01 | <relative-repository-path> | - |
```

## 实施并创建检查点

1. 选择第一个阻塞项均已完成且尚未勾选的任务。在修改生产文件前，将简明的执行方向和当前步骤记录到 `implementation.md`。
2. 只实施该任务。仅当用户在本次执行中明确调用时，才使用规划、测试、评审或其他配套 Skill。
3. 检查差异，只暂存该任务的业务修改。使用 Conventional Commits 摘要创建一个本地实现提交，并附加以下 trailer：

   ```text
   Noctis-Task: <domain>/<yyyyMMdd>-<slug>[/<subtask>]/<task-id>
   ```

4. 在 `tasks.md` 中勾选任务，并在 `implementation.md` 中追加简短的实现摘要和实现提交哈希；适用时在同一次修改中更新父任务文件。当目录中的全部任务均已完成后，将状态设为 `status: completed`。
5. 只提交受影响的 Noctis 记录，使用相同的 `Noctis-Task` trailer 创建独立的本地 `docs:` 检查点提交。对于单仓库项目，实现修改和 Noctis 记录仍须在该仓库中分别提交。
6. 继续处理下一个未被阻塞的任务，直到完成用户要求的范围或遇到真实阻塞。未经单独授权，不要推送或部署。

## 谨慎恢复

恢复任务前，读取 `tasks.md`、`implementation.md`、相关工作树以及匹配的 `Noctis-Task` 提交。原地继续尚未提交的工作；实现提交已经存在但缺少 Noctis 检查点时，先核实提交范围，再补全记录。发现证据不一致时应如实报告，不要重写历史或静默修复任务状态。
