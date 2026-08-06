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

需要被 Noctis 编排的 Skill 在根目录增加 `noctis.yaml`。manifest 只声明 executor/support、contract、文档工具与扩展资源，不复制 `SKILL.md` 流程。所有资源路径相对于本 Skill，且不得逃逸目录，确保 Skill 可独立安装。

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

- 仓库不维护中心运行时注册表。每个原子 Skill 用同级 `noctis.yaml` 自注册；Noctis 的 stage/support contract 与示例保存在 `noctis/assets/`。
- `$noctis init` 根据当前可用 manifest 和用户选择，在目标项目生成 `Noctis/registry.yaml`。已有内容不同时必须先展示差异并再次确认，禁止静默覆盖。
- 同一 stage/support 发现多个 provider 时保留选择，不通过路径顺序暗中决定。没有 manifest 的第三方 Skill 只能由用户提供手工映射。
- `fix` 是恢复 stage，不得加入正常 preset。任务创建时把 stage contract、executor、support 及 provider 固化到 `tasks.md` 快照；恢复任务默认沿用快照。

## 结构化任务文档

- `tasks.md` 由 `noctis/scripts/noctis.py` 管理；各原子 Skill 独立携带自己的模板和 `create/read/update/append` 文档脚本。
- 文档 frontmatter 保持最小，只放 document、template、revision 及确有必要的任务状态。所有写入使用 revision 比较和原子替换。
- 可扩展位置使用稳定 `noctis:slot`、`noctis:collection` 和 `noctis:item` 标记。基础工具只更新自己拥有的 slot，并保留未知 extension。
- augmentation 由 provider manifest 声明，由 Noctis 在对应 workflow 实际启用时通过脚本持久插入；不得预改源模板或直接字符串拼接生成任务状态。
