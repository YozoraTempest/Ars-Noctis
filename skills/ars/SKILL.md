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

## Noctis Adapter

- 需要持久运行 Ars Task 时，用 `scripts/ars_noctis.py` 把 `ars.plan/v1` 转为 `noctis.plan/v1`，再把结果交给独立安装的 Noctis。
- 运行中新增 Ars Task 时，创建 `ars.noctis-extension/v1` 并转为 `noctis.extension/v1`。新 provider 快照随 Extension 加入，不要求初始 Plan 预知所有能力。
- Noctis 返回 Claim 后，Codex App 主路径直接用 `claim-dispatch` 完成 Task 适配和宿主派发；只需导出 Task 时单独使用 `claim-adapt`。provider 返回 `ars.result/v1` 后，用 `result-adapt` 包装为 `noctis.result/v1`。
- Adapter 负责 provider capability、effect、workspace、Artifact 和 Git receipt；Noctis 只保存 adapter 输出，不解释这些 Ars 语义。
- 旧 `.ars/runs` 仅通过 `migrate-run` 显式转换。不要让 Noctis 自动探测旧目录，也不要把迁移逻辑放入 Core。

## Codex App 执行

1. 第一次在仓库组合 Ars 与 Noctis 时运行 `app-profile-init`。默认 profile 位于 Git common metadata，不进入工作树；空 `skills` 表示使用 `single` 并继承主 Agent 的模型与推理强度。
2. 单个 Skill 能直接完成时显式调用该 Skill，由当前 Agent 执行，不创建 Run 或 subagent。
3. 创建 Run 时分别解析当前提示的显式配置、仓库 profile 和可选 Run 配置。按 `显式 > 仓库 > Task > Provider > Run > 主 Agent` 逐字段选择 `agent_mode`、`model` 和 `reasoning_effort`，把结果冻结到 executor snapshot；创建 Run 前向用户展示每个 Task 的最终绑定。
4. 领取 Claim 后，以 Codex App 当前 Agent、用户在当前任务显式选择的 Skills 和 subagent 能力生成临时 `ars.app-host/v1`，运行 `claim-dispatch`。只接受 `single` 或 `multi`；不要根据任务内容自行猜测模式。
5. `ready/single` 仅在 provider 已由用户在当前 App 任务中显式选择时，由当前 Agent 执行 `invocation` 指定的 Skill。`ready/multi` 使用宿主 subagent 能力和 dispatch 的 `spawn` 参数；初始提示已包含 `$<provider>` 与完整 `ars.task/v1`。`spawn` 未提供模型或推理强度字段时继承主 Agent。要隔离 provider 上下文时使用 `multi`。
6. `blocked` 时不要执行 provider 或修改冻结快照。用 Noctis `task-cancel` 取消旧 Task 并清除其本机 Claim，再用更正后的配置创建新 Run 或 Extension Task。不要静默替换模型，不要在 Codex App 主路径退回独立 CLI 进程。当前 Agent 只协调 multi 执行；provider subagent 只返回 `ars.result/v1`，Adapter 校验后再交给 Noctis 完成 Task。

## 契约边界

- `ars.json` 使用 `ars.skill/v1`，`version` 使用稳定 SemVer。
- capability 接收 `ars.task/v1` 并返回 `ars.result/v1`；业务产物通过 Artifact 引用传递。
- `effects` 只表示能力可能需要的副作用，不代表用户授权。不要声明能力不会实际使用的副作用。
- 不在 manifest 中声明模板、内部状态文件、脚本路径或其他 Skill 的安装路径。
- 不为只需独立调用、没有组合需求的 Skill 强行增加 Ars manifest。

运行命令与完整字段见 `scripts/ars.py --help`。需要编写或审查 manifest 时读取 [references/manifest.md](references/manifest.md)；需要让 provider 收发 Ars envelope 时读取 [references/provider-envelope.md](references/provider-envelope.md)；需要连接 Noctis、配置 Codex App runtime 或迁移旧 Run 时读取 [references/noctis-adapter.md](references/noctis-adapter.md)。
