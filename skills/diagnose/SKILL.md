---
name: diagnose
description: 调查软件异常、失败、性能退化或环境差异，并给出有证据的根因判断。用户要求诊断、复现、定位或解释故障时使用；不要用于直接修复、代码审查或正式验收。
---

# Diagnose

围绕一个可信的故障信号缩小问题，证据强度决定结论强度。

## 方向

- 明确预期、实际行为、触发条件和影响范围，建立能观察目标故障的最小反馈信号。
- 依据证据提出并证伪假设；优先缩短、稳定和收紧反馈循环。
- 给出根因或最可能边界、置信程度、已排除范围和最小修复方向。

## 边界

- 默认只读，不把诊断变成顺手修复；需要持久复现资产或 instrumentation 时服从 Task 授权。
- 无法复现或证据不足时如实返回，不把相关性写成因果关系。
- 输出日志、请求或捕获物前移除凭据和个人数据。

## 工具

按问题选择测试或脚本、日志、调试器、Profiler、Trace、差分运行或 Git bisect。工具服务于区分假设，不为收集更多输出而使用。

## Ars

收到 `ars.task/v1` 时只接受 provider `diagnose`、capability `software.diagnose`。Task envelope 是完整边界；返回 `ars.result/v1` 和适合实际调查的诊断 Artifact。只执行当前 Task，不创建或推进 Noctis，也不调用其他 provider。

解析或返回 envelope 时读取 [references/ars-envelope.md](references/ars-envelope.md)。
