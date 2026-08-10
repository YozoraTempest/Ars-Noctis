---
name: code-review
description: 对指定提交、差异或变更集执行只读代码审查，优先发现可证明的正确性、安全、兼容性和回归问题。用户要求 review、审查 PR/diff/commit 或复核修复时使用；不要用于实现修复、运行完整行为验收或泛化代码讲解。
---

# Code Review

## 执行

1. 精确确定审查基线、目标 revision 和文件范围；范围不明确且会改变结论时先说明假设或请求澄清。
2. 阅读适用规则、变更上下文、调用方和相关测试。只做与判断有关的只读检查。
3. 只报告能由代码、配置、测试或运行结果支持的问题。按严重性排序，每项给出文件、行号、触发场景、实际影响和最小修复方向。
4. 区分确定缺陷、契约风险和测试缺口。多个表现来自同一根因时合并，不用风格偏好填充报告。
5. 未发现问题时明确说明，并列出尚未实际验证的范围。除非用户另行要求修复，否则不修改文件、不提交、不推送。

## Noctis 调用

收到 `ars.task/v1` 时，只接受 provider `code-review`、capability `code.review` 的 Task。优先审查 inputs 中由直接前置 Task 产生的 Artifact，不从工作树或聊天历史猜测变更范围。

返回 `ars.result/v1`：

- 用 inline 或 workspace Artifact 返回结构化 findings；稳定字段至少包含 `severity`、`category`、`location`、`evidence`、`impact` 和 `remediation`。
- 以 evidence 记录实际检查的 revision、命令或报告。
- 工具不可用或 revision 不可达时返回 `blocked`，不要把未执行检查描述为通过。

解析 Task 或构造 Result 前读取 [references/ars-envelope.md](references/ars-envelope.md)，严格复制关联字段并只返回契约允许的字段。

不要直接修改业务代码、Noctis 数据库或其他 Skill 的记录。
