# Ars-Noctis

Ars-Noctis 是轻量级 Skills 编排与互操作框架。Ars 定义可独立调用的原生 Skill 单元和 Artifact 契约；Noctis 负责组合 Ars、推进执行状态并在上下文丢失后恢复。

单个 Ars 足够时直接调用，不要求进入 Noctis。只有多 Ars 协作、跨项目执行或需要断点恢复时才创建编排记录。

## 仓库结构

```text
Ars-Noctis/
├── AGENTS.md              # 仓库级协作约束
└── skills/
    ├── AGENTS.md          # Skill 编写与验证规范
    └── <skill-name>/
        ├── SKILL.md       # 必需：触发描述与核心流程
        ├── ars.yaml       # 原生 Ars：能力、Artifact、状态和资源契约
        ├── agents/
        │   └── openai.yaml
        ├── references/    # 可选：按需加载的详细资料
        ├── scripts/       # 可选：确定性读写和重复操作
        └── assets/        # 可选：文档模板、扩展和其他资源
```

每个 `skills/<skill-name>` 都应当可以单独触发。Ars 只包含执行任务所需的内容；仓库说明、设计过程和维护约定保留在仓库根目录。

## Ars

原生 Ars 使用 `ars.yaml` 声明：

- executor capability 或 support；
- input/output Artifact port 与原生格式；
- 可能产生的 side effects，但不借此授予权限；
- `stateless | documents | external` 状态模式；
- 自有文档、工具和 augmentation。

`$ars create skill` 创建新的原生 Ars，`$to-ars` 原地迁移自有 Skill 或为第三方 Skill 创建非侵入 Adapter。格式兼容的 Artifact 直接传递；不兼容时必须安排显式 Adapter Task。

## Noctis 编排

Noctis 是可选的通用 Ars 编排与执行底座，不是原生 Ars 的运行前提：

- `noctis` 选择 Task、Unit 或 Work，确认依赖、Artifact Binding、完成条件与授权并生成 ExecutionPlan。
- `noctis-exec` 创建和推进结构化生命周期，调度计划中固化的 Ars/support，并校验 Artifact 输入输出。
- `noctis-continue` 在断点、换对话、换模型或换 Agent 后重建最小入口和 resolved inputs，再交回 Exec。

Workflow 不限于编码，例如：

```text
design -> implement -> code-review -> verify
data-cleaning -> data-validation -> to-excel
research -> draft -> review -> to-document
```

目标项目中的持久化结构为：

```text
<project-root>/
└── Noctis/
    ├── registry.yaml
    └── <domain>/
        ├── tasks/<task-id>/                 # 可恢复单 Task 模式
        │   ├── noctis.md
        │   └── <record>.md
        ├── units/<unit-id>/                 # 单 Unit 模式
        │   ├── noctis.md
        │   ├── scenarios.md
        │   └── tracks/<track-id>/
        └── work/<work-id>/                  # 多 Unit 模式
            ├── noctis.md
            └── units/<unit-id>/
                ├── noctis.md
                ├── scenarios.md
                └── tracks/<track-id>/
                    ├── implementation.md
                    ├── review.md
                    ├── verification.md
                    └── evidence/
```

- Work 编排通常串行的 Unit；Unit 表示一个需求的完整实现，并用 Task 依赖图表达跨项目并行与集成汇合。
- Track 只是按项目或集成范围组织文件的可选分组，不具有状态；Step 由原子 Skill 在 Task 内部维护。
- `$noctis init` 从可用 Ars 的 `ars.yaml` 生成项目级注册表；不同内容不会静默覆盖。
- `$noctis workflow=reviewed` 等数据式调用只生成确认后的 ExecutionPlan，再交给 Exec。
- `$noctis $implement $code-review` 可提前显式加载能力，但仍需确认层级、Task 图和授权。
- `$noctis continue` 或 `$noctis-continue` 从当前项目唯一未完成根记录进入 Exec；多个候选必须选择。
- `$implement`、`$code-review` 和 `$verify` 仍可独立调用且不创建 `noctis.md`；只有经 Noctis/Exec 启动的单 Task 才持久化。

执行记录与能力文档都由脚本创建和更新。`revision` 提供并发保护，稳定 slot/item 允许 Exec 在启用新能力时持久扩展已有文档，而不修改源模板或覆盖其他能力的内容。

## 生命周期

1. 用真实触发语句确认 Skill 的职责、非目标和升级边界。
2. 使用官方 Skill 初始化工具生成最小骨架。
3. 编写精简的 `SKILL.md`，仅在确有复用价值时增加资源目录。
4. 运行结构校验，并用不携带预设答案的真实任务做正向验证。
5. 根据实际使用中的误触发、漏触发和额外流程成本迭代。

## 仓库验证

使用统一入口校验所有 Ars manifest、Skill 结构和测试目录。显式传入当前环境官方 `quick_validate.py`，不要依赖固定安装路径：

```powershell
python scripts/validate_repository.py --quick-validate <path-to-quick_validate.py>
```

脚本强制使用 UTF-8，并分别发现仓库级测试和各 Skill 的测试目录；没有发现任何测试时返回失败。

## Skills

| Skill | 目标 | 状态 |
| --- | --- | --- |
| `ars` | 创建、检查并验证 Noctis 原生 Ars | 可用 |
| `to-ars` | 原地迁移 Skill 或创建非侵入 Ars Adapter | 可用 |
| `noctis` | 规划 Work、Unit、Task、Artifact Binding 并生成 ExecutionPlan | 可用 |
| `noctis-exec` | 管理执行生命周期、Artifact、状态恢复与文档扩展 | 可用 |
| `noctis-continue` | 在无上下文时恢复执行入口与 resolved inputs | 可用 |
| `implement` | 执行 Implement/Fix Task，并维护内部 Step 与提交记录 | 可用 |
| `code-review` | 对 Task 精确提交执行静态审查和定向修复复核 | 可用 |
| `verify` | 按 Unit 场景执行人工、AI 或辅助式行为验收 | 可用 |
