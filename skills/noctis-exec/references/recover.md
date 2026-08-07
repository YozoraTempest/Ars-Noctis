# 恢复执行流程

只在 active Review/Verify 已记录可达问题或失败，且用户已经确认修复范围后插入恢复流程。未授权时保持当前 Task，不创建 Fix。

## 插入恢复子图

使用 Unit 级 `orchestration splice` 一次完成：

- 结束当前 active Task并记录异常 outcome 和已经产生的 sourceArtifacts；
- 插入新的 Fix、复审或重验 Task；
- 要求所有新 Task 从当前 Task 可达，并汇合到指定 tail；
- 把当前 Task 的 pending 直接后继重接到 tail。

常用形状：

- Review finding：Review → `fix-review` → 新 Review → 原后继；Fix 的 required `review` 输入绑定当前 Review 输出。
- Verify failure：Verify → `fix-verification` → 可选新 Review → 新 Verify → 原后继；Fix 的 required `verification` 输入绑定当前 Verify 输出。

只重接尚未开始的后继。任何后继已 active、completed 或 blocked 时返回 `replan-required`，不要改写已发生历史。

Fix、复审和重验使用新的稳定 Task ID，并固化各自 capability、provider、support、Artifact Binding 与记录路径。新 Task 的输入只能引用 splice 内的直接依赖或已确认外部 Artifact。不要复用旧 Task或维护 resume 队列。

## 完成恢复

Fix 只处理用户接受的 finding/scenario；新 Review 只复核 Fix diff；新 Verify 只重验失败及直接受影响场景。后续 Task 按普通生命周期推进。

一次恢复后再次出现问题时停止并让用户决定是否插入下一轮，不自动形成无限 Fix/Review 或 Fix/Verify 循环。
