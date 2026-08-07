# 创建 ExecutionPlan

## 选择最小结构

- 单个原子 Skill 且需要 Noctis 生命周期：Task，路径为 `Noctis/<domain>/tasks/<task-id>/noctis.md`。
- 一个完整需求：Unit，路径为 `Noctis/<domain>/units/<unit-id>/noctis.md`。
- 多个通常串行的完整需求：Work，路径为 `Noctis/<domain>/work/<work-id>/noctis.md`，子 Unit 位于其 `units/` 下。

不同项目的 Task 通常位于不同 Track，可以并行；局部 Review 依赖对应 Implement，集成 Review/Verify 使用 `cardinality: many` 输入绑定全部直接依赖。正常计划不得包含 `fix-review` 或 `fix-verification`。

## 选择工作流

当前 Agent 先激活 `noctis-continue` 的只读发现流程。Continue 展示已有状态机实例及不同 Track 上的 active、ready、blocked 入口；用户选择遗留入口时由 Continue 进入 Exec，选择创建新计划时才返回这里。不要重新展开模板或覆盖 Task 快照。

创建新计划时再读取 `Noctis/registry.yaml`，用 Workflow Template 展开当前候选。`default_workflow` 只作为推荐，不自动启动；注册表模板不是此前生成的工作流。

用户选择后再展开 Task、Track、provider 和授权。Exec 只接收最终确认的 ExecutionPlan，不读取注册表替用户选择模板。

## 解析能力

读取 `Noctis/registry.yaml`，从 Workflow Template 展开 Task 图。同一 capability 可以出现多次。为每个 Task 固化 contract、executor provider、support provider/激活时机、Artifact Binding 和记录路径；不读取 provider 的 `SKILL.md`。

输入只绑定直接依赖的输出，或绑定用户明确提供的外部 ArtifactRef。`cardinality: one` 使用单一 source，`many` 使用非空 source 数组。类型必须相同且格式必须有交集；否则增加显式 Adapter Task。不要在计划或 Exec 中安排隐藏格式转换。

没有注册表、provider 不唯一、contract 不兼容或记录路径冲突时展示事实并确认处理，不按路径顺序猜测。

## 构造计划

使用以下顶层 Interface：

```yaml
version: 2
root: Noctis/<domain>/<level>/<id>/noctis.md
records:
  - level: task | unit | work
    path: Noctis/.../noctis.md
    input: {}
```

每个 `input` 都包含 `id`、`title`、`objective`、非空 `completionConditions`，以及：

```yaml
authority:
  allowed: []
  forbidden: []
```

Task 再包含 capability、binding、artifactBinding 和 record。artifactBinding 固化 input 的 source/type/formats/required，以及 output 的 type/formats/required。Unit 再包含 workflowTemplate、tracks 和 tasks。Work 再包含 units；Work 中每个 Unit path 必须指向计划内对应 Unit 记录。

## 启动确认

写入前一次展示：

- 层级、根记录和目标；
- Work 的 Unit 顺序，或 Unit 的 Task 图与并行组；
- 每个 Task 的 capability、Track、executor、support、Artifact 输入输出和记录文件；
- 完成条件，以及测试、提交、推送、部署和外部写入授权。

用户选择调整时重新生成并展示完整计划。确认后把 ExecutionPlan 原样交给 `noctis-exec` 的 `materialize-workflow`，并明确标记本次调用已经确认。物化成功后调用 `entry --record <root>`，再把 ExecutionEntry 原样交给 `execute-workflow`；正常启动与 Continue 恢复共用这一执行输入。
