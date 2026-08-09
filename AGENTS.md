# Ars-Noctis 协作规范

## 范围与架构

本仓库维护可独立安装的 Agent Skills、Ars 组合协议，以及协议无关的 Noctis 持久任务运行时。`SKILL.md` 负责触发和行为；`ars.json` 只负责 Ars 能力发现；Noctis 只负责通用 Task DAG、持久状态与公共 envelope 校验。

- 单个 Skill 能完成的任务直接调用，不创建 Noctis Run。
- 每个 `skills/<name>/` 是独立安装单元，不按固定安装路径导入其他 Skill。
- Ars 多 Skill 组合通过 `ars.skill/v1`、`ars.task/v1`、`ars.result/v1` 和 Artifact v1；Ars 通过 adapter 使用 `noctis.*` 公共契约。
- Noctis 是协作式状态内核，不是 Agent 宿主；不得声称脚本能够自行调用模型或 Skill。
- Noctis 不导入 Ars、不扫描 `ars.json`，不得为 implement、code-review、verify 或任何 adapter 增加专用状态或分支。
- Git 跟踪的 `.noctis/runs/<run-id>/` 是 Noctis 项目状态的唯一事实源，只通过 Noctis CLI 追加；Git 元数据目录中的本机缓存可删除且不得复制为项目状态。

## 工作原则

- 修改前阅读本文件和目标目录下更近的 `AGENTS.md`。
- 先用真实正向与相邻负向请求确认触发、职责、非目标和升级边界。
- 默认相信 Agent 具备通用工程能力，只记录稳定、非显而易见且会改变结果的规则。
- 保持渐进披露：元数据负责触发，`SKILL.md` 负责最短完整流程，详细契约按需放入一层 `references/`。
- 结构化契约使用解析器和严格校验，不用字符串拼接维护状态。
- 权限与能力分离；工具可用、登录状态、manifest effect 或旧记录均不代表用户授权。
- 保留工作树中已有且与任务无关的修改。

## 变更与验证

- 新建 Skill 使用当前宿主提供的官方初始化工具。
- 修改 Skill 后运行官方快速校验；修改脚本时运行代表性 CLI 用例和单元测试。
- 修改触发描述时更新不泄露预期答案的正向、负向和重叠评测请求。
- 未经明确要求，不提交、不推送、不发布，也不修改远程状态。

## Git

- 提交信息使用 Conventional Commits，摘要使用中文。
- 一个提交只覆盖一个 Skill、一个共享工具链阶段或一个仓库级关注点。
- 提交前检查暂存差异并报告实际验证。
