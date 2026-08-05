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
