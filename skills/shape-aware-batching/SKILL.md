---
name: shape-aware-batching
description: Build a shape-aware batching scheduler that groups LLM inference requests by hardware-aligned shapes, applies a max-shapes merging strategy under a budget, and emits a per-bucket plan. Use when designing or implementing continuous-batching / shape-padded inference schedulers where the goal is to minimize cost or latency by reducing distinct padded shapes across concurrent sequences.
---

# Shape-aware inference batching scheduler

Implement a scheduler that partitions requests into batches where every batch uses a single padded tensor shape compatible with the serving runtime.

## Inputs

- Request stream from JSONL, one record per request with at minimum: `request_id`, `prompt_len`, `gen_len`. Optional fixed hardware dims: `heads`, `hidden` (often constant per model).
- One or more **bucket** names, each with its own input file. Each bucket produces one plan file.
- Granularity `g` (e.g. 64) — the alignment unit for sequence length.
- Max-shapes budget `S_max` (e.g. 8) — the maximum number of distinct padded shapes allowed per bucket.
- A cost model `cost(shape_tuple, num_requests)` returning estimated latency or compute for a batch with a given shape and request count.

## Procedure

1. **Load requests per bucket.** Parse each bucket's JSONL into a list of records. Keep raw `prompt_len`, `gen_len` and `request_id` together.

2. **Define alignment.** Use `align(x, g) = ((x + g - 1) // g) * g`. For sequence dimension, compute `seq_len_raw = prompt_len + gen_len` (or `prompt_len` if `gen_len` is handled outside the batch shape) per request.

3. **Compute aligned shape per request.** For each request, build a shape tuple from the dimensions that vary in the cost model. Typically just `seq = align(seq_len_raw, g)`. If `heads`/`hidden` vary across requests, align each independently with their own granularities.

4. **Group by shape.** Bucket requests whose aligned shapes are identical into the same group.

5. **Apply the max-shapes merge.** If the number of distinct groups exceeds `S_max`, merge groups using a **smallest-representative-greater-than-or-equal** rule:
   - Sort distinct shapes ascending.
   - Walk left-to-right, assigning each shape to the smallest representative `R` such that `R ≥ shape` and `R` already exists in the current set, or promoting `shape` to a representative if no smaller representative qualifies.
   - Cap representatives at `S_max`; if more promotion is needed, promote greedily into the next free slot, otherwise fall back to the next granularity multiple above the largest shape.
   - Result: each request is mapped to exactly one representative shape.

6. **Build batches.** Within each bucket, one representative shape yields one batch. The batch record carries `batch_id`, the full shape tuple (e.g. `{"seq_align": ..., "heads_align": ..., "hidden_align": ...}`), and the list of `request_id`s assigned to it. Iterate request ids in stable order to keep output deterministic.

7. **Optimize with the cost model.** Sum `cost(shape, count(requests_in_shape))` across batches in the bucket = total bucket cost. To improve the plan, explore alternatives:
   - Try different merge decisions (e.g. rounding some shapes up one more multiple), recompute cost, keep the lowest.
   - If the budget `S_max` is loose, try tightening; if too tight (forces many padding multiples), loosen by one.
   - The optimization loop is optional but typically yields noticeably better plans on real distributions.

8. **Emit per-bucket plans.** Write one JSONL file per input bucket (e.g. `plan_<bucket>.jsonl`). One line per batch, schema:
   ```json
   {"batch_id": 1, "shape": {"seq_align": 1024, "heads_align": 32, "hidden_align": 4096}, "request_ids": ["r1","r2"]}
   ```
   Match input bucket names so the runtime can pair plan → bucket 1:1.

## Notes

- The heads/hidden dimensions are model constants in most cases — only sequence length varies across requests. If they do vary, repeat the align/group/merge steps for each varying dim using the same logic.
- Always validate that the merged representative `R` satisfies `R ≥ every member's raw aligned value`, otherwise padding is insufficient and the runtime will OOB.
- The merge rule is monotonic: raising the representative for one shape never invalidates another shape's assignment that already fits.
- Keep batching independent per bucket — do not reshuffle requests across buckets.