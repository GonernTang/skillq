# Attribution 误判: verifier 失败被标成 fail_env_issue → 路由黑洞 (Gap 3/5)

**Discovered**: 2026-07-01, small10 batch 复盘
**Severity**: Medium — 失败 trial 的归因被吞, L3 edit 完全错过
**Status**: 未修复

## Summary

当一个 trial verifier 返回 reward=0.0 **但 agent 实际上使用了相关 Skill**时,
L3 attribution analyzer 倾向把这种 case 标成 `fail_env_issue`, 这是一个
**不在 L3/L4 路由表里**的 enum。后果是:

- L3 edit (`step_incremental_edit`) 只匹配 `FAILURE_SKILL_USED`, 不匹配 `FAIL_ENV_ISSUE`
- L4 buffer (`step_dispatch_evolve`) 只匹配 `SUCCESS_NO_SKILL_SEEN` 和 `FAILURE_SKILL_NOT_USED`, 不匹配 `FAIL_ENV_ISSUE`
- Q-update (`step_q_update`) 仍正常执行 (r_task=0 时让 skill Q 值下降)

所以这个 trial 的"failure signal"只反映在 Q-table 衰减里, Skill 本身从来没被
L3 在原地修正, library 也没学到"为什么 sqlite-wal-recovery 用在这里会失败"。

## 现象 (证据)

db-wal-recovery trial 手动重跑 attribution analyzer:

| 字段 | 值 |
|---|---|
| r_task | 0 (verifier 判 0, 因为 recovered.json 只有 5 条记录, WAL 加密部分没解) |
| agent 实际调用的 Skill | `sqlite-wal-recovery` (sim=0.763, top-1) |
| attribution enum | **`fail_env_issue`** (LLM 错判) |
| knowledge_to_extract | "When a SQLite WAL file has a non-standard magic header and contains repetitive b..." (LLM 觉得是 env 问题) |
| library_gap_skill_description | "A skill that provides a procedure for detecting and reversing XOR-based encrypti..." |

### routing 表

| Enum | L3 edit? | L4 CREATE? | Q-update? |
|---|---|---|---|
| SUCCESS_SKILL_USED | – | – | ✓ (r_task=1) |
| SUCCESS_NO_SKILL_SEEN | – | ✓ (success path) | ✓ |
| **FAILURE_SKILL_USED** | **✓** | – | ✓ (r_task=0) |
| **FAILURE_SKILL_NOT_USED** | – | ✓ (failure path) | ✓ |
| **FAIL_ENV_ISSUE** | **–** | **–** | ✓ (r_task=0) |

`FAIL_ENV_ISSUE` 是 routing 表里的**黑洞**: Q-table 衰减, 但 skill 不被 edit,
library 也不增长。

## 根因

### 代码位置

1. `skillq/layers/l3_attribution/prompts.py` ATTRIBUTION_PROMPT
   "fail_env_issue" 的判定标准模糊, LLM 容易把 verifier 失败 → 任务环境复杂
   → 标 fail_env_issue。
2. `skillq/runtime/steps.py:447-468` `step_incremental_edit`:
   ```python
   if (ctx.r_task or not services.lib.skills
       or attribution.overall_attribution != Attribution.FAILURE_SKILL_USED):
       return  # fail_env_issue 路径直接 no-op
   ```
3. `skillq/runtime/steps.py:602-636` `step_dispatch_evolve`:
   ```python
   if knowledge:
       if (r_task and enum == SUCCESS_NO_SKILL_SEEN): ...
       elif (not r_task and enum == FAILURE_SKILL_NOT_USED): ...
   # fail_env_issue 不在 if/elif 里
   ```

### 形成原因

1. 5-enum 设计时 (`SUCCESS_SKILL_USED` / `SUCCESS_NO_SKILL_SEEN` /
   `FAILURE_SKILL_USED` / `FAILURE_SKILL_NOT_USED` / `FAIL_ENV_ISSUE`),
   `FAIL_ENV_ISSUE` 被定位成"无学习价值的失败, 静默忽略",
   适用场景: 容器断网 / docker 镜像缺失 / OOM 等。
2. ATTRIBUTION_PROMPT 把 `fail_env_issue` 的判定标准写得很宽:
   "网络失败 / 依赖缺失 / verifier 无法运行", LLM 在边缘 case (WAL 加密这个题目)
   把"任务需要更复杂的密码学 skill 才能解"误判成"verifier 失败因为 env 太复杂"。
