# Ars-Noctis 协作规范

## 当前范围

本仓库正在重新设计。当前只保留 `skills/ars-noctis/` 路由 Skill，尚未注册任何原子 Skill。

- 仓库根目录不是 Skill，不放置根 `SKILL.md` 或 `agents/openai.yaml`。
- 路由器只报告注册状态并维护未来路由约束，不执行领域任务。
- 不引用、恢复或隐式兼容已经删除的旧原子 Skill。
- 不增加状态机、Task DAG、provider/adapter 协议、持久运行记录或恢复数据库。
- 不增加 npm 安装器、Plugin 包装、脚本执行层或评测运行时。

## 重新设计

- 创建原子 Skill 前先明确用户请求、可观察结果、interface 和相邻非目标。
- 每个 `skills/<name>/` 必须是独立安装单元，目录名与 frontmatter `name` 一致。
- 原子 Skill 不依赖路由器、不读取兄弟 Skill、不调用其他 Skill。
- 只有原子 Skill 的 interface 已经确定并落盘后，才更新 `ars-noctis` 路由表。
- 不预先创建空目录、占位 Skill 或猜测未来分类。
- 工具可用、登录状态或过去授权均不代表当前授权；外部副作用服从当前用户请求。

## 变更与验证

- 修改任一 Skill 后，对该目录运行官方 `quick_validate.py`。
- 修改目录结构或路由注册时，检查每个路由链接都指向存在的兄弟 `SKILL.md`。
- 新增或删除原子 Skill 时同步更新 README 和 `skills/AGENTS.md`。
- 没有确定、重复执行的机械逻辑时不新增 scripts、evals 或 tests。

## Git

- 提交信息使用 Conventional Commits，摘要使用中文。
- 一个提交只覆盖一个原子 Skill 或一个仓库级关注点。
- 提交前检查暂存差异并报告实际验证；未经明确要求，不推送、不发布。
