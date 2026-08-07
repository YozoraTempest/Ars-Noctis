# 创建 ExecutionPlan

## 选择最小结构

- 单个原子 Skill 且需要 Noctis 生命周期：Task，路径为 `Noctis/<domain>/tasks/<task-id>/noctis.md`。
- 一个完整需求：Unit，路径为 `Noctis/<domain>/units/<unit-id>/noctis.md`。
- 多个通常串行的完整需求：Work，路径为 `Noctis/<domain>/work/<work-id>/noctis.md`，子 Unit 位于其 `units/` 下。

不同项目的 Task 通常位于不同 Track，可以并行；局部 Review 依赖对应 Implement，集成 Review/Verify 依赖全部局部分支。正常计划不得包含 Fix。

## 解析能力

读取 `Noctis/registry.yaml`，从 Workflow Template 展开 Task 图。同一 capability 可以出现多次。为每个 Task 固化 contract、executor provider、support provider/激活时机、Artifact Binding 和记录路径；不读取 provider 的 `SKILL.md`。

输入只绑定直接依赖的输出，或绑定用户明确提供的外部 ArtifactRef。类型必须相同且格式必须有交集；否则增加显式 Adapter Task。不要在计划或 Exec 中安排隐藏格式转换。

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

用户选择调整时重新生成并展示完整计划。确认后把 ExecutionPlan 原样交给 `noctis-exec` 的 `start-workflow`；Noctis 不调用状态脚本。
