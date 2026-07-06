---
name: relu-weight-extraction
description: Recover hidden-layer weight rows of a black-box ReLU network via logit-gradient breakpoint detection. Use when stealing/extracting a target layer's weights from a model that exposes only forward (logit) queries — keywords: model-extraction, neural-network-weight-stealing, ReLU activation, gradient breakpoint, sign-change.
---

# ReLU Hidden-Layer Weight Extraction

When a black-box model exposes only logits (or hard-label outputs) but you need the weight matrix of a target hidden ReLU layer, you can recover each row of the weight matrix by finding where the gradient of the target logit with respect to the input changes — every sign-change along a 1-D line reveals one neuron's hyperplane.

## Diagnostic checklist

Run these BEFORE scaling up the extraction to the full neuron budget — each catches a class of false positive that sinks hours of downstream work:

1. **Sanity probe on a tiny known network.** If you have *any* access to the architecture (number of hidden neurons `h`, input dim `d`), run the candidate pipeline on a synthetic model with `h=4` and confirm the recovered rows match the true rows up to sign/permutation. If you have no synthetic, at minimum verify the procedure recovers itself from a random-projection toy model.
2. **Coverage check across many directions.** Sample `>= 10 * h` random unit directions and confirm the number of unique breakpoints you find in the first scan is within ±10% of `h`. If you recover far fewer than `h`, your line-search is missing neurons (false negatives); if you recover many more, you have duplicate/spurious breakpoints (false positives).
3. **Gradient-jump consistency.** For each candidate row `w_i`, verify `||w_i|| ≈ ||Δ∇logit||` along its detection line. A row whose magnitude differs from its gradient-jump magnitude by more than ~20% is almost certainly noise or a duplicate — drop it.
4. **Cosine-duplicate filter.** After collecting all candidate rows, deduplicate by max cosine similarity ≥ 0.99 (after sign-alignment). The number of unique rows must not exceed the expected hidden count; if it does, raise the similarity threshold and re-deduplicate.

## Procedure

1. **Query the oracle.** Given an input `x`, the oracle returns logits `f(x) ∈ R^K`. Pick a target logit `k` (use a random one, repeat for all if you need them all).
2. **Sample directions.** Generate many random unit directions `u` and reference points `x0`. Use both random unit vectors and structured ones (e.g. axis-aligned) — ReLU breakpoints in axis-aligned directions are common and easier to validate first.
3. **Line-search for breakpoints.** Parameterize the line `x(t) = x0 + t*u`. Probe `f_k(x(t))` at fine-grained `t` (binary-search refinement near each candidate sign-change). Each sign-change in `∇_{t} f_k` corresponds to a neuron crossing its activation boundary.
4. **Estimate the row.** Two readings of `∇ f_k` on either side of the breakpoint give the gradient jump `Δg`. The candidate weight row is `w_i ≈ α_i * Δg`, where `α_i` is a non-negative scale absorbed into the row.
5. **Validate per row** (Diagnostic step 3): check that `|α_i|` makes the gradient-jump magnitude consistent with the row's sign-change interval width.
6. **Deduplicate** (Diagnostic step 4) across all directions: pairwise cosine similarity after sign-alignment; merge near-duplicates.
7. **Stop** when you have `h` unique rows, or `>= 2*h` random directions have produced no new rows.

### Estimation refinements

- Prefer **central differences** (`f(x+h)-f(x-h)` over `2h`) over forward differences — halves the bias from any smooth component between breakpoint events.
- For continuous second derivatives, an **analytic gradient** via auto-diff over a differentiable surrogate gives the cleanest breakpoints (only valid if you have a white-box differentiable clone; for pure black-box use central differences).
- When the network is deep, breakpoints in *deeper* layers compound; if the target layer is `L`, try a linear-probe surrogate at intermediate widths to localize the layer.

## Stop signal

If after processing `>= 3 * h` random directions (where `h` is the expected hidden width) the deduplicated row count is **outside `[0.8*h, 1.2*h]`**, stop and reset the architecture:

- Too few rows → your line-search is too coarse or sampling is biased; **double the breakpoint-probe density** and re-run from scratch on fresh directions (do not iterate by tightening thresholds on the same data).
- Too many rows → your duplicate filter is too loose; **raise the cosine threshold to 0.995** and re-merge; if still too many, switch from gradient-jumps to a **second-derivative** test (the jump is real iff the second derivative has a delta-like spike).

If two full passes with these resets still leave the count outside the band, the target layer is NOT a clean single-ReLU layer — the procedure does not apply. Stop and verify the architecture (e.g. confirm activation function, layer count, presence of skip connections) before resuming.