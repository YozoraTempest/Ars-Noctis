# 初始化项目注册表

只在用户显式执行 `$noctis init` 时初始化。

## 确定项目根

按以下顺序选择：用户指定路径；多仓库项目的共同工作区根；单仓库项目的仓库根。存在歧义时询问，不硬编码本机路径。

## 发现能力

从平台当前可用 Skill 目录读取名称、描述和 locator，再只读取候选 Skill 同级的 `noctis.yaml`。不要读取候选 `SKILL.md` 来发现能力。

规范化以下信息：

- executor 与它提供的 capability/contract；
- support 与 contract、激活时机；
- 文档、模板、工具与 augmentation；
- Workflow Template 的 Task、capability 与依赖。

manifest 不完整、资源路径逃逸 Skill 目录或 contract 不兼容时排除候选并说明原因。同一 capability/support 有多个 provider 时展示全部有效选择，不按路径顺序暗中决定。没有 manifest 的第三方 Skill 仅在用户提供手工映射后注册。

## 写入注册表

把选择结果转换为 `init_registry.py` 接受的规范化 JSON：

1. 先用 `--dry-run` 展示确定性候选内容。
2. 用户确认后创建 `Noctis/registry.yaml`。
3. 已有内容相同时保持不变。
4. 已有内容不同时展示差异；获得第二次明确确认后才能使用 `--replace`。

相同输入必须生成逐字节一致的注册表。初始化不创建 Work、Unit 或 Task，也不激活任何 executor。
