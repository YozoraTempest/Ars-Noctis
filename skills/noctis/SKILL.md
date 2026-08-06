---
name: noctis
description: 按 Noctis 任务中声明的 workflow 编排 implement、code-review 和可选 verify，维护父子任务顺序并在用户确认点暂停。仅在用户显式调用并希望使用预设或自定义组合推进完整任务时使用；不替代可单独调用的原子 Skill，也不自行实施、审查或验证。
---

# Noctis

只协调工作流。不要编写业务代码、审查代码或执行验证。

## 选择工作流

使用以下预设：

| Preset | Workflow | Use |
| --- | --- | --- |
| `implement-only` | `implement` | 只要求实现或修复 |
| `reviewed` | `implement`, `code-review` | 默认工程修改 |
| `verified` | `implement`, `code-review`, `verify` | 还要求实际行为验收 |

用户指定预设时直接使用。用户显式列出原子 Skill 时，使用该精确组合，不添加隐藏阶段；例如 `$implement $code-review` 等价于 `reviewed`。只调用原子 Skill 而未调用 `$noctis` 时，不注入任何预设。

仅调用 `$noctis` 且需求没有明确验证要求时使用 `reviewed`。执行前说明选中的预设、完整 workflow 和选择依据；用户可以覆盖。

## 维护任务状态

优先使用用户给出的任务路径。否则在项目根目录的 `Noctis/<domain>/tasks/` 中定位唯一匹配任务；存在多个候选时展示候选，不要猜测。没有任务记录时，创建最小 `tasks.md`，并将选定 workflow 写入 frontmatter：

```yaml
---
status: active
stage: implement
workflow:
  - implement
  - code-review
---
```

使用 `status: active | completed | blocked`。活动或阻塞任务必须保留 `stage: implement | review | fix | verify`；完成任务移除 `stage`。Task 和 Subtask 可以声明不同 workflow。

Task 表示整体业务目标，Subtask 表示仓库或独立执行边界，Step 只表示 Subtask 内的实施动作。存在 Subtask 时先按依赖完成所有 Subtask；每个 Subtask 独立走完自身 workflow。全部 Subtask 完成后，将父 Task 推进到 `review`，执行一次整体集成审查。

## 路由原子 Skill

按照当前 `stage` 使用对应的已安装 Skill：

- `implement` 或 `fix`：使用 `$implement`。
- `review`：使用 `$code-review`。
- `verify`：使用 `$verify`。

调用前完整读取对应 Skill 的说明并让它独立完成职责。原子 Skill 不可用时报告缺失项并停止，不要在本 Skill 中重写其流程。

每次原子 Skill 返回后重新读取 `tasks.md`，再决定下一步。不要假定它成功推进状态。遇到下列确认点必须暂停：

- 代码审查 finding 的批量取舍；
- 验证场景和逐场景模式确认；
- 有界的外部状态变更授权；
- 任务范围、公开契约或依赖顺序发生变化。

## 保持边界

仅根据已声明 workflow 接力，不自行增加测试、验证、部署或推送。不得把一个原子 Skill 的职责交给另一个 Skill。Noctis 自身修改 workflow 或父任务编排状态时，只提交相关任务记录，使用 `docs:` 摘要和对应 `Noctis-Task` trailer。
