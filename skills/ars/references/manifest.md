# Ars Manifest v1

只在创建或审查 `ars.json` 时加载本文件。

```json
{
  "schema": "ars.skill/v1",
  "id": "example-skill",
  "version": "1.0.0",
  "capabilities": [
    {
      "id": "example.transform",
      "description": "Transform one validated input into an output artifact.",
      "accepts": "ars.task/v1",
      "returns": "ars.result/v1",
      "effects": ["command.execute", "workspace.write"]
    }
  ]
}
```

字段约束：

- `id` 与 Skill 目录名、`SKILL.md` 的 `name` 一致。
- `version` 是 `MAJOR.MINOR.PATCH`。修改 envelope 语义、Artifact 解释或副作用边界时提升 major。
- capability ID 使用稳定的小写点号或连字符标识，不包含 provider 名称。
- `accepts` 固定为 `ars.task/v1`，`returns` 固定为 `ars.result/v1`。
- `effects` 只能取 `command.execute`、`workspace.write`、`git.commit`、`git.push`、`network.write`、`deployment`、`destructive`。

Manifest 是能力发现面，不是权限授予、执行记录或私有实现索引。Noctis 会在创建 Run 时快照实际选中的 provider 版本；同 ID 的多个 provider 副本必须显式消除歧义。
