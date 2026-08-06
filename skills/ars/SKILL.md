---
name: ars
description: 创建、检查和验证 Noctis 原生 Ars Skill，并生成严格的 ars.yaml 能力、Artifact 与状态契约。用于用户显式调用 `$ars create skill`、要求创建可被 Noctis 原生编排的新 Skill，或需要检查、验证 Ars 目录时；改造已有或第三方 Skill 时改用 `to-ars`。
---

# Ars

只创建、检查和验证原生 Ars。不要改造已有 Skill，不要编排或执行其业务能力。

## 路由

- `$ars create skill`：执行创建流程。
- `$ars inspect <path>`：运行 `scripts/ars.py inspect --skill <path>`，只报告 `native | legacy | external | invalid`。
- `$ars validate <path>`：先运行 `scripts/ars.py validate --skill <path>`，再运行官方 Skill 快速校验。

只有需要解释字段、设计 capability 或诊断校验错误时读取 [contract.md](references/contract.md)。不要为普通 inspect 预读契约。

## 创建原生 Ars

1. 用具体调用示例确认名称、触发条件、职责、非目标和升级边界。
2. 确认角色为 executor 或 support，并逐项确认 capability/support contract。
3. 对 executor 确认 Artifact 输入输出和可能产生的 side effects；没有内容时显式使用空集合。
4. 选择状态模式：`stateless` 无持久状态，`documents` 使用自有结构化文档，`external` 从目标文件或外部工具恢复。
5. 使用当前环境官方 `skill-creator` 的初始化工具创建 Skill 骨架，不自行仿造。
6. 只创建实际需要的 scripts、references、assets 和文档资源。
7. 把 Ars manifest 规范化为 JSON，先执行 `scripts/ars.py create --dry-run`；确认候选后再写入 `ars.yaml`。已有不同文件时必须展示差异并再次确认后使用 `--replace`。
8. 依次运行 `scripts/ars.py validate`、官方 Skill 快速校验和新增脚本的代表性用例。

## 原生不变量

- 目录名、`SKILL.md` name 和 `ars.yaml` name 必须一致。
- Ars 必须既能独立调用，也能按 manifest 由 Noctis 调度。
- 每份原生文档只由所属 Ars 写入；Artifact 只保存引用，不复制其他 Skill 文档。
- 格式兼容时直接传递 ArtifactRef；格式不兼容时使用显式 Adapter Task。
- `side_effects` 只声明可能行为，不授予执行权限。
- 不为无状态 Ars 创建空文档、空脚本或伪恢复流程。

参数和错误输出以 `python scripts/ars.py --help` 为准，不为调用工具读取脚本源码。
