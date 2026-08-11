# Noctis Adapter

只在 Ars 工作要进入 Noctis 时加载本文件。Adapter 位于 `scripts/ars_noctis.py`；常规生命周期使用 `scripts/ars_host.py`，只调用 Noctis 公共 CLI，不导入 Noctis 内部模块。

## 依赖边界

```text
ars.json + ars.plan/v1
        |
        v
  Ars adapter  <---->  Noctis public JSON
        |
        v
ars.task/v1 + ars.result/v1
```

Noctis Core 不发现 provider，不知道 capability、workspace、Artifact 或 effect。Adapter 必须在数据进入 Core 前校验并冻结这些语义，在 Claim 离开 Core 和 Result 返回 Core 时再次校验边界。

## Plan

```powershell
python scripts/ars_noctis.py catalog --skills-root <skills-root>
python scripts/ars_noctis.py plan-adapt --project <project> --plan <ars-plan.json> --skills-root <skills-root> --run-config <app-run-config.json> --explicit-config <app-explicit-config.json> > <noctis-plan.json>
```

`plan-adapt` 执行：

1. 严格校验 `ars.plan/v1`、workspace、Task DAG、provider capability 与 effect 上界。
2. 只为实际使用的 provider/runtime 组合创建 executor；同一 provider 可因 Task 的模型或 Agent 模式不同产生多个 executor。
3. 将 provider ID、版本、capability 和 Codex App runtime 固定到 `ars.executor-snapshot/v2`；不保存安装路径。
4. 将每个 Ars Task 变为 Noctis Task。`ars.binding/v1` 放入 opaque request，effects 映射为 Noctis requirements。

输出可直接交给 `noctis.py plan-check` 和 `run-create`。

## 常规生命周期

Noctis 路径必须显式提供：

```powershell
python scripts/ars_host.py create --project <project> --plan <ars-plan.json> --skills-root <skills-root> --noctis <noctis.py>
# 提交 create 返回的 checkpoint 后再领取 Task
python scripts/ars_host.py next --project <project> --run-id <uuid> --host <app-host.json> --noctis <noctis.py> > <app-dispatch.json>
# 执行 dispatch 指定的 provider，得到 ars-result.json
python scripts/ars_host.py finish --project <project> --result <ars-result.json> --noctis <noctis.py>
```

`create` 在临时目录中完成 Plan 适配与 Noctis 校验，不保留中间 JSON。`next` 让 Noctis 领取指定 Task；省略 `--task-id` 时领取首个 ready Task。完整 `noctis.claim/v1` 保存在 `<git-common-dir>/ars-noctis/claims/<claim-id>.json`，不进入工作树、Git 历史或 Agent 提示；Agent 只接收适配后的 `ars.app-dispatch/v1`。

`finish` 根据 `ars.result/v1` 的 `claim_id` 读取本机 Claim，校验并提交 Noctis Result。只有 Noctis 成功完成 Task 后才删除 Claim 缓存；校验、revision 或 checkpoint 失败时保留缓存供修正后重试。宿主不调用模型，也不自动提交 checkpoint。

运行时 profile 和派发约束不属于常规路径；只有需要自定义绑定时才加载对应引用。动态扩展、低层调试和旧 Run 迁移同样按需加载。
