# Skill 编写规范

## 目录边界

`skills/` 的每个直接子目录代表一个可独立安装的 Skill，目录名使用小写字母、数字和连字符，并与 `SKILL.md` 中的 `name` 一致。

一个 Skill 的最小结构为：

```text
<skill-name>/
├── SKILL.md
└── agents/
    └── openai.yaml
```

仅在任务确实需要时增加 `scripts/`、`references/` 或 `assets/`。不要在 Skill 目录中增加 `README.md`、变更日志、安装指南或重复说明。

Noctis 原生 Ars 在根目录增加 `ars.yaml`。manifest 只声明 executor/support、contract、Artifact port、状态模式、可能副作用、文档工具与扩展资源，不复制 `SKILL.md` 流程。所有资源路径相对于本 Ars，且不得逃逸目录。

## SKILL.md

- YAML frontmatter 只包含 `name` 和 `description`。
- `description` 同时说明能力与具体触发场景；不要把触发规则藏在正文中。
- 正文使用祈使式，聚焦核心决策和执行顺序，控制在 500 行以内。
- 详细规则和示例只保留一份；移入 `references/` 后，从 `SKILL.md` 直接说明何时读取。
- 引用层级保持一层，避免引用文件继续要求加载更多引用。

## UI 元数据与验证

- 生成 `agents/openai.yaml` 前先阅读官方字段说明，并根据完成后的 `SKILL.md` 生成 `display_name`、`short_description` 和 `default_prompt`。
- 不添加未经明确提供的图标、品牌色或其他可选元数据。
- 完成后运行官方 `quick_validate.py`。
- 脚本必须实际运行；复杂工作流应以真实触发语句验证误触发、漏触发和不必要的流程成本。

## Noctis 注册

- 仓库不维护中心运行时注册表。每个原生 Ars 用同级 `ars.yaml` 自注册；Noctis 的 capability/support contract 与示例保存在 `noctis/assets/`。
- `$noctis init` 根据当前可用 Ars manifest 和用户选择，在目标项目生成 `Noctis/registry.yaml`。已有内容不同时必须先展示差异并再次确认，禁止静默覆盖。
- 同一 capability/support 发现多个 provider 时保留选择，不通过路径顺序暗中决定。没有 manifest 的第三方 Skill 只能由用户提供手工映射。
- Workflow Template 声明 Task capability 与依赖图，允许多个 Task 使用同一 capability。`fix` 只允许在异常时动态插入，不得加入正常模板。
- Workflow 的 input port 只绑定直接前置 Task 的 output port；类型相同且格式有交集时直接传递，否则插入显式 Adapter Task。
- Unit 创建时把每个 Task 的 capability contract、executor、support、provider、Artifact Binding 和记录路径固化到 `noctis.md`；恢复默认沿用快照。

## 结构化编排文档

- Task、Unit 与 Work 的 `noctis.md` 由 `noctis-exec/scripts/exec.py` 管理；Noctis 只生成已确认的 ExecutionPlan，Noctis Continue 只生成只读 ExecutionEntry。各原子 Skill 独立携带自己的模板和 `create/read/update/append` 文档脚本。
- Work 只编排 Unit，Unit 只编排 Task，Task 内 Step 由执行 Skill 管理。Track 仅用于物理分组，不维护生命周期状态。
- Unit 的 Task 使用依赖图表达并行与串行汇合。异常流程以新的 Task 原子插入，并只重接尚未开始的后继；不得维护全局 stage 或 resume 队列。
- 文档 frontmatter 保持最小，只放 document、template、revision 及确有必要的任务状态。所有写入使用 revision 比较和原子替换。
- 可扩展位置使用稳定 `noctis:slot`、`noctis:collection` 和 `noctis:item` 标记。基础工具只更新自己拥有的 slot，并保留未知 extension。
- augmentation 由 provider manifest 声明，由 Noctis Exec 在对应 Task 实际启用时通过脚本持久插入；不得预改源模板或直接字符串拼接生成任务状态。
- 只有经 Noctis/Exec 启动的单 Task 才在 `Noctis/<domain>/tasks/<task-id>/` 持久化；独立调用原子 Skill 不注入编排记录。
- Continue 不区分断点、模型、Agent 或对话来源；它按当前项目局部扫描恢复最小上下文，所有状态判断仍由 Exec 完成。
- ArtifactRef 只记录类型、格式、位置和 revision；resolved input 另附来源 provider 与 record 句柄，原生文档仍由所属 Ars 独占写入。
