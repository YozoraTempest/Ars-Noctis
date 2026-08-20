# Ars-Noctis

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Ars-Noctis 是一组普通、可独立使用的个人 Agent Skills。`ars-noctis` 只负责在七个原子 Skill 之间选择和组合，不实现状态机、任务图、持久运行时或额外协议。

## Skills

| Skill | 职责 |
| --- | --- |
| `ars-noctis` | 识别请求目标，选择并按需组合原子 Skill |
| `spec` | 澄清需求、范围、业务规则和验收条件 |
| `design` | 设计模块 interface、数据流、迁移和关键技术取舍 |
| `diagnose` | 只读复现、定位和解释软件故障 |
| `implement` | 完成代码、配置或迁移变更并运行相关检查 |
| `test` | 围绕风险设计、补充或执行最小充分测试 |
| `code-review` | 只读审查明确的 diff、commit 或 PR |
| `verify` | 按既定标准执行真实行为或集成验收 |

每个 `skills/<name>/` 都是完整单体，具有自己的 `SKILL.md` 和 `agents/openai.yaml`。原子 Skill 不依赖路由器，也不读取其他 Skill；可以直接使用 `$spec`、`$diagnose` 或 `$implement` 等入口。

`$ars-noctis` 适合明确包含多个目标的请求，例如“定位并修复”或“实现并验收”。它只读取必要的原子 Skill，并在当前执行内按事实依赖衔接，不创建中间状态或运行记录。

## 安装

先克隆仓库，再把 `skills/` 下的八个直接子目录分别复制或链接为用户级同级 Skills：

```bash
git clone https://github.com/YozoraTempest/Ars-Noctis.git /absolute/path/to/Ars-Noctis
mkdir -p ~/.agents/skills
for skill_path in /absolute/path/to/Ars-Noctis/skills/*; do
  ln -s "$skill_path" ~/.agents/skills/"$(basename "$skill_path")"
done
```

目标结构应为：

```text
~/.agents/skills/
├── ars-noctis/
├── spec/
├── design/
├── diagnose/
├── implement/
├── test/
├── code-review/
└── verify/
```

Codex 支持符号链接并会自动检测 Skill 变更；如果新入口没有出现，重启 Codex。安装位置与 Skill 目录格式见[官方 OpenAI Skills 文档](https://learn.chatgpt.com/docs/build-skills)。

所有 Skill 默认只允许显式调用，避免这些覆盖面较广的工程能力自动介入普通请求。

## 路由行为

- 单一目标只选择一个原子 Skill。
- 实现附带的普通回归检查留在 `implement`，不额外加载 `test`。
- “定位并修复”依次使用 `diagnose`、`implement`。
- “审查并修复”依次使用 `code-review`、`implement`。
- “实现并验收”依次使用 `implement`、`verify`。
- “从模糊想法推进到设计”依次使用 `spec`、`design`。

路由器不会创建 Task DAG、状态文件、handoff envelope、subagent 或恢复协议。

## 项目结构

```text
skills/
├── ars-noctis/          # 纯路由 Skill
├── spec/                # 独立需求规格 Skill
├── design/              # 独立技术设计 Skill
├── diagnose/            # 独立故障诊断 Skill
├── implement/           # 独立代码实现 Skill
├── test/                # 独立测试 Skill
├── code-review/         # 独立代码审查 Skill
└── verify/              # 独立行为验收 Skill
```

仓库不包含 npm 安装器、Plugin 包装、运行脚本、评测数据或状态机实现。

## 验证

修改后对每个 Skill 运行官方快速校验：

```bash
for skill_path in skills/*; do
  python /path/to/skill-creator/scripts/quick_validate.py "$skill_path"
done
```

## License

[MIT](LICENSE)
