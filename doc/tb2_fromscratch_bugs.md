# TB 2.0 From-Scratch 全量实验 Bug 清单

**来源**: `tb2_skillq_fromscratch__2026-07-01__19-08-16` (89-task from-scratch)
**配置**: `n_concurrent=4`, `extract_every_n_trials=1`, 空种子技能库
**修复状态**: 已修复的标记 ✅，其余待修

---

## P0: Q-learning 完全失效

### 现象

- Q-table 67 个条目**全部 = 0.5**（seed 默认值），没有任何 Q 值偏离默认
- per-trial `q_table.json` 快照也是全 0.5
- `q_updates.jsonl` 从未被创建（说明 `step_q_update` 的文件写入分支从未执行）

### 根因

`step_q_update` 依赖 `calls_log` (`skillq_skill_calls.jsonl`) 来获取 agent 调用了哪些 Skill。但当前 pull 模式下，L1 钩子通过 `UserPromptSubmit` 把 Top-K 技能推给 agent，agent 读完后**不一定会调用 `Skill()` 工具**——它直接用自己学到的技能内容去解 task，不触发 PreToolUse hook。

```python
# steps.py step_q_update:
calls_log = _read_skill_calls_log(...)   # 读 calls_log
by_skill = {}
for c in calls_log:
    if not c.denied:
        by_skill[c.skill_id].append(c)   # 按 skill_id 分组

if not by_skill:
    return  # ← 99% 的 trial 在这里提前返回
```

calls_log 为空 → `by_skill` 为空 → 提前 return → Q 从不更新 → UCB 项退化为纯 cosine sim。

### 修复方向

**方案 A**（推荐）：让 pull 模式也触发 `Skill()` 调用。L1 推给 agent 时同时要求 agent 必须显式 `Skill(<id>)` 来"注册"它用了哪个技能——这产生 calls_log 条目但不需要额外工具调用成本。

**方案 B**：`step_q_update` 不从 calls_log 读数据，改为从 L1 的 ranking 结果（`l1_sims`）反推"哪些技能被推荐过"，假设被推荐 = 被使用。

---

## P0: Harbor 1h timeout 未生效

### 现象

- 配置了 `override_timeout_sec: 3600.0` + `agent_timeout_multiplier: 1.0`，理论 1h 上限
- `schemelike-metacircular-eval` 跑了 **9h+** 没被 kill
- `extract-moves-from-video` 跑了 **9h+** 没被 kill

### 根因

Harbor 的 timeout计算逻辑位于 `harbor/trial/trial.py:507-525`：

```python
effective_ceiling = min(override, max) * multiplier
```

配置中 `override=3600`，multiplier=1.0，effective=3600s。但 Harbor 在 docker compose 模式下，timeout 可能依赖于 Docker 容器本身的 --stop-timeout 或 compose 的 timeout 设置，而非 Harbor 自身的 kill 信号。当容器内的 claude --print 进程不响应 SIGTERM 时，Harbor 不会发送 SIGKILL。

另一种可能：Harbor 在某些代码路径中覆盖了 `override_timeout_sec`（例如从 agent 配置中读取了不同的 timeout 值）。

### 修复方向

**方案 A**：在 `skillq` 端加独立 watchdog——在每个 trial 的 `on_trial_started` hook 中启动一个 asyncio timer，到时间后直接 `docker kill` 对应的容器。不依赖 Harbor 的 timeout。

**方案 B**：检查 Harbor 源码确认 timeout 的实际生效路径，修 Harbor 的 bug。

---

## P1: LiteLLM stderr 崩溃绕过 try/except ✅ 已修复

### 现象

- `Provider List: https://docs.litellm.ai/docs/providers` 在 stderr 中反复出现
- `circuit-fibsqrt` 的 `step_attribute` 调用崩溃，异常未被 Python try/except 捕获
- `result.json` 永远停在 `mean=? entries=0`（Harbor 未完成写结果）
- `method_errors.jsonl` **未被创建**（说明 `bridge.py` 的大 try/except 没拦住）

### 根因

LiteLLM 在协议/连接层失败时，错误打印到 stderr（`print()` 或 C 层输出），而非抛出 Python Exception。asyncio event loop 被中断或进程收到信号退出——Python 的 `try/except Exception` 抓不到这类崩溃。

