---
name: pytorch-tensor-parallel-linear
description: Implement ColumnParallelLinear and RowParallelLinear modules for PyTorch tensor parallelism. Use when sharding nn.Linear layers across ranks with torch.distributed collectives, when building Megatron-style tensor-parallel MLP/attention blocks, or when distributed linear outputs must match a reference single-GPU linear. Covers all_gather vs all_reduce placement, weight split axes (dim=0 vs dim=1), bias sharding rules, and world_size=1 fallback.
---

# PyTorch Tensor-Parallel Linear Layers

When sharding `nn.Linear` across ranks, use the **two-pattern** design: `ColumnParallel` splits the output dimension, `RowParallel` splits the input dimension. Mixing them up is the #1 source of shape/collective bugs.

## The two patterns

### ColumnParallelLinear (output sharded)
- **Split master weight along `dim=0`** (out_features axis). Each rank holds `out_features // world_size` rows.
- **Shard bias identically** to the weight rows — each rank owns its own bias slice.
- Compute local matmul → add **local bias** → **`all_gather`** outputs along the gathered dim → concatenate into the full output.
- Each rank's output shape before gather: `[..., out_features // world_size]`.

### RowParallelLinear (input sharded)
- **Split master weight along `dim=1`** (in_features axis). Each rank holds `in_features // world_size` columns.
- **Keep the full bias on every rank** (replicated), but **add it AFTER the reduction**, not before.
- Compute local matmul (partial sum) → **`all_reduce`** partial sums across ranks → then add the (replicated) bias.
- Adding bias before all_reduce would sum it `world_size` times — wrong.

## Correctness invariants (must hold)

1. **`all_gather` for Column, `all_reduce` for Row** — never the reverse. ColumnParallel needs the pieces; RowParallel needs the sum.
2. **Bias placement** is asymmetric: Column sharded + added before gather; Row replicated + added after reduce.
3. **Weight split axis** is asymmetric: Column on `dim=0`; Row on `dim=1`.
4. **Single-rank fallback**: guard every collective with `if world_size > 1:` so the module works in unit tests without `torch.distributed.init_process_group`.
5. **Pre-allocate the gather list**: `torch.distributed.all_gather` needs a fixed-size list of output tensors; build it once in `__init__`, not per-forward.
6. **No tensor detachment** — let autograd flow through the collectives so backward works.
7. **Store `out_features_per_rank` / `in_features_per_rank`** as instance attributes for shape assertions in tests.

## Diagnostic checklist

Before declaring the implementation done, run these checks:

1. **`world_size == 1` smoke test**: run `ColumnParallelLinear` and `RowParallelLinear` in a single process with a random input; output shape must equal `nn.Linear(in, out)(input).shape`. If it crashes on a collective, the fallback guard is missing.
2. **Numerical equivalence vs single-GPU reference**: build the equivalent unsharded `nn.Linear`, copy rank-shard `i`'s weight slice into rank `i`'s `ColumnParallelLinear` (along `dim=0`) or `RowParallelLinear` (along `dim=1`), run the same input on both, and assert `torch.allclose(out_parallel, out_single, atol=1e-5)`. Run with `world_size in {2, 4}` — pick a divisor of your test layer width.
3. **Gradient flow check**: call `out.sum().backward()` on the parallel output and the single-GPU output; assert `weight.grad` shapes match (sharded vs full) and that gradients are non-zero on every rank.
4. **Bias-placement check**: temporarily comment out the bias and confirm the parallel output still matches the no-bias single-GPU reference. If it does, bias handling is correct; if it doesn't, you likely added RowParallel bias before the all_reduce.

## Stop signal

If you have rewritten the column/row logic **2 times** and the parallel output still disagrees with the single-GPU reference by more than `atol=1e-5` on `world_size=2`, **stop and re-derive the split axis and collective choice from scratch** — do not iterate a third time. The bug is almost always one of: wrong split dim, wrong collective (gather vs reduce), bias added before reduce, or the gather list not pre-allocated. Re-read the "Correctness invariants" section above before touching code.

## Common pitfalls

- Using `torch.distributed.nn.functional.all_gather` instead of the low-level `torch.distributed.all_gather(tensor_list, tensor)` — the high-level variant expects different argument shapes and silently misaligns.
- Calling `tensor.contiguous()` on the local output **after** adding bias but **before** the all_gather — this is fine, but forgetting `.contiguous()` on the **input to** RowParallel's all_reduce will hang or miscount.
- Forgetting that `torch.distributed.all_gather` is **in-place into a pre-allocated list**, not a function that returns a concatenated tensor.
- Slicing the bias with the wrong shape when `out_features % world_size != 0` — guard against non-divisible widths or assert divisibility in `__init__`.

## Minimal scaffolding

```python
class _AllGatherAlongDim(torch.autograd.Function):
    @staticmethod
    def forward(ctx, x, world_size, gather_list, dim):
        ctx.world_size, ctx.dim = world_size, dim
        x.contiguous()
        torch.distributed.all_gather(gather_list, x)
        return torch.cat(gather_list, dim=dim)

    @staticmethod
    def backward(ctx, grad):
        # Split grad along dim, return this rank's slice
        ...
```

Pair this with a similar `_AllReduceSum` autograd.Function (backward = identity, forward = `torch.distributed.all_reduce`). Wrap the forward path so it short-circuits when `world_size == 1`.