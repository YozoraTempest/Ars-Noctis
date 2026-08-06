# Ars Migration

迁移候选必须覆盖以下事实：

| 项目 | 需要确认的内容 |
| --- | --- |
| Ownership | 自有、第三方、只读或生成缓存 |
| Trigger | 原 Skill 的独立调用方式与不应触发的场景 |
| Role | executor 或 support |
| Capability | 稳定职责、contract 和完成语义 |
| Artifact | input/output port、type、formats、required |
| State | stateless、documents 或 external |
| Side effects | 可能的文件、Git、网络或外部系统写入 |
| Documents | 唯一写入者、原生路径、恢复来源和冲突路径 |

## 原地迁移示例

已有实现 Skill 自己维护 `implementation.md`：保留文档、模板和脚本，在 `ars.yaml` 声明 `state.mode: documents`，并将实现记录发布为 `implementation-record` Artifact。

## Adapter 示例

外部 Spec Skill 继续在自己的目录生成 proposal、design、spec 和 tasks。Adapter 不合并这些文件，只发布一个 `specification` ArtifactRef，location 指向原生目录。实施 Ars 接受该类型和格式后即可直接消费；格式不兼容时再插入转换 Task。

## 冲突规则

- 同一语义产物有多个候选来源时让用户选择权威来源。
- 两个 Skill 计划写入同一路径时在执行前阻塞。
- 下游不得修改上游原生产物。
- 上游 revision 变化后，旧的下游绑定失效并要求重新规划。
- 不进行默认复制、合并、去重或双向同步。
