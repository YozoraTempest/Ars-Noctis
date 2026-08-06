# Ars Contract v1

Ars 是 Ars-Noctis 的原生 Skill 单元。Noctis 只通过 `ars.yaml` 发现其能力，不为发现过程读取 `SKILL.md`。

## Manifest

`ars.yaml` 顶层字段固定为：

```yaml
version: 1
kind: ars
name: example
role: executor
state:
  mode: stateless
capabilities: []
supports: []
documents: []
augmentations: []
```

- `role: executor` 要求非空 `capabilities`，并禁止 `supports`。
- `role: support` 要求非空 `supports`，并禁止 `capabilities`。
- `state.mode` 使用 `stateless | documents | external`。
- `documents` 模式要求至少一个 document；其他模式禁止 document 和 augmentation。

## Executor Capability

```yaml
capabilities:
  - id: transform-data
    contract: 1
    inputs:
      source:
        type: dataset
        formats:
          - tabular.csv@1
        required: true
    outputs:
      result:
        type: dataset
        formats:
          - tabular.normalized@1
        required: true
    side_effects:
      - filesystem-write
```

Port ID 只在 capability 内唯一。`type` 表示语义，`formats` 表示可直接消费或产生的原生格式，格式使用 `<namespace>.<name>@<version>`。`required` 表示 Task 完成或启动时是否必须存在。

`side_effects` 用稳定标识符声明能力可能产生的副作用，供 Noctis 规划时展示；它不能替代用户授权。

## Support

```yaml
supports:
  - id: stage-knowledge
    contract: 1
    activation:
      - before
      - on-request
    side_effects: []
```

Support 不拥有 Task，只在 executor 的生命周期中按声明时机激活。

## State

- `stateless`：没有需要恢复的内部状态，同一请求可从输入重新执行。
- `documents`：通过 `documents` 中声明的模板和脚本维护状态，所有写入使用 revision。
- `external`：状态位于目标工作树或外部工具；恢复时重新检查这些事实，不复制为 Ars 文档。

Document 与 augmentation 字段沿用 Ars-Noctis 的结构化文档契约。`template`、`tool` 和 augmentation template 必须位于 Ars 目录内并真实存在。

## Artifact Flow

Noctis Workflow 把后继 input port 显式绑定到直接前置 Task 的 output port。类型必须相同，格式必须有交集。没有交集时必须插入 Adapter Task；Exec 不执行隐藏转换。

Task 完成时发布 ArtifactRef：

```yaml
type: dataset
format: tabular.normalized@1
location: output/customers.csv
revision: sha256:example
```

`location` 可以表示项目路径或外部位置；`revision` 可为空，但来源发生变化时应提供可比较版本。

ExecutionEntry 的 resolved input 在 ArtifactRef 外附带来源 Task、provider 和 record 句柄。文档型消费者应通过来源 Ars 的已注册文档工具读取 record；不得为了桥接而直接改写或复制其 Markdown。
