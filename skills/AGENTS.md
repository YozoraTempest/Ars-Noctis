# Skill 编写规范

本目录的每个直接子目录都是独立 Skill，目录名必须与 `SKILL.md` 的 `name` 一致。`ars-noctis` 只做路由；其余 Skill 必须自包含，不依赖路由器或读取兄弟 Skill。

- 每个 Skill 只保留 `SKILL.md` 与有实际用途的 `agents/openai.yaml`；没有确定用途时不增加 scripts、references、assets 或 tests。
- `SKILL.md` frontmatter 只包含 `name` 和可判别的 `description`。
- 原子 Skill 只完成自身 interface，不调用其他 Skill，也不拥有跨 Skill 状态。
- 路由器只选择、加载和排序原子 Skill，不复制其方法正文。
- 不引入 Ars manifest、provider envelope、Task DAG、状态文件或运行时协议。
- 修改后对每个直接子目录运行官方 `quick_validate.py`。
