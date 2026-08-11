---
name: implement
description: 在软件仓库中完成明确范围的代码、配置或迁移变更，并运行相称的本地检查。用户要求实现、修复或重构时使用；不要用于只读诊断、代码审查、独立验收或发布。
---

# Implement

交付当前任务要求的最小完整变更，让仓库事实指导实现细节。

## 方向

- 阅读适用规则、相关代码和已有测试，沿用仓库模式并保护无关用户修改。
- 在 Task 边界内自主选择设计、工具和实现步骤；避免无关重构和提前抽象。
- 运行与变更风险相称的检查，优先快速、相关的反馈，再按实际影响扩大范围。

## 边界

- 不扩大需求或替调用方编排后续工作。
- 不自行调用其他 provider，不创建、扩展、重试或完成 Noctis Task。
- 写入、提交、推送、部署或外部修改只在当前授权范围内执行。

## 工具

优先使用仓库原生的搜索、构建、格式化、静态检查和测试工具；需要外部知识时使用对应依赖的官方资料。

## Ars

收到 `ars.task/v1` 时只接受 provider `implement`、capability `code.change`。Task envelope 是完整边界；返回 `ars.result/v1`，用 Artifact 表达产物、evidence 表达实际检查、effect receipt 表达已发生副作用。

解析或返回 envelope 时读取 [references/ars-envelope.md](references/ars-envelope.md)。
