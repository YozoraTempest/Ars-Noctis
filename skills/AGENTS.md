# Skill 编写规范

## 安装边界

每个直接子目录是一个独立 Skill，目录名与 `SKILL.md` 的 `name` 一致。最小结构为：

```text
<skill>/
├── SKILL.md
└── agents/openai.yaml
```

只在有实际用途时增加 `scripts/`、`references/`、`assets/` 或 `tests/`。不要增加 Skill 级 README、安装指南、变更日志或重复说明。

## 触发与正文

- `SKILL.md` frontmatter 只包含 `name` 和 `description`。
- `description` 同时写明能力、具体适用请求和最邻近的非目标；隐式触发不能依赖正文。
- 正文使用祈使式，只保留决策、边界和最短完整流程，控制在 500 行内。
- 详细契约和长例子只保留一个事实来源，并由 `SKILL.md` 直接说明何时读取；引用不继续要求加载第二层引用。
- `agents/openai.yaml` 使用官方生成脚本维护，default prompt 必须显式包含 `$skill-name`。

## Ars 互操作

只有确实需要被组合的 Skill 才增加 `ars.json`。Manifest 使用 `ars.skill/v1`，只声明 Skill ID、SemVer、capability、统一 envelope 版本和可能副作用；不要暴露模板、脚本、状态文件或私有路径。

- capability 接收 `ars.task/v1`，返回 `ars.result/v1`。
- Manifest effect 是可能性，不是授权。Task effect 是本次计划请求；Run grant 才是经用户授权的范围。
- Provider 不读取其他 Skill 的正文或私有文件，不写 `.noctis/runs/`，只返回 Result。
- Artifact 使用 workspace、git、HTTP(S) URI 或 inline locator；workspace path 必须精确且不可逃逸，commit 必须是可验证的完整 SHA。
- 同 capability 的多个 provider 必须由 Plan 显式绑定；同 ID 的多个 provider 副本视为歧义，不按路径顺序选择。

## 状态与恢复

Noctis 把协议无关的 Plan、Result 和追加事件保存在 Git 跟踪的 `.noctis/runs/<run-id>/`；当前 worktree 的 Git 元数据目录中只保存临时 claim 与当前机器授权，可随时重建且不会被提交。Task 完成只有在状态文件提交后才可供后继领取。Adapter 负责领域契约、产物和副作用证据；Noctis 不得反向依赖 adapter。克隆后没有持久 Result 的旧 `working` Task 恢复为 `pending`；先核对可能已有的外部副作用，再决定是否重试。

## 验证

运行官方 `quick_validate.py`、`scripts/ars.py validate` 和代表性脚本用例。测试至少覆盖公开契约、失败状态、revision 冲突、授权边界与恢复；不要用测试固定实现细节或让被测 Skill 自行产生期望答案。
