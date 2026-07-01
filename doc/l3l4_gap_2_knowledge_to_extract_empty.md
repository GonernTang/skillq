# L4 dispatch guard: knowledge_to_extract 空字符串 → 整条 trial 跳过 (Gap 2/5)

**Discovered**: 2026-07-01, small10 batch 复盘
**Severity**: Medium — 静默丢失 trial 的 attribution 价值
**Status**: 未修复

## Summary

`step_dispatch_evolve` 用 `if knowledge:` 字符串真值守门,
只要 LLM 返回的 `knowledge_to_extract` 是空字符串, 整条 SUCCESS_NO_SKILL_SEEN
trial 就被跳过, 不会进 extract buffer, 也不会触发 L4 CREATE。
但 LLM 仍把 attribution 写成 success_no_skill_seen — 用户从 attribution 端
看不出"为什么没触发"。

## 现象 (证据)

small10 batch 手动重跑 attribution analyzer 的结果:

| Trial | r_task | enum | knowledge_to_extract | 实际触发? |
|---|---|---|---|---|
| cobol-modernization | 1 | success_no_skill_seen | **(空)** | ❌ 被守门跳过 |
| distribution-search | 1 | success_no_skill_seen | **(空)** | ❌ 被守门跳过 |
| constraints-scheduling | 1 | success_no_skill_seen | "Procedure for multi-attendee meeting slot..." | ✅ 进 buffer |
| feal-differential | 1 | success_no_skill_seen | "To attack a FEAL-like 4-round..." | ✅ 进 buffer |

cobol-modernization 和 distribution-search 都成功通过 verifier (reward=1.0),
agent 用了相关 Skill 后 trial 成功。但 attribution 端返回空 knowledge,
导致 L4 CREATE 不触发, 这些"成功路径"没有被 L4 收割到 library 里。

## 根因

### 代码位置

`skillq/runtime/steps.py:602-636` (`step_dispatch_evolve`):

```python
knowledge = attribution.knowledge_to_extract.strip()
gap_description = attribution.library_gap_skill_description.strip()
triggered = False

if knowledge:                                # ← 守门, 空字符串直接 skip
    if (ctx.r_task
        and attribution.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN):
        buffer_full = services.extract_buffer.add(...)
        triggered = True
    elif (not ctx.r_task
        and attribution.overall_attribution == Attribution.FAILURE_SKILL_NOT_USED):
        buffer_full = services.extract_buffer.add(...)
            triggered = True
            ...

if not triggered:
    return
```

### 形成原因

1. ATTRIBUTION_PROMPT (`skillq/layers/l3_attribution/prompts.py`) 让 LLM 在 success 路径写
   `knowledge_to_extract`, 但**没强制要求非空**。
2. 当 LLM 看到 agent 用了一个**高度匹配的** skill (例如 cobol-to-python sim=0.644, kl-distribution-search sim=0.779),
   LLM 倾向于认为"这个 trial 没新东西值得 harvest, 现有 skill 已经够了", 所以写空 knowledge。
3. `step_dispatch_evolve` 用 `if knowledge:` 当守门, 把"LLM 说没事可 harvest"误读成
   "不要触发 L4"。

这是一个**设计缺陷**: enum 已经说"SUCCESS_NO_SKILL_SEEN" (= "library 缺相关 skill,
需要 L4 CREATE 一个"), 但下游守门又说"knowledge 空, 没法 harvest", 两个信号互相矛盾。

## 后果

| 维度 | 影响 |
|---|---|
| L4 触发率 | 2 trial 应触发 → 0 trial 成功 |
| 库增长 | 0 (即使 task 跟 library 完全不重合, enum 也被屏蔽) |
| 鲁棒性 | LLM 行为依赖, prompt 微调就可能导致这 2 trial 永久跳过 |
| Attribution 价值 | enum 字段 + knowledge 字段不一致, audit 时容易迷惑 |

## 修复方向

### Fix A: prompt 强制 knowledge 非空 (改动小, 推荐)

修改 `ATTRIBUTION_PROMPT`, 在 success-no-skill-seen 路径加硬约束:

```
If overall_attribution is success_no_skill_seen, you MUST populate
knowledge_to_extract with a non-empty procedural summary (≥ 50 words)
describing the reusable method the agent used. Empty knowledge is
inconsistent with this enum and will be rejected by the pipeline.
```

**优点**: 改动局限在 prompt, 不动 runtime 代码
**风险**: LLM 可能在压力下编造质量低的 knowledge, 喂给 extract → 出垃圾 skill

### Fix B: enum 降级 (改动中等)

`step_dispatch_evolve` 在 knowledge 为空时:

```python
if knowledge:
    # 现有路径
elif attribution.overall_attribution == Attribution.SUCCESS_NO_SKILL_SEEN:
    # enum 说要 harvest 但 knowledge 空 → 强制用 library_gap_skill_description 兜底
    knowledge = gap_description
    if knowledge:
        # 进 buffer 用 gap_description 当 seed
```

**优点**: 即便 LLM 输出空 knowledge, pipeline 仍用 gap description 兜底
**风险**: gap_description 可能跟 task 关联度比 knowledge_to_extract 低

### Fix C: enum 路由加 warning (推荐做, 低成本)

在守门处加 metric:

```python
if not knowledge:
    if attribution.overall_attribution in (
        Attribution.SUCCESS_NO_SKILL_SEEN,
        Attribution.FAILURE_SKILL_NOT_USED,
    ):
        logger.warning(
            "l4_dispatch_skipped_empty_knowledge: trial=%s enum=%s",
            ctx.trial_id,
            attribution.overall_attribution.value,
        )
```

**优点**: 让"enum 说 harvest 但 knowledge 空"这件事在 host log 显式可见
**风险**: 无

## 验证

修复后跑 small10, 预期:
- cobol-modernization / distribution-search 至少其中一个被记入 warning
  (Fix C 路线) 或实际触发 L4 (Fix A/B 路线)
- 重跑 attribution 时 empty knowledge 比例从 2/8 降到 0/8

## 相关文件

- `skillq/runtime/steps.py:570-641` — `step_dispatch_evolve`
- `skillq/layers/l3_attribution/prompts.py` — ATTRIBUTION_PROMPT
- `skillq/layers/l3_attribution/models.py:102-108` — `TrialAttribution` 字段定义