---
name: noctis
description: 交互确认目标和 workflow 后，按注册表渐进调度原子 Skill，维护 Noctis 父子任务顺序并在用户确认点暂停。仅在用户显式调用并希望使用预设或自定义组合推进完整任务时使用；不替代可单独调用的原子 Skill，也不自行实施、审查或验证。
---

# Noctis

只协调工作流。不要编写业务代码、审查代码或执行验证。

## 读取注册表

每次调用先读取与本文件同目录的 `registry.yaml`，只加载注册元数据，不加载任何原子 Skill。注册表是可执行 Skill、阶段所有权、角色和 preset 的唯一来源；Skill 已安装不代表已经注册，注册也不代表自动加入 preset。

在展示启动确认前验证：`version` 受支持；默认 preset 和角色引用存在；注册路径为相对路径、保持在 `skills/` 下且目标 `SKILL.md` 的 name 与注册名一致；每个 `entry_stage` 属于自身 stages；所有 stage 仅有一个所有者；preset 非空、无重复项且只引用已注册 Skill。自定义 workflow 使用相同约束。任何一项不满足时报告具体注册项并停止，不要猜测或修复注册表。

## 选择工作流

需要渐进加载时，只显式调用 `$noctis`，并通过以下任一形式把后续 Skill 名称作为工作流数据传入：

- `$noctis preset=<registered-preset>`
- `$noctis workflow=<skill-a>,<skill-b>`

`workflow` 中的名称不带 `$`。不要把 `$noctis` 和多个原子 Skill 一次性显式列出以表达渐进加载；显式写出的 Skill 可能在任务开始时已经全部激活。

直接显式调用多个原子 Skill 仍作为兼容模式支持：使用用户给出的精确顺序，不添加隐藏阶段。该模式只保证渐进执行，不能保证后续 Skill 的说明尚未进入上下文。只调用原子 Skill 而未调用 `$noctis` 时，不注入任何预设。

新任务优先采用用户显式指定的注册 preset 或 workflow。未指定时，根据各 preset 的 description 推荐最匹配项；没有更具体匹配时使用 `default_preset`。恢复任务以已记录 workflow 为当前方案；调用参数与记录冲突时把它作为待确认的变更，不直接覆盖。

## 启动确认

每次显式调用 `$noctis` 都先执行一次启动确认。确认前只读定位任务和项目结构，不创建或修改文件，不推进状态，也不读取任何原子 Skill 的 `SKILL.md`。

优先使用平台提供的交互选择工具；不可用时使用等价的文本选项。存在多个候选任务时先让用户选择目标，不要猜测。然后展示一张启动确认卡，至少包含：

- 任务目标、Task/Subtask 路径以及新建或恢复状态；
- 当前 stage、拟采用的完整 workflow 和推荐依据；
- 将创建或更新的任务记录、本地提交边界；
- 测试和行为验证是否包含，以及推送、部署和远程写入的权限边界。

提供以下选择：

- `A 按当前方案启动`：确认并继续，默认推荐；
- `B 调整工作流`：展示全部注册 preset，并允许输入只含已注册 Skill 的自定义 workflow；
- `C 取消`：不产生任何变更并停止。

只有用户明确选择 A，或在当前方案不存在未决项时明确回复“确认”，才视为通过。沉默、含糊回复和仅查看方案不构成确认。选择 B 后必须展示调整后的完整确认卡并再次确认。

确认后才可创建或更新任务记录，并按当前 stage 加载第一个原子 Skill。同一次调用内的阶段接力不重复启动确认；代码审查 finding、验证场景、外部状态变更和范围变化仍使用各自确认点。再次显式调用 `$noctis` 时重新确认当前任务和剩余 workflow。

## 维护任务状态

优先使用用户给出的任务路径。否则在项目根目录的 `Noctis/<domain>/tasks/` 中定位唯一匹配任务。没有任务记录时，先在确认卡中预览拟创建路径；启动确认后再创建最小 `tasks.md`，并将选定 workflow 写入 frontmatter：

```yaml
---
status: active
stage: <first-skill-entry-stage>
workflow:
  - <skill-name>
---
```

使用 `status: active | completed | blocked`。活动或阻塞任务必须保留注册表中唯一归属的 stage；完成任务移除 `stage`。Task 和 Subtask 可以声明不同 workflow。

Task 表示整体业务目标，Subtask 表示仓库或独立执行边界，Step 只表示 Subtask 内的实施动作。存在 Subtask 时先按依赖完成所有 Subtask；每个 Subtask 独立走完自身 workflow。全部 Subtask 完成后，使用注册表 `integration_review` 角色对应 Skill 的 `entry_stage` 推进父 Task，执行一次整体集成审查。

## 路由原子 Skill

启动确认通过后，每轮先重新读取 `tasks.md`，再从注册表中找到唯一拥有当前 `stage` 的责任 Skill。按该注册项的 path 相对于 `registry.yaml` 解析目标，只在该阶段即将执行时完整读取这一个 `SKILL.md`；不要提前读取 workflow 中后续 Skill 的文件。运行时注册项失效时报告并停止，不要在本 Skill 中重写其流程。

让当前原子 Skill 独立完成职责。它返回后重新读取 `tasks.md`，不要假定它成功推进状态；只有状态已经进入下一阶段时，才解析并读取下一项 Skill。已经进入上下文的说明无法卸载，因此原子 Skill 的阶段守卫始终优先于旧指令。

遇到下列确认点必须暂停：

- 代码审查 finding 的批量取舍；
- 验证场景和逐场景模式确认；
- 有界的外部状态变更授权；
- 任务范围、公开契约或依赖顺序发生变化。

## 保持边界

仅根据已声明 workflow 接力，不自行增加测试、验证、部署或推送。不得把一个原子 Skill 的职责交给另一个 Skill。Noctis 自身修改 workflow 或父任务编排状态时，只提交相关任务记录，使用 `docs:` 摘要和对应 `Noctis-Task` trailer。