```python
# bridge.py _on_trial_ended_new:
try:
    await run_pipeline(ctx, result)      # step_attribute 在此崩溃
except Exception:                        # ← 抓不到 stderr 级崩溃
    logger.exception(...)
```

### 修复（已落地）

`step_attribute` 增加了 try/except + r_task 推断 fallback：

```python
try:
    attribution = ctx.services.attribution_analyzer.analyze(...)
except Exception:
    attribution = TrialAttribution(
        overall_attribution=(
            Attribution.SUCCESS_NO_SKILL_SEEN if ctx.r_task
            else Attribution.FAILURE_SKILL_USED
        ),
        overall_rationale="[attribution-fallback] model call failed",
    )
```

注意：这个修复只覆盖 `step_attribute` 内部的崩溃。如果 LiteLLM 在 `step_incremental_edit`（EditRefiner）或 `step_dispatch_evolve`（extract subprocess）中崩溃，仍然没有保护。

---

## P1: 主机睡眠导致进程死亡 + resume 无效

### 现象

- 主机进入睡眠模式（约 00:53）
- 醒来后 PID 91401 已死，所有 Docker 容器消失
- 重新运行 `skillq paper run` 尝试 resume → 启动即崩，无错误输出
- 4 个 trial（`schemelike-metacircular-eval`, `extract-moves-from-video`, `pytorch-model-cli`, `pytorch-model-recovery`）数据不完整

### 根因

两重问题：

1. **睡眠 kill 进程**：`uv run python -m skillq.cli paper run` 是前台 nohup 进程，睡眠时被操作系统暂停/杀死。Harbor 的 Docker compose 容器也在睡眠期间停止。

2. **resume 失败**：Harbor 的 job resume 依赖 `config.json` 中的 trial 状态。但 `config.json` 里没有 per-trial 完成状态（只有 job 级别配置），Harbor 无法判断哪些 trial 已完成。`skillq paper run` 启动时尝试 resume 但 Harbor 内部崩溃。

### 修复方向

**方案 A**（推荐）：在 `skillq` 端加 checkpoint 机制——每完成一个 trial 的 pipeline，在 `skillq_state/checkpoint.json` 记录完成状态。resume 时读取 checkpoint，只重新调度未完成的 trial。

**方案 B**：使用 `tmux` / `screen` 代替 `nohup`，睡眠时进程保持存活。 + `docker run --restart=always` 让容器在醒来后自动恢复。

### 本次临时恢复手段

手动从旧 run 的 `method_state.json` 提取 67 个 L4 技能 + Q-table → 复制到 `skills/` 目录 → 创建 `fromscratch_resume` config 只跑 4 个残余 task。

---

## P1: `result.json` 无增量保存

### 现象

- 85/89 个 trial 已经完成验证（docker verifier reward.txt 存在）
- 但 `result.json` 一直是 `mean=? entries=0`
- Harbor 只在全部 trial 结束后才写最终结果——过程中崩溃则全丢

### 根因

Harbor 的设计：`result.json` 在 `Job.run()` 结束时一次性写入，不提供中间结果。如果进程在结束前死亡，文件保留初始化状态（`mean=?`）。

### 修复方向

**方案 A**：`on_trial_ended` hook 中手动维护一个 `skillq_state/results.jsonl`——每个 trial 完成时追加一行 `{task_name, reward, ...}`。全量跑完后再汇总。

**方案 B**：修 Harbor 让 `result.json` 在每个 trial 完成后 append 写入（需要 fork Harbor）。

---

## P1: `result.json` 无增量保存 ✅ 已修复

（详见上方 Fix 3：`_write_trial_result` + 最后 trial 自动汇总 `result.json`）

---

## P1: Docker session 文件 root 权限 🔵 WONTFIX

### 现象

- 手动 `docker kill` 容器后，session JSONL 文件仍归 root (uid 0)
- Harbor 无法读取 → trajectory 生成失败 → `Permission denied`
- `schemelike-metacircular-eval` 和 `extract-moves-from-video` 受影响

### 根因

Docker bind mount 的文件在容器内由 root 创建，退出后 host 端文件保持 root 所有权。Harbor 的 `chown_agent_sessions_to_host_user` 只在 trial **正常结束**时调用——手动 kill 的容器不会触发。即使触发，非 root 用户也无权 chown root 文件。

