---
name: ars-noctis
description: 在规格、设计、诊断、实现、测试、代码审查和行为验收之间选择并组合适用的原子 Skill。用户显式要求 Ars-Noctis 处理跨能力软件工程任务时使用；不要用于执行单一能力时增加额外流程，也不要用于持久任务编排。
---

# Ars-Noctis Router

只负责路由。根据用户最终目标选择最少的原子 Skill，读取其完整 `SKILL.md` 后按其 interface 执行；不要自行补充领域方法，也不要预先加载所有 Skill。

## 路由表

- 澄清需求、范围、业务规则或验收条件：读取 [spec](../spec/SKILL.md)。
- 设计模块 interface、数据流、迁移或技术取舍：读取 [design](../design/SKILL.md)。
- 复现、定位或解释故障且默认不修复：读取 [diagnose](../diagnose/SKILL.md)。
- 修改代码、配置或迁移：读取 [implement](../implement/SKILL.md)。
- 设计测试策略、补充测试资产或分析覆盖缺口：读取 [test](../test/SKILL.md)。
- 只读审查明确的 diff、commit 或 PR：读取 [code-review](../code-review/SKILL.md)。
- 按既定标准执行真实行为或集成验收：读取 [verify](../verify/SKILL.md)。

## 组合规则

- 单一目标只选择一个 Skill。该 Skill 能完成的附带工作不再拆分，例如实现过程中的普通回归检查仍由 `implement` 完成。
- 多个目标按事实依赖和用户要求排序，只加载直接相关的 Skill。
- “定位并修复”依次使用 `diagnose`、`implement`。
- “审查并修复”依次使用 `code-review`、`implement`，只处理用户授权修复的问题。
- “实现并验收”依次使用 `implement`、`verify`，不把实现检查冒充行为验收。
- “从模糊想法推进到设计”使用 `spec`、`design`；缺失决定会改变目标或验收结论时先请求用户输入。

路由只改变当前采用的 Skill interface，不创建 Task DAG、状态文件、handoff envelope、subagent 或恢复协议。跨轮次继续工作时，以当前对话、用户材料和工作区事实为准。
