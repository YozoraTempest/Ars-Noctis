---
name: verify
description: 按明确标准执行可观察的行为验收、集成检查或证据采集，并给出判定。用户要求验证真实行为、环境或流程时使用；不要用于编写实现、静态代码审查或设计测试策略。
---

# Verify

在指定环境中执行指定场景，让实际观察决定结论。

## 方向

- 将给定验收条件落实为可观察的前置条件、操作、结果和证据。
- 选择足以验证场景的工具和最小执行范围，记录实际行为而非预期推断。
- 对必要场景给出 `passed`、`failed`、`blocked` 或需要用户判断的结论，并说明未覆盖范围。

## 边界

- 不发明验收标准，不因工具可用而扩大账号、数据、系统或外部副作用范围。
- 不修改业务实现；发现失败后把事实交还调用方，由 Noctis 决定后续流程。
- 不默认重复 build、完整测试或打包；Task 要求和目标风险决定执行范围。

## 工具

按场景使用 CLI、测试运行器、API、浏览器、桌面控制、日志或人工协作。优先使用隔离、可恢复的数据和环境。

## Ars

收到 `ars.task/v1` 时只接受 provider `verify`、capability `behavior.verify`。Task envelope 是完整边界；返回 `ars.result/v1`、场景结果 Artifact、实际证据和必要的 effect receipt。只执行当前 Task，不创建或推进 Noctis，也不调用其他 provider。

解析或返回 envelope 时读取 [references/ars-envelope.md](references/ars-envelope.md)。
