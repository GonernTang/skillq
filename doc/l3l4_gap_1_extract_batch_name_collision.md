# L4 batched-extract: name collision → 整批丢弃 (Gap 1/5)

**Discovered**: 2026-07-01, small10 batch 复盘
**Severity**: High — 直接吞掉 3 个 trial 的 L4 CREATE 产出
**Status**: 未修复

## Summary

`step_dispatch_evolve` 调用 `SkillExtractor.extract_batch` 生成新 skill 后,
`_flush_buffer` 会做 name-collision 检查。撞名时**整批丢弃**,
而不是给新 skill 加版本后缀或拒绝单条 trial。
small10 batch 中 4 次 `extract_batch` 全部因此返回 `None` / 被丢弃,
最终 0 个新 skill 入库。

## 现象 (证据)

### 现场数据

`tb2_skillq_small10__2026-07-01__11-27-17` 跑完后:

| 指标 | 值 |
|---|---|
| `extract_batch` 子进程调用次数 | **4** (`/tmp/claude-1000/claude-1000/-tmp-claude-1000-skillq-extract-31298-*` 4 个沙盒目录) |
| 新增 skill 数 | **0** (`.skillq_library/.state/method_state.json:library.skills` 仍是 69 个种子 skill) |
| Q-table 非默认条目数 | **4** (都是 q_update 引起,不是 L3 edit) |
| `lib_changes` 持久化 | 无 |

### 重跑 attribution analyzer 预测的 3 个 L4 CREATE 触发 trial

| Trial | 已有同名/近名 skill | LLM 自由发挥可能产出的名字 |
|---|---|---|
| constraints-scheduling | `meeting-scheduler`, `schedule-meeting` | `meeting-scheduler`, `schedule-meeting`, `find-meeting-slot`, `ics-slot-finder` |
| feal-differential-cryptanalysis | `feal-differential-attack` | `feal-differential-attack`, `feal-attack`, `feal-key-recovery` |
| caffe-cifar-10 | 无 caffe 专项 | `caffe-build`, `caffe-cifar-train`, `caffe-cpu-build` |

## 根因

### 代码位置

`skillq/runtime/steps.py:679-697` (`_flush_buffer`):

```python
new_skill = await mode_extractor.extract_batch(trials=batch)
# ...
if new_skill is None:
    logger.info(
        "extract_batch returned no skill (mode=%s, LLM skipped or "
        "output failed); batch of %d records discarded.",
        mode, len(batch),
    )
    continue
if new_skill.skill_id in services.lib:
    logger.warning(
        "extract_batch produced skill %s which is already in lib; "
        "skipping lib.add.",
        new_skill.skill_id,
    )
    continue  # ← 整批丢弃,不开新 skill,不改 Q-table,不动 lib_changes
new_skill.admission_exempt = True
services.lib.add(new_skill)
```

### 形成原因

1. LLM 的命名空间是开放的(`name_min_words=1, name_max_words=4` 的 kebab-case 字符串)。
2. 当 LLM 被给到一个 task, 它倾向于复用自己"概念上已知"的 skill 名。
3. v3 库里 69 个 skill 已经覆盖了大多数常见 task 关键词(meeting, feal, caffe, video-game-move...),
   任何 task→skill 命名大概率撞上。
4. `_flush_buffer` 的 collision 处理只接受 `continue`,**没有版本化逻辑**。

## 后果

| 维度 | 影响 |
|---|---|
| L4 触发率 | 3 trial 应触发 L4 CREATE → 0 trial 成功 |
| Lib 增长 | 0 (本应 +3) |
| Q-table 反馈 | 0 (即使 skill "应该" 学到这些 knowledge, Q 值不会变化) |
| 后续 trial | 这 3 个 task 后续 trial 还会拿同样的 ranking 结果, 因为 library 没变 |
| Audit 可见性 | logger.warning 仅写到 host logger, **不写到 trial_dir** — 用户跑完看 trial.log 看不到原因 |

## 修复方向

### Fix A: 撞名时版本化 (推荐, 改动小)

`_flush_buffer` 撞名分支改为:

```python
if new_skill.skill_id in services.lib:
    new_id = f"{new_skill.skill_id}__v2"
    suffix = 2
    while new_id in services.lib:
        suffix += 1
        new_id = f"{new_skill.skill_id}__v{suffix}"
    logger.info(
        "extract_batch produced skill %s (collision); renaming to %s.",
        new_skill.skill_id, new_id,
    )
    new_skill = new_skill.model_copy(update={"skill_id": new_id})
# 继续走 services.lib.add(new_skill)
```

**优点**: 改动局限, 不破坏现有 LLM 行为, 新旧 skill 并存
**风险**: 可能产生很多 __v2/v3/v4;需要给 L1 hard gate 加 vector-table 备份策略

### Fix B: 撞名时 in-place 替换

如果新 skill 的 `library_gap_skill_description` 跟现有 skill 的 frontmatter
有显著差异 (cosine < 0.7), 视为"实质性新内容", 走 `Qlib.replace` 把旧 skill
的 body 换成新 skill 的 body。

**优点**: 不会膨胀 lib, 旧的 skill 被升级
**风险**: 旧 skill 已经积累的 n_uses/n_success 统计会被丢失;replacement
策略需要更严格的"新比旧好"的判断

### Fix C: 把 collision 信号透出到 trial_dir

不论 Fix A 还是 B, 都同时把 collision 写一行到
`<trial_dir>/skillq_state/lib_changes.jsonl`, 字段:
`{"ts": ..., "kind": "l4_create_collision", "skill_id": ..., "action": "renamed|replaced|discarded"}`

**优点**: 不管选哪种 collision 策略, 用户能从 trial 目录看到 audit trail
**风险**: 无

## 验证

修复后跑 small10 (同样的 10 task + 同样的 attribution model), 预期:
- `extract_batch` 4 次成功 → 至少 3 个新 skill (Fix A 路线)
- `library.skills` 从 69 → ≥ 72
- `library_gap_skill_description` 出现在 audit log

## 相关文件

- `skillq/runtime/steps.py:644-697` — `_flush_buffer` 实现
- `skillq/layers/l4_evolve/create.py:265-376` — `_collect_skill` 校验
- `skillq/layers/l4_evolve/prompts.py` — LLM 命名指引