---
name: adaptive-llm-batching
description: Adaptive batch scheduler for LLM inference on static-graph accelerators. Use when grouping inference requests into shape-bounded batches under constraints on total cost, padding ratio, P95 latency, and sequential timecost.
---

# Adaptive LLM Inference Batching Scheduler

When scheduling LLM inference requests for static-graph accelerators (where each batch must fit a fixed `(prompt_shape, gen_shape)`), use an adaptive shape-selection and batch-merging procedure. The accelerator's cost model gives you, for any batch shape, a `cost(shape, count)` and a `decode_cost(shape, count)`. Padding ratio is `1 - useful_tokens / shape_tokens`.

## Step 1 — Normalize by alignment granularity

For each request, compute `seq_align = ceil(prompt_len / gran) * gran` using the accelerator's prompt alignment granularity (e.g. 64 or 128 tokens). Track `gen_len` and `prompt_len` separately. This is the unit at which shapes are chosen — without it the distribution looks denser than it really is and shape selection collapses.

## Step 2 — Pick K distinct shapes via weighted quantiles

Build the per-`seq_align` request-count histogram, then sample K distinct `seq_align` values using weighted quantiles over the request counts. K is typically 4–8, chosen so that the largest selected shape covers the long tail while the smallest is well-utilized. The goal is **distribution coverage**, not uniform spacing — most requests should land on a shape with little padding above their `seq_align`.

## Step 3 — Assign each request to the smallest fitting shape

For each request, round up to the smallest selected `seq_align` ≥ the request's `seq_align`. This defines the prompt shape. Reject requests whose `seq_align` exceeds the largest selected shape (or pad them into it, depending on policy).

## Step 4 — Group by gen_len with adaptive windows

Within each prompt-shape bucket, group requests into batches by `gen_len` using a window width that scales with magnitude:

- `gen_len ≤ 50` — require **exact match** (window = 0). Short generations are latency-sensitive and common enough to fill buckets alone.
- `50 < gen_len ≤ 600` — use a small window (e.g. ±1 to ±10 tokens). Wider as `gen_len` grows.
- `gen_len > 600` — use a wider window (±12 to ±25) to merge the long tail.

Sort requests by `gen_len` within each shape before windowing so adjacent buckets can merge predictably.

## Step 5 — Merge small batches by cost, not by size alone

After initial batching, examine every pair of adjacent batches within the same shape. If either batch has ≤ 2 requests, attempt to merge them. **Do not merge unconditionally** — accept the merge only if:

```
decode_cost(merged_shape, merged_count) ≤ decode_cost_a + decode_cost_b + batch_overhead
```

where `batch_overhead` accounts for fixed per-batch setup (kernel launch, shape compile). Without this gate, small-batch merges degrade sequential timecost even when total cost looks fine.

## Step 6 — Iterate to meet all metrics

Compute the four target metrics after each adjustment: total cost, padding ratio, P95 latency (estimated per-request from its batch's decode steps), and sequential timecost (sum of per-batch decode time). If any metric misses its target, adjust in this order:

1. **Padding ratio too high** → increase K (more shapes) or shift quantile weights toward the under-served length region.
2. **Sequential timecost too high** → tighten merge criteria in Step 5 (raise the cost-savings threshold, or skip merges for already-large batches).
3. **Total cost too high** → reduce K, or widen gen_len windows to fill small batches rather than running them half-full.
4. **P95 latency too high** → split the slowest batch by `gen_len` (narrow its window) or move its requests to a larger shape with more parallel decode capacity.

Loop until all four targets pass, or until a step count / time budget is exhausted.

## Cost-model conventions

- `cost(shape, count)` typically decomposes into prefill (proportional to `shape.prompt * count`) plus decode (proportional to `shape.gen * count` and to sequential depth).
- A static-graph accelerator's prefill cost is dominated by the shape's max length, not the actual mean; this is why `seq_align` matters.
- Decode cost is mostly a function of `shape.gen * count` and sequential batching — a merged batch with very different `gen_len` values wastes cycles waiting for the longest member.

## When to prefer this over simpler heuristics

- Workload has a wide `seq_align` range (≥ 10× between shortest and longest).
- Target P95 latency is tight enough that uniform shapes leave too much padding.
- Sequential timecost is part of the SLA, not just total cost — i.e. you can't trade wall-clock for total work.