---
name: code-review
description: 对明确提交、差异或变更集执行只读审查，报告可证明的正确性、安全、兼容性和回归问题。用户要求 review、审查 PR、diff 或 commit 时使用；不要用于实现修复或运行完整行为验收。
---

# Code Review

审查精确变更，只让有证据、会影响工程判断的问题进入报告。

## 方向

- 固定基线、目标 revision 和范围，阅读相关调用方、契约与测试。
- Findings 优先并按严重性排序；每项说明位置、触发条件、证据、影响和可执行修复方向。
- 合并同一根因，区分确定缺陷、风险和测试缺口；无发现时说明未验证范围。

## 边界

- 保持只读，不顺手修复，不把风格偏好或工具已经稳定检查的内容写成问题。
- 不替 Verify 执行完整验收，不替 Noctis 决定返工或后续 Task。
- 范围或基线缺失且会改变结论时请求输入。

## 工具

使用 Git diff/show/log/blame、仓库搜索、静态分析和必要的定向测试。工具用于证明或证伪 finding，不追求固定检查清单。

## Ars

收到 `ars.task/v1` 时只接受 provider `code-review`、capability `code.review`。Task envelope 是完整边界；返回 `ars.result/v1`、结构化 findings Artifact 和实际检查证据。只执行当前 Task，不创建或推进 Noctis，也不调用其他 provider。

解析或返回 envelope 时读取 [references/ars-envelope.md](references/ars-envelope.md)。
