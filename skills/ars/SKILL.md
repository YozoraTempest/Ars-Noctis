---
name: ars
description: 创建、迁移、检查或验证带 ars.json 能力清单的 Agent Skill，并把 Ars Plan、Task、Result 或旧 Run 显式适配到 Noctis 公共契约。用户要编写可组合 Skill、检查 Ars 契约或建立 Ars-Noctis 边界时使用；不要用于普通代码实现、直接调用现有 Skill 或通用工作流状态管理。
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
- Noctis 返回 Claim 后，先用 `claim-adapt` 转为 `ars.task/v1`；provider 返回 `ars.result/v1` 后，用 `result-adapt` 包装为 `noctis.result/v1`。
- Adapter 负责 provider capability、effect、workspace、Artifact 和 Git receipt；Noctis 只保存 adapter 输出，不解释这些 Ars 语义。
- 旧 `.ars/runs` 仅通过 `migrate-run` 显式转换。不要让 Noctis 自动探测旧目录，也不要把迁移逻辑放入 Core。

## 契约边界

- `ars.json` 使用 `ars.skill/v1`，`version` 使用稳定 SemVer。
- capability 接收 `ars.task/v1` 并返回 `ars.result/v1`；业务产物通过 Artifact 引用传递。
- `effects` 只表示能力可能需要的副作用，不代表用户授权。不要声明能力不会实际使用的副作用。
- 不在 manifest 中声明模板、内部状态文件、脚本路径或其他 Skill 的安装路径。
- 不为只需独立调用、没有组合需求的 Skill 强行增加 Ars manifest。

运行命令与完整字段见 `scripts/ars.py --help`。需要编写或审查 manifest 时读取 [references/manifest.md](references/manifest.md)；需要让 provider 收发 Ars envelope 时读取 [references/provider-envelope.md](references/provider-envelope.md)；需要连接 Noctis 或迁移旧 Run 时读取 [references/noctis-adapter.md](references/noctis-adapter.md)。
