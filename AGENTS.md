# Ars-Noctis 协作规范

## 范围与结构

本仓库维护八个同级、可独立安装的个人 Agent Skills。`skills/ars-noctis/` 是纯路由 Skill；其余七个目录是自包含原子 Skill。

- 仓库根目录不是 Skill，不放置根 `SKILL.md` 或 `agents/openai.yaml`。
- 每个 `skills/<name>/` 是独立安装单元，目录名与 frontmatter `name` 一致。
- `ars-noctis` 只选择、加载和排序原子 Skill，不复制其方法正文。
- 原子 Skill 不依赖路由器、不读取兄弟 Skill、不调用其他 Skill。
- 不增加状态机、Task DAG、provider/adapter 协议、持久运行记录或恢复数据库。
- 不增加 npm 安装器、Plugin 包装、脚本执行层或评测运行时。

## 工作原则

- 修改前阅读本文件、README 和 `skills/AGENTS.md`，保留无关用户修改。
- 默认相信 Agent 具备通用工程能力，只记录稳定、非显而易见且会改变结果的规则。
- Skill 描述必须明确能力、适用请求和相邻非目标，避免原子 Skill 之间职责重叠。
- 只有真实跨能力请求才使用路由器；单个原子 Skill 能完成的任务不得人为拆分。
- 工具可用、登录状态或过去授权均不代表当前授权；外部副作用服从当前用户请求。

## 变更与验证

- 修改任一 Skill 后，对该目录运行官方 `quick_validate.py`。
- 修改路由表、目录结构或共享规则后，对八个 Skill 全部运行官方校验。
- 检查路由链接指向存在的兄弟 `SKILL.md`，并确认每个 `agents/openai.yaml` 的默认提示包含对应 `$skill-name`。
- 不用固定措辞的测试代替 interface 审查；没有确定、重复执行的机械逻辑时不新增 scripts 或 evals。

## Git

- 提交信息使用 Conventional Commits，摘要使用中文。
- 一个提交只覆盖一个原子 Skill 或一个仓库级关注点。
- 提交前检查暂存差异并报告实际验证；未经明确要求，不推送、不发布。
