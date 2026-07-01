# extract_every_n_trials=1: 单次失败 = 单 trial 永久丢失 (Gap 4/5)

**Discovered**: 2026-07-01, small10 batch 复盘
**Severity**: High — 配置选择直接放大其他 Gap 的影响
**Status**: 未修复

## Summary

small10 用的 `tb2_skillq_small10.yaml` 把 `evolve.extract_every_n_trials` 设成 `1`,
意思是 buffer 里累积 1 条 trial 记录就立刻 flush, 触发一次 `claude --print` 子进程。
这个配置跟 L4 batched-extract 的"agggregate N trials → 1 个 skill" 设计精神相反:

- 阈值=4 (lqrl 默认): 1 次 extract 失败只丢最多 4 trial, 还有下一次 retry
- 阈值=1: 1 次 extract 失败 = 1 trial 永久丢失, 没有重试

small10 batch 4 次 extract 全部失败 = 4 个 trial 的 L4 价值被永久吞掉。

## 现象 (证据)

### 配置

`experiments/configs/tb2_skillq_small10.yaml`:
```yaml
evolve:
  enabled: true
  extract_every_n_trials: 1      # ← 每 1 个 qualifying trial 触发一次
  enforce_failure_skill_structure: true
```

### 现场

`tb2_skillq_small10__2026-07-01__11-27-17` extract 子进程调用:

| 时段 (CST) | 触发源 | 返回值 |
|---|---|---|
| 11:29:10 | 某次 trial 触发 (估计 constraints-scheduling) | `None` (被拒收, 见 Gap 1) |
| 11:32:07 | 某次 trial 触发 (估计 feal-differential) | `None` |
| 11:33:24 | 某次 trial 触发 (估计 caffe-cifar-10) | `None` |
| 11:42:08 | final-trial force flush (估计 leftover buffer) | `None` |

`step_dispatch_evolve:640`:
```python
# Final-trial force flush.
if services.state.step + 1 >= services.expected_terminal_trials:
    await _flush_buffer(ctx, result)
```

### Q 增长 vs Q 衰减

| 事件 | 数值 |
|---|---|
| 应该产出的 L4 skill | 3 (按 attribution enum 推断) |
| 实际产出的 L4 skill | 0 |
| L4 路径的 trial 永久丢失率 | 100% (4/4 extract 调用全失败) |

## 根因

### 代码位置

1. `skillq/runtime/bridge.py:230`:
   ```python
   extract_buffer = ExtractBuffer(n_trials_threshold=method.extract_every_n_trials)
   ```
   直接用 `method.extract_every_n_trials` 作 threshold, 没做最小值守门。

2. `skillq/layers/l4_evolve/extract_buffer.py:41-74`:
   ```python
   @dataclass
   class ExtractBuffer:
       n_trials_threshold: int
       pending: list[dict[str, Any]] = field(default_factory=list)

       def add(self, ...) -> bool:
           if not knowledge.strip():
               return False
           self.pending.append({...})
           return len(self.pending) >= self.n_trials_threshold  # ≥ threshold 就 flush
   ```
   Threshold=1 时, add 一次就 return True, 调用方立刻 flush。

3. `skillq/config.py:437-453`:
   ```python
   extract_every_n_trials: int = Field(
       default=4, ge=1,
       description="...Default 4 mirrors SkillsVote's evolve_every_n_trials=1 default..."
   )
   ```
   Config 默认 4, 但 user 设成 1 是允许的 (`ge=1`)。

### 形成原因

1. 用户的考量可能是"small batch 跑得快点, 阈值小 = L4 反应快"。
2. 但 `_flush_buffer` 是 fire-and-forget 一次性, 没有 retry queue 也没有
   "如果 extract 失败, 把 records 留在 buffer 等下次 trial 合并" 的逻辑。
3. 失败 = `batch 丢弃` (Gap 1) **AND** records 也丢失 — 没有 fallback 把
   records 存到 disk 留作后续 retry。
4. 配置 `ge=1` 没下限保护, 让 user 可以设成 1。

