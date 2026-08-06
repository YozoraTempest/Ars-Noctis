---
name: to-ars
description: 将已有自有 Skill 原地转换为 Noctis 原生 Ars，或为第三方、只读和升级频繁的 Skill 创建非侵入 Ars Adapter。用于用户显式调用 `$to-ars`、要求迁移旧 noctis.yaml、接入 OpenSpec、Superpowers 等外部 Skill，或解决跨 Skill 文档和 Artifact 契约冲突时；创建全新 Ars 时改用 `ars`。
---

# To Ars

只迁移或适配已有 Skill。不要重写来源 Skill 的业务流程，也不要把多个外部工作流合并成一个万能 Adapter。

## 评估

1. 激活 `ars`，使用其 `scripts/ars.py inspect --skill <path>` 分类目标。
2. 读取目标 `SKILL.md`、已有 manifest、实际使用的 scripts/references/assets，以及会创建或修改的原生文档。
3. 按 [migration.md](references/migration.md) 形成一份迁移候选，列出 capability、Artifact、状态模式、副作用、文档所有权和路径冲突。
4. 一次展示原地迁移或 Adapter 方案、实际文件变化和行为保持依据；获得明确确认后才编辑。

已经是有效 native Ars 时只报告结果，不制造格式 churn。无效 `ars.yaml` 先报告错误，不用猜测值覆盖。
当前环境缺少 `ars` 时报告公共底座依赖，不复制 Ars Contract 或自行实现另一套校验器。

## 选择方式

- 用户拥有且允许同步修改的 Skill：原地迁移。
- 第三方、只读、安装缓存或会随上游更新的 Skill：创建独立 `<source>-ars-adapter`。
- 只有路径或引用形状不同：Adapter 直接暴露原生产物，不复制内容。
- 需要重新生成或解释内容：创建显式 Adapter capability，由 Noctis 安排独立 Task。

## 原地迁移

保留现有触发语义和核心流程。把旧 `noctis.yaml`、实际文档工具和行为事实映射为 `ars.yaml`；缺少的信息必须确认，不从文件名推断业务契约。

新增或调整资源后，使用已激活 `ars` 暴露的 `scripts/ars.py create --dry-run` 展示 manifest，不拼接固定安装路径。写入并通过 Ars 校验后才移除已被完整替代的旧 `noctis.yaml`。不得同时保留两个权威 manifest。

## 创建 Adapter

使用官方 Skill 初始化工具创建独立 Skill。Adapter 的 description 必须明确来源 Skill 和触发范围；`state.mode` 通常使用 `external`，因为状态仍由来源 Skill 及其原生文档拥有。

Adapter 只负责：激活来源 Skill、提供必要输入、读取其原生产物，并发布 Ars ArtifactRef。不要修改来源文件，不要双向同步文档，不要把 Noctis 状态写回来源状态。

## 验证

完成后依次运行：

1. `ars.py validate`；
2. 官方 Skill 快速校验；
3. 目标新增或变更脚本的代表性用例；
4. 一条独立调用和一条 Noctis 调用的真实触发检查。

迁移只证明结构和桥接有效，不证明来源 Skill 的业务行为已经通过测试。
