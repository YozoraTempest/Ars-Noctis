# Ars-Noctis

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Ars-Noctis 是个人 Agent Skill 路由项目。当前原子 Skill 集合已经清理，仓库只保留一个空注册状态的 `ars-noctis` 路由入口，等待重新设计。

## 当前状态

- `skills/ars-noctis/` 保留路由 Skill 的名称、UI 元数据和注册约束。
- 当前没有已注册的原子 Skill，也没有可执行的领域路由。
- 显式调用 `$ars-noctis` 只会报告当前注册状态，不会回退到已删除的旧 Skill。
- 仓库不包含状态机、Task DAG、持久运行时、npm 安装器、Plugin 包装、运行脚本或评测数据。

旧的 `spec`、`design`、`diagnose`、`implement`、`test`、`code-review` 和 `verify` 已从当前工作树移除。需要参考时可以从 Git 历史中的 commit `e961098` 查看，不应在新设计中默认继承其职责划分。

## 项目结构

```text
skills/
├── AGENTS.md
└── ars-noctis/
    ├── SKILL.md
    └── agents/openai.yaml
```

## 重新设计约束

- 先定义原子 Skill 的目标、触发范围、interface 和相邻非目标，再创建目录。
- 每个原子 Skill 必须能够独立安装和调用，不依赖路由器或兄弟 Skill。
- 路由器只选择、加载和排序已经存在的原子 Skill，不复制其方法正文。
- 单个 Skill 可以完整处理的请求不应为了流程形式被拆分。
- 不重新引入状态机、provider envelope、运行数据库或额外 Agent 宿主。
- 新增或删除原子 Skill 时同步更新路由器和本 README。

## 验证

当前只需验证保留的路由 Skill：

```bash
python /path/to/skill-creator/scripts/quick_validate.py skills/ars-noctis
```

## License

[MIT](LICENSE)
