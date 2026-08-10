---
name: ars
description: 创建、迁移、检查或验证带 ars.json 能力清单的 Agent Skill，把 Ars envelope 显式适配到 Noctis，并在 Codex App 中协调单 Agent 或多 Agent 执行。用户要编写可组合 Skill、检查 Ars 契约或建立 Ars-Noctis 执行边界时使用；不要用于普通代码实现、直接调用现有 Skill 或通用工作流状态管理。
---

# Ars

把 Agent Skills 开放目录格式作为安装与触发边界，只为确实需要组合的 Skill 增加 `ars.json`。不要把执行流程、私有文件布局或授权状态复制到 manifest。

## 工作流

1. 阅读目标仓库规则、目标 `SKILL.md`、已有 `ars.json` 和本次工作直接需要的引用。不要预加载无关脚本、测试或资产；用至少两个真实正向请求和两个相邻负向请求确认能力、非目标与触发边界。
2. 新建 Skill 时使用当前宿主提供的官方初始化工具；修改现有 Skill 时保留其公开行为，除非用户明确允许破坏性重构。
3. 先完成标准 `SKILL.md`，再仅为可组合能力创建 `ars.json`。每个 capability 只声明稳定 ID、Task/Result envelope 版本和可能副作用。
4. 运行 `scripts/ars.py validate --skill <目录>`。再运行宿主的官方 Skill 快速校验和至少一个代表性用例。
5. 更新已有或第三方 Skill 时，先执行 `inspect`。只原地修改用户拥有的目录；对不可修改的第三方 Skill 使用官方初始化工具创建独立 Adapter Skill，不读取或导入其私有实现。

## 持久组合

- 单个 Skill 能直接完成时显式调用该 Skill，不创建 Run 或 subagent。
- 只有工作需要持久 Task DAG 时才连接 Noctis。操作前读取 [references/noctis-adapter.md](references/noctis-adapter.md)，使用 `scripts/ars_host.py create|next|finish` 完成常规生命周期。
- 创建前展示每个 Task 的最终 provider、`single/multi`、模型和推理强度绑定；创建或完成后由调用方提交 Noctis 返回的 checkpoint。
- `next` 只向 Agent 返回 `ars.app-dispatch/v1`。`ready/single` 要求 provider 已由用户在当前任务显式选择；`ready/multi` 严格使用 `spawn` 参数；`blocked` 不得静默换模或降级。
- Adapter 校验 provider、capability、effect、workspace、Artifact 和 Git receipt；Noctis 只保存公共 JSON，不解释 Ars 语义或调用模型。
- 动态 Extension、低层 Claim/Result 操作和旧 `.ars/runs` 迁移只按引用文档执行，不自动探测或改写历史。

## 契约边界

- `ars.json` 使用 `ars.skill/v1`，`version` 使用稳定 SemVer。
- capability 接收 `ars.task/v1` 并返回 `ars.result/v1`；业务产物通过 Artifact 引用传递。
- `effects` 只表示能力可能需要的副作用，不代表用户授权。不要声明能力不会实际使用的副作用。
- 不在 manifest 中声明模板、内部状态文件、脚本路径或其他 Skill 的安装路径。
- 不为只需独立调用、没有组合需求的 Skill 强行增加 Ars manifest。

运行命令与完整字段见 `scripts/ars.py --help` 和 `scripts/ars_host.py --help`。需要编写或审查 manifest 时读取 [references/manifest.md](references/manifest.md)；需要让 provider 收发 Ars envelope 时读取 [references/provider-envelope.md](references/provider-envelope.md)；需要连接 Noctis、配置 Codex App runtime 或迁移旧 Run 时读取 [references/noctis-adapter.md](references/noctis-adapter.md)。