### 为什么不修

1. **触发条件消失**：P0 timeout 修复后不再需要手动 kill 死循环 trial
2. **attribution fallback 兜底**：trajectory 丢失时 `step_attribute` 用 r_task 推断 fallback verdict
3. **修复代价大**：需要改 Docker 镜像或 Harbor fork，改动面远超收益
4. 全量 89 个 trial 中仅影响 2 次，均为手动 kill 场景

---

## P2: schemelike-metacircular-eval 死循环无检测

### 现象

- Agent 输出 114k+ 行，陷入修-测循环
- 每次尝试修解释器 → 跑 test → 挂 → 修 → 循环
- `trace_max_chars=6000` 截断后 attribution LLM 只看到最后 6000 字符的循环尾巴
- 无法提取有意义的教训 → L3 edit / L4 CREATE 无产出

### 根因

`trace_max_chars=6000` 取**尾部最后 6000 字符**。对于死循环 trace，尾部全是重复的修-测模式，不包含初始方案或失败的根本原因。系统没有"卡住检测"机制，依赖 Harbor 的 timeout 来终止——但 timeout 本身也失效了（P0-#2）。

### 修复方向

**方案 A**（推荐）：首尾采样——trace 超长时给 LLM 同时看开头（初始方案 + 首次失败）和结尾（卡在哪里），跳过中间的修-测循环。改动在 `analyzer.py` 的 `_load_session_trace`，~15 行。

**方案 B**：加 loop 检测——如果连续 N 次 assistant 消息内容高度相似（cosine sim > 0.9），提前截断并标记为 stuck。

**方案 C**：基于 trial 总时长动态调整 trace_max_chars——短 trial 给 6000，长 trial 给首尾各 3000。

---

## P2: `run_benchmark.py` 在 nohup 下必崩

### 现象

- `nohup uv run python experiments/run/run_benchmark.py ...` 每次都在 LiteLLM 初始化后无声退出
- 无 stderr / stdout 错误输出
- `skillq paper run` 直接调用则正常

### 根因

`run_benchmark.py` 作为 wrapper 创建子进程调用 `skillq paper run`，nohup 下子进程的 stdout/stderr 管道可能没有被正确转发。或者 Harbor 在初始化阶段尝试读取 tty（progress bar 等），nohup 下没有 tty → cras h。

### 修复方向

**方案 A**（推荐）：在 `run_benchmark.py` 中用 `subprocess.Popen` 并显式捕获 stdout/stderr 到日志文件。

**方案 B**：直接用 `skillq paper run`（当前 workaround）并废弃 `run_benchmark.py` 的 wrapping 逻辑。

---

## P2: Extract 偶发失败 ✅ 已修复（日志增强）

### 现象

- `reshard-c4-data` 的 L4 extract 返回 `None`（extract_batch returned None）
- 其余 66 次 extract 成功（失败率 1.5%）
- 失败原因不明——`extract_failures.jsonl` 只记录了 `reason`，缺少 task 和 knowledge 信息

### 修复

`_write_extract_failure` 增加 `task` 和 `knowledge` 字段（各截断 300 字符），失败率 1.5% 在可接受范围内，不修根因（可能是 LLM 偶发跳过或 `_collect_skill` 校验拒绝），仅增强可观测性。

---

## 修复优先级

| 优先级 | Bug | 影响 | 修复量 |
|---|---|---|---|
| **P0** | Q-learning 失效 | 学习闭环断裂 | 需设计讨论 |
| **P0** | Harbor timeout 失效 | 一个死循环吃 9h | ~20 行 watchdog |
| **P1** | LiteLLM stderr 崩溃 | pipeline 崩 + result 丢失 | ✅ 部分已修 |
| **P1** | 睡眠 resume 无效 | 长跑中断无法恢复 | ~30 行 checkpoint |
| **P1** | result.json 不完整 | 中间崩溃数据全丢 | ~15 行追加写入 |
| **P1** | root 权限文件 | kill 后无法读 trace | ~5 行 chown |
| **P2** | 死循环无检测 | 无效 LLM 调用 | ~15 行首尾采样 |
| **P2** | run_benchmark nohup 崩 | 启动不稳定 | ~10 行 |
| **P2** | extract 偶发失败 | 1/67 丢失 | ~5 行更多 log |