## 后果

| 维度 | 影响 |
|---|---|
| 单次失败影响面 | 1 trial 永久丢失 (vs 阈值=4 时的 1/4 trial) |
| Library 增长 | 0 (small10 batch 4 次失败 = 0 skill) |
| Audit trail | 无 — `batch of N records discarded` 只在 logger, 不写到 trial_dir |
| Retry 机会 | 0 — records 在 buffer 里被 flush 一次就清空 |
| Gap 1 / Gap 5 放大 | 这两个 Gap 的影响在 threshold=1 下是 4 倍放大 |

## 修复方向

### Fix A: 配置下限 + 推荐值 (推荐, 改动小)

`skillq/config.py:437`:
```python
extract_every_n_trials: int = Field(
    default=4, ge=2,  # 改 ge=2, 至少 2 个 trial 才能 flush
    description=(
        "...Batched-evolve flush cadence. Recommended ≥ 4 for "
        "production runs; threshold=2 minimum to ensure batch "
        "aggregation is meaningful. Threshold=1 is allowed only "
        "for debugging (every qualifying trial spawns one extract "
        "subprocess; no aggregation, no retry)."
    ),
)
```

**优点**: 防止用户再次设成 1; 默认 4 已经是行业最佳实践
**风险**: 老 config 里 hardcoded `1` 的会被 pydantic 拒绝, 需要先迁移

### Fix B: extract 失败时把 records 持久化 (中等改动)

`step_dispatch_evolve` 的失败分支:
```python
async def _flush_buffer(ctx, result):
    groups = services.extract_buffer.flush()
    for mode, batch in groups:
        if not batch:
            continue
        try:
            new_skill = await mode_extractor.extract_batch(trials=batch)
        except Exception:
            logger.exception(...)
            # 新增: 把 records 写到 disk 作为 pending retry
            services.pending_extract_queue.extend([(mode, r) for r in batch])
            continue
        if new_skill is None:
            # 新增: 同样进 retry queue
            services.pending_extract_queue.extend([(mode, r) for r in batch])
            continue
        # ...
```

后续 trial 开始前, step_classify_failure 之前:
```python
async def step_retry_pending_extract(ctx, result):
    """每次 on_trial_started 前重试 pending queue, 阈值合并."""
    if len(services.pending_extract_queue) >= method.extract_every_n_trials:
        # 把 queue 内容灌进 extract_buffer, 触发正常 flush 路径
        ...
```

**优点**: 即便 extract 失败, records 不丢, 下次 batch 自动 retry
**风险**: pending queue 可能膨胀, 需要 upper bound

### Fix C: 失败时打 warning 到 trial_dir (推荐同步做)

跟 Gap 1 Fix C 类似:

```python
if new_skill is None:
    err_path = ctx.trial_dir / "skillq_state" / "extract_failures.jsonl"
    err_path.parent.mkdir(parents=True, exist_ok=True)
    with open(err_path, "a") as f:
        f.write(json.dumps({
            "ts": time.time(),
            "trial_id": ctx.trial_id,
            "mode": mode,
            "n_records": len(batch),
            "reason": "extract_batch returned None",
        }) + "\n")
```

**优点**: 用户从 trial 目录能看到 L4 失败原因
**风险**: 无

## 验证

修复后跑 small10 + 同样 4 个 extract 触发 trial, 预期:
- 配置 Fix A: pydantic 拒绝 threshold=1, 强制 ≥ 2
- 重试 Fix B: 4 次失败 → 留下 4 条 pending records → 下一 batch 合并 retry
- 审计 Fix C: trial_dir 下能看到 4 条 extract_failures.jsonl 记录

## 相关文件

- `skillq/config.py:437-453` — `extract_every_n_trials` 字段定义
- `skillq/runtime/bridge.py:222-243` — `SkillExtractor` / `ExtractBuffer` 构造
- `skillq/runtime/steps.py:570-641` — `step_dispatch_evolve`
- `skillq/layers/l4_evolve/extract_buffer.py` — `ExtractBuffer` 实现