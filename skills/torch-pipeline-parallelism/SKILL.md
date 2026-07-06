---
name: torch-pipeline-parallelism
description: Step-by-step implementation of All-Forward-All-Backward (AFAB) pipeline parallelism for PyTorch Transformer models. Use when partitioning a model across ranks with send/recv P2POp primitives, applying microbatch gradient accumulation, or scaling cross-entropy loss by the number of microbatches. Triggers on tasks mentioning pipeline-parallelism, torch distributed pipeline, layer-partitioned training, or AFAB scheduling.
---

# Torch Pipeline Parallelism (AFAB)

## When to use

- Multi-rank training where model layers are sharded across `world_size` ranks and activations are passed via `torch.distributed`.
- The loss must be computed once per microbatch and gradients must accumulate across all microbatches before the optimizer step.
- `world_size == 1` must run as a no-communication fallback (no `send`/`recv`, no `ProcessGroup` ops).

## Procedure

1. **Layer partitioning** — Compute each rank's layer slice so that `total_layers % world_size == 0`. Handle non-divisible cases with a remainder distribution (first N ranks get +1 layer). Rank `r` owns layers `[r * per_rank, (r+1) * per_rank)` (plus remainder offset). Embedding lives on rank 0; final norm + output projection + loss live on the last rank.

2. **Forward phase (all microbatches)** — Loop `m = 0 .. num_microbatches - 1`:
   - **Rank 0:** embed inputs → run its layer slice → `dist.send(hidden, dst=1)` (skip if last).
   - **Middle ranks:** `dist.send(recv_in, src=r-1)` → run layers → `send(hidden, dst=r+1)`.
   - **Last rank:** `recv_in = dist.recv(src=last-1)` (skip if only rank) → run layers → apply final norm + output projection → compute cross-entropy loss → `loss = loss / num_microbatches` → `loss.backward()`.
   - Keep gradients between microbatches (do NOT zero between fwd/bwd cycles).

3. **Backward phase (all microbatches, in same order)** — Loop `m = 0 .. num_microbatches - 1`:
   - Last rank already triggered backward. For every other rank, on the backward pass: receive gradient from `dst=r+1`, run `backward()` on the stored activations, then `dist.send(grad, dst=r-1)`.
   - First rank has no upstream `send`.

4. **Grad/optimizer boundary** — Before the schedule: call `model.zero_grad()` (or set `param.grad = None`). After both phases finish: call `optimizer.step()` and `optimizer.zero_grad()`. **Do NOT call `optimizer.step()` inside the per-microbatch loop.**

5. **Single-rank fallback** — When `world_size == 1`, skip every `send`/`recv`, run all layers, compute loss, scale by `num_microbatches`, `backward()`, then `optimizer.step()`. The schedule must be identical to the multi-rank path minus the comms.

## Diagnostic checklist

Run ALL of these BEFORE scaling up from a 2-rank smoke test:

1. **Layer slice check:** Print `f"rank {r} owns layers {start}..{end}"` for every rank and confirm `[start, end)` partitions `[0, total_layers)` with no gap or overlap.
2. **world_size=1 no-op:** Run the full train step with `world_size=1` and confirm `dist.send`/`dist.recv` are never called (use a counter or grep).
3. **Loss scaling:** Verify `loss = raw_loss / num_microbatches` occurs BEFORE `.backward()`, and that gradients after all microbatches equal `sum_i grad_i` (PyTorch accumulates `.backward()` calls on the same graph leaves automatically).
4. **Boundary rank symmetry:** Rank 0 has no `recv`; last rank has no `send` of hidden state forward (its loss.backward handles the chain); first rank has no backward `send` to a `-1` rank.

## Stop signal

- If you have written **2** versions of the AFAB step and they still fail any of the four diagnostic checks above (especially loss scaling or boundary-rank send/recv), STOP iterating. Re-derive the schedule from this template rather than patching. A third attempt on the same architecture is almost guaranteed to repeat the same mistake (the layer-slice / loss-scale / send-recv ordering is fragile to local edits).
- If gradients explode or are zero after `optimizer.step()`, the loss was not scaled by `num_microbatches` — re-check item 3 of the diagnostic checklist before touching the optimizer.