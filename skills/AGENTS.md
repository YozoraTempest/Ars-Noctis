# Skill 编写规范

当前只有 `ars-noctis` 路由 Skill；原子 Skill 集合等待重新设计。

- 每个直接子目录必须是独立 Skill，目录名与 `SKILL.md` 的 `name` 一致。
- `ars-noctis` 只维护已存在原子 Skill 的选择和排序，不复制其方法正文。
- 原子 Skill 必须自包含，不依赖路由器或读取兄弟 Skill。
- 先确定 interface 再创建新目录，不增加空占位 Skill。
- 每个 Skill 只保留完成自身任务实际需要的 `SKILL.md`、`agents/openai.yaml` 及可选资源。
- 不引入 Ars manifest、provider envelope、Task DAG、状态文件或运行时协议。
- 修改后对相关 Skill 运行官方 `quick_validate.py`。
