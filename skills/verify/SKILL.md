---
name: verify
description: 按明确场景执行可观察的行为验收、集成检查或证据采集，并给出 passed、failed 或 blocked 判定。用户要求验证真实行为、验收流程、运行集成场景或人工协同检查时使用；不要用于编写实现、静态代码审查或仅补单元测试。
---

# Verify

## 执行

1. 把需求转成可观察场景：前置条件、操作、预期结果、判定主体和证据。缺少关键期望时先确认，不自行发明业务规则。
2. 选择最小充分模式：`human` 由用户操作并判定；`ai` 由当前 Agent 使用已授权工具操作并判定；`assisted` 由 Agent 准备环境或证据、用户最终判定。
3. 在执行前确认目标环境、账号、数据范围和可能副作用。登录状态或工具可用不等于授权；生产、批量、不可逆或外部写入必须另行明确授权。
4. 执行每个场景并记录实际观察。工具不可用、环境不稳定或证据不足时判定 blocked，不静默降级，也不把“页面可打开”当作功能通过。
5. 汇总 passed、failed、blocked 和未执行项。默认不修改业务代码；修复失败另交 Implement。

## Noctis 调用

收到 `ars.task/v1` 时，只接受 provider `verify`、capability `behavior.verify` 的 Task。使用 inputs 中的实现产物、审查发现或场景，不读取其他 Skill 私有状态。

返回 `ars.result/v1`：

- Artifact 提供结构化场景结果；evidence 只引用实际存在的文件、完整 commit、HTTP(S) URI 或 inline 观察。
- effect receipt 只记录实际发生且 Task 已授权的命令、workspace 写入或网络写入。
- 任一必要场景失败时返回 `failed`；需要用户判定时返回 `input-required`；环境或权限缺失时返回 `blocked`。

独立调用时直接报告验收结果，不创建 Noctis 状态、不提交证据、不推送或部署。
