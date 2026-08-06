---
name: noctis
description: 交互确认任务与阶段工作流，按项目级注册表调度已注册的执行 Skill 和支撑能力，并用结构化脚本维护 Noctis 父子任务、快照、恢复队列与文档扩展。仅在用户显式调用 Noctis，或明确要求由 Noctis 编排多个能力时使用；不替代执行、审查或验证 Skill。
---

# Noctis

只负责编排。不要实现业务、审查代码、运行测试或判定行为结果。

## 使用工具链

用本 Skill 的脚本操作持久化状态，不直接编辑结构化 Markdown：

- `scripts/init_registry.py`：确定性创建或比较项目级 `Noctis/registry.yaml`。
- `scripts/noctis.py task ...`：创建、定位、读取、更新和迁移 `tasks.md`。
- `scripts/noctis.py extend ...`：在稳定插槽中插入、同步、读取或移除扩展块。

脚本默认输出 JSON；需要展示片段时才使用 `--format markdown`。每次写入使用刚读取到的 `revision` 作为 `--expected-revision`；冲突时重新读取并重新判断，不盲目重试。具体参数以脚本 `--help` 为准。

## 初始化项目注册表

只在用户显式执行 `$noctis init` 时初始化。项目根按以下顺序确定：用户指定路径；多仓库项目的共同工作区根；单仓库项目的仓库根。存在歧义时询问，不硬编码本机路径。

从平台当前可用 Skill 目录读取名称、描述和 locator 元数据，再只读取候选 Skill 同级的 `noctis.yaml`。不要为发现阶段读取任何候选 `SKILL.md`。没有 manifest 的第三方 Skill 只有在用户提供手工映射后才能注册。

发现并规范化以下信息：

- executor 与它处理的 stage/contract；
- support 与适用 contract；
- 文档、模板、工具和 augmentation 声明；
- preset 的 stage 顺序。

同一 stage 或 support 有多个 provider 时列出全部有效选择与差异，让用户决定。manifest 不完整、引用越界或 contract 不兼容时排除该候选并说明原因，不读取其正文猜测。

把选择结果转换为 `init_registry.py` 接受的规范化 JSON。先运行 `--dry-run` 展示候选；用户确认后再创建。已有注册表不同，脚本会返回差异且不覆盖；展示差异并获得第二次明确确认后才能使用 `--replace`。相同输入必须生成逐字节相同结果。

## 解析调用方式

支持两种编排输入：

- `$noctis`、`preset=<id>` 或 stage 数据：按需加载，直到阶段到达才激活对应 executor/support。
- `$noctis $implement $code-review ...`：显式 Skill 由平台提前加载，按用户给出的能力推导 stage 顺序，但仍完整执行任务定位、启动确认、快照和阶段守卫。

显式能力不等于隐藏授权。不要自行添加 unit-test、verify、推送、部署或远程写入。`fix` 只用于失败恢复，不能出现在正常 preset 或用户的初始 workflow 中。

首次使用前要求项目注册表存在。根据当前可用 Skill manifest 重新生成候选并用 `init_registry.py` 比较；若发生 drift，提供三种选择：本次沿用任务快照、明确更新项目注册表、取消。不得静默回退或自动覆盖。

## 启动确认

确认前只允许只读定位。用 `scripts/noctis.py task scan --root <root>` 找到候选任务；优先使用用户指定路径，多个候选时让用户选择，没有记录时预览将创建的位置。

一次性展示：

- 目标、Task/Subtask 路径、新建或恢复状态；
- 当前 stage、完整 workflow、executor 和启用的 support；
- 将维护的文档及本地提交边界；
- 测试、实际行为验证、推送、部署和外部写入是否在范围内。

提供 `A 按当前方案启动`、`B 调整工作流`、`C 取消`。选择 B 时展示所有有效 preset 和自定义 stage 方案，更新后再次确认。只有无歧义的 A 或“确认”才可继续；显式提前加载多个 Skill 也不能省略此确认。

## 创建任务与快照

新任务放在项目根的 `Noctis/<domain>/tasks/<yyyyMMdd>-<slug>/`。多仓库任务创建父 Task，并按仓库或独立交付边界创建直接 Subtask；父 Task 在 `tasks.md` 中声明并行或串行关系。Step 只是 Subtask 内可勾选的实施动作。

用 `task create` 创建记录，输入 title、objective 和 `workflowSnapshot`。快照必须包含本次实际 stage 顺序，以及每个 stage 的 contract、executor provider 和 support provider/激活时机。任务恢复以快照为准，项目注册表只用于新任务或用户确认后的迁移。

用 `task append/update/inspect` 维护任务项。不要直接重写 frontmatter、插槽或 item 标记。父 Task 的进度在子任务检查点同步更新；最后一个 Subtask 完成时，在同一父记录检查点把父 Task 推进到集成 review 或下一 stage。

## 调度阶段

每轮先用 `task inspect` 读取最新状态：

1. 校验 `status: active`、当前 stage 和快照 contract。
2. 激活该 stage 中 `before` support，再激活 executor；`on-request` support 只在执行者实际需要时激活。
3. 通过平台 Skill 机制激活 provider，不直接打开其他 Skill 的 `SKILL.md`。已加载 Skill 的文档工具在后续阶段仍可使用。
4. 执行者返回后重新 inspect。只有记录已按 contract 迁移，才进入下一阶段。

原子 Skill 可以独立使用；未由 Noctis 调度时，不注入 preset、任务快照或隐藏阶段。Noctis 调度下，原子 Skill 的阶段守卫优先于上下文中较早加载的说明。

## 失败恢复

正常完成用 `task transition` 进入快照中的下一 stage，末尾转为 `completed`。审查或验证需要修复时转入 `fix`，并通过 `--resume` 固化修复后的有序返回路径：

- review finding：`review`，然后继续原 workflow；
- verify 失败且原 workflow 含 review：`review verify`；
- verify 失败且无 review：`verify`。

Implement 完成集中修复后使用 `--use-resume`，不得自行计算或跳过返回阶段。阻塞时保留 stage 并设为 `blocked`；只有证据恢复后才继续。

## 扩展文档

各 Skill 拥有自己的模板和文档工具。Noctis 只在显式 workflow 启用某能力时，根据已注册 augmentation 用 `extend insert/upsert/sync` 扩展已经生成的任务文档。支持 `once`、`each` 和指定 `item`；扩展内容可位于文档开头、末尾或稳定 item 插槽。

生成后的任务文档就是该任务的有效模板。扩展立即成为文档的一部分，基础文档工具必须保留未知扩展块；不要修改 Skill 源模板，也不要对未启用能力预埋字段。

## 保持边界

范围、workflow、provider、外部副作用或权限发生实质变化时暂停并重新确认。Noctis 自身只提交任务编排记录，使用 `docs:` Conventional Commit 和对应 `Noctis-Task` trailer。未经明确授权不推送、不部署、不执行远程写入。
