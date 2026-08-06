# Ars-Noctis

个人 Agent Skills 仓库，用于沉淀可复用、可独立触发的工程工作流。

## 仓库结构

```text
Ars-Noctis/
├── AGENTS.md              # 仓库级协作约束
└── skills/
    ├── AGENTS.md          # Skill 编写与验证规范
    └── <skill-name>/
        ├── SKILL.md       # 必需：触发描述与核心流程
        ├── noctis.yaml    # 可选：Noctis executor/support 自注册信息
        ├── agents/
        │   └── openai.yaml
        ├── references/    # 可选：按需加载的详细资料
        ├── scripts/       # 可选：确定性读写和重复操作
        └── assets/        # 可选：文档模板、扩展和其他资源
```

每个 `skills/<skill-name>` 都应当可以单独安装和使用。Skill 只包含执行任务所需的内容；仓库说明、设计过程和维护约定保留在仓库根目录。

## Noctis 编排

Noctis 是可选编排器，不是原子 Skill 的运行前提。它按 stage 组合 executor 与 support，并在目标项目中维护：

```text
<project-root>/
└── Noctis/
    ├── registry.yaml
    └── <domain>/tasks/<task>/
        ├── tasks.md
        ├── implementation.md
        ├── review.md
        ├── scenarios.md
        └── verification.md
```

- `$noctis init` 从可用 Skill 的 `noctis.yaml` 生成项目级注册表；不同内容不会静默覆盖。
- `$noctis preset=reviewed` 等数据式调用按 stage 渐进加载能力。
- `$noctis $implement $code-review` 可提前显式加载能力，但仍执行任务定位、交互确认、快照与阶段守卫。
- `$implement`、`$code-review` 和 `$verify` 仍可独立调用，不会隐式注入其他阶段。

任务文档由所属 Skill 的脚本创建和更新。`revision` 提供并发保护，稳定 slot/item 允许 Noctis 在启用新能力时持久扩展已有文档，而不修改源模板或覆盖其他能力的内容。

## 生命周期

1. 用真实触发语句确认 Skill 的职责、非目标和升级边界。
2. 使用官方 Skill 初始化工具生成最小骨架。
3. 编写精简的 `SKILL.md`，仅在确有复用价值时增加资源目录。
4. 运行结构校验，并用不携带预设答案的真实任务做正向验证。
5. 根据实际使用中的误触发、漏触发和额外流程成本迭代。

## Skills

| Skill | 目标 | 状态 |
| --- | --- | --- |
| `noctis` | 按项目注册表编排 stage、support、父子任务和恢复队列 | 可用 |
| `implement` | 按 Task/Subtask 实施功能或集中修复，并维护独立实现记录 | 可用 |
| `code-review` | 对精确提交范围执行静态审查和一次定向修复复核 | 可用 |
| `verify` | 按确认场景执行人工、AI 或辅助式行为验收 | 可用 |
