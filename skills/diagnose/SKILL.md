---
name: diagnose
description: 调查软件异常、失败、性能退化或环境差异，通过复现、范围缩小和证伪实验形成可独立使用的诊断结论。用户要求排查问题、解释异常、判断故障归属、创建最小复现或确认根因时使用；不要用于直接实施修复、审查已有变更、编写测试资产或按既定场景执行正式验收。
---

# Diagnose

对故障执行完整调查，直接交付可供决策的结论和证据，不把诊断当作其他 Skill 的必经阶段。

## 执行

1. 明确预期行为、实际行为、发生条件、影响范围和已知时间线。优先从仓库、日志和现有材料查明事实；只有缺失信息会改变调查方向时才请求补充。
2. 建立可比较基线，使用最小充分方法复现问题。无法复现时记录环境差异、尝试过的条件和已排除范围。
3. 将故障缩小到组件、边界、状态或输入，提出多个可证伪的竞争假设，不把时间相关性当作因果关系。
4. 设计最小实验逐项排除假设。保留实际命令、日志、代码位置、度量或观察作为证据，不虚构未执行的结果。
5. 给出 `confirmed`、`probable`、`not-reproduced`、`environmental` 或 `unresolved` 结论，并说明置信依据和剩余不确定性。
6. 报告触发条件、影响范围、临时缓解选项和最小修复方向。默认不修改生产实现；调查报告本身就是完整交付。

默认只读。用户明确要求可复用的最小复现或诊断资产时，才在授权范围内创建独立文件；不要把诊断实验伪装成修复。

## 交付

直接调用时在当前任务中报告 `observed`、`expected`、`reproduction`、`hypotheses-tested`、`conclusion`、`evidence`、`impact`、`mitigation-options` 和 `residual-uncertainty`。没有证据时不要声称根因已经确认。

## Ars 调用

收到 `ars.task/v1` 时：

- 只接受 provider `diagnose`、capability `software.diagnose` 的 Task；Task 可以没有前置 Artifact，也可以包含用户材料、日志、失败输出或其他公开 Artifact。
- 以 instructions、inputs、acceptance、workspace 和 effects 为完整边界，不读取其他 Skill 的正文、私有文件或状态。
- 返回 `ars.result/v1`，默认以内联 `diagnosis.report` Artifact 交付结构化报告。按实际调查可附加 `diagnosis.reproducer` 或 `diagnosis.trace`，但不要求任何消费者存在。
- `not-reproduced`、`environmental` 或有证据支撑的 `unresolved` 仍可作为已完成调查返回 `completed`；缺少关键业务事实时返回 `input-required`，环境、工具或授权不足时返回 `blocked`。被调查软件失败不等于诊断 Task 自身 `failed`。
- 只有 Task 明确请求并授权持久诊断资产时才写入 workspace；写入时遵循 envelope 对 `workspace.write`、`git.commit` 和 Git Artifact 的共同要求。

解析 Task 或构造 Result 前读取 [references/ars-envelope.md](references/ars-envelope.md)，严格复制关联字段并只返回契约允许的字段。

独立调用时直接交付诊断结论，不要求 Ars、Noctis、前置文档或其他 Skill。