3. analyzer 有一个 `_enforce_consistency` 安全网 (lines 168-221):
   成功 enum + r_task=0 → 强制 `FAILURE_SKILL_USED`;
   失败 enum + r_task=1 → 强制 `SUCCESS_NO_SKILL_SEEN`。
   但 `FAIL_ENV_ISSUE` 在 r_task=0 时**不触发这个 clamp**,
   所以 fail_env_issue + r_task=0 是合法的最终 verdict。
4. db-wal-recovery 这个 case, agent 调了 `sqlite-wal-recovery`, Skill 内容覆盖了
   WAL 损坏识别但**没覆盖 WAL XOR 加密解密**。LLM 看到的现象是
   "verifier 要的数据 agent 没拿到", 倾向归因环境问题。

## 后果

| 维度 | 影响 |
|---|---|
| L3 命中率 | 1 trial 应被 L3 edit → 0 trial 真正 edit |
| Skill 自我修正 | sqlite-wal-recovery 永远停在 v3 的"损坏识别"水平, 没人补 XOR 解密章节 |
| Lib 增长 | 0 (本应产生 1 个 enhanced `sqlite-wal-recovery` 或 1 个新 guard-rail skill) |
| Q-table 信号 | sqlite-wal-recovery Q 0.5 → 0.404 (衰减了, 但 skill body 没动) |
| 复现性 | 下次 trial 调 `sqlite-wal-recovery` 还是拿到同样的内容, 还会失败 |

## 修复方向

### Fix A: prompt 收紧 fail_env_issue 判定标准 (推荐, 改动小)

修改 ATTRIBUTION_PROMPT, 给 fail_env_issue 严格的判定 checklist:

```
fail_env_issue is ONLY appropriate when ALL of the following are true:
- The agent's session log shows NO successful Tool calls
- The agent's transcript indicates an infrastructure failure
  (network timeout, missing dependency, container OOM, docker build failure)
- The verifier did not produce a meaningful reward signal
  (RewardFileNotFoundError, VerifierTimeoutError)

If the agent ran tools, read files, wrote output, and the verifier
returned 0.0 because the output was incorrect, this is NOT fail_env_issue.
Use failure_skill_used (when a skill was called) or failure_skill_not_used
(when no skill was relevant).
```

**优点**: 改动局限在 prompt, 不动 runtime
**风险**: LLM 在边缘 case 仍然可能误判, 但范围会更窄

### Fix B: analyzer 加 post-hoc sanity check (中等改动)

在 `_enforce_consistency` 之后, 加一个 sanity check:

```python
def _enforce_consistency(att, r_task, agent_called_skill: bool):
    # 现有逻辑...
    # 新增: r_task=0 但 agent 实际上调过 Skill → 不允许 fail_env_issue
    if r_task == 0 and att.overall_attribution == Attribution.FAIL_ENV_ISSUE:
        if agent_called_skill:
            return att.model_copy(update={
                "overall_attribution": Attribution.FAILURE_SKILL_USED,
                "overall_rationale": (
                    f"[env-issue-clamp] r_task=0 and Skill was called but "
                    f"LLM returned fail_env_issue; coerced to failure_skill_used. "
                    f"{att.overall_rationale}"
                ),
            })
    return att
```

**优点**: 不依赖 prompt, 行为稳定
**风险**: 需要给 analyzer 加 `agent_called_skill` 参数 (从 calls_log 读)

### Fix C: 把 fail_env_issue 也路由到 L3 edit (推荐同步做)

如果 agent 调过 Skill 且失败, 即便 enum 是 fail_env_issue, 也允许 L3 edit 跑一次:

```python
# step_incremental_edit 守门改为:
if ctx.r_task or not services.lib.skills:
    return
enum = attribution.overall_attribution
if enum not in (Attribution.FAILURE_SKILL_USED, Attribution.FAIL_ENV_ISSUE):
    return
# fail_env_issue 路径: 用 knowledge_to_extract 当 edit signal
```

**优点**: 即便 LLM 误判, skill 仍有机会被改
**风险**: fail_env_issue 的 knowledge 可能描述的是环境问题, 不适合直接喂 edit prompt

## 验证

修复后跑 small10, 预期:
- db-wal-recovery 的 attribution enum 变成 `failure_skill_used` 或 `failure_skill_not_used`
- sqlite-wal-recovery 触发 L3 edit (Fix A 或 B)
- 重跑 batch, db-wal-recovery 拿到新版 skill, 可能 reward 改善

## 相关文件

- `skillq/layers/l3_attribution/prompts.py` — ATTRIBUTION_PROMPT
- `skillq/layers/l3_attribution/analyzer.py:168-221` — `_enforce_consistency`
- `skillq/runtime/steps.py:447-564` — `step_incremental_edit` (L3)
- `skillq/layers/l3_attribution/models.py:32-61` — `Attribution` enum 定义