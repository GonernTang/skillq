---
name: relu-kink-extraction
description: Recover the first-layer weight matrix of a one-hidden-layer ReLU network from black-box query access by detecting activation kinks along random 1D directions, clustering the jump directions, and merging antipodal pairs. Use when the agent must extract W (or A1) from a piecewise-linear model whose internal parameters are inaccessible.
---

# ReLU Kink-Based Weight Extraction

When a network `f(x) = sum_i a2_i * ReLU(<a1_i, x> + b1_i) + b2` is accessible only as an oracle, every `a1_i` direction is encoded as a **kink** in any 1D slice that crosses the hyperplane `<a1_i, x> + b1_i = 0`. The jump vector at that kink equals `a2_i * a1_i` (up to a scale). Recovering `a1_i` (and `a2_i`) is therefore a problem of (1) finding kinks, (2) measuring jump directions, (3) clustering directions, (4) merging sign pairs, (5) recovering magnitudes.

## Diagnostic checklist (run BEFORE committing to the approach)

1. **Verify the model is piecewise-linear and one-hidden-layer ReLU.** If the target is deeper, has attention/convolutions, or uses smooth activations, kink counts grow combinatorially and a single 1D slice will not be sufficient — switch methods.
2. **Estimate the number of hidden neurons `H` from a calibration sweep.** Pick one random direction, sweep with a fine grid, and count distinct kinks (second-difference peaks above the noise floor). If you cannot find roughly `H` clean kinks on the first sweep, increase the sweep budget or refine the threshold before clustering.
3. **Choose a kink-detection threshold from the noise floor, not from a guess.** Compute the median absolute second difference on a smooth segment and set the detection threshold at ~10× that median. A threshold that is too low produces spurious kinks that pollute clustering; too high hides real ones.
4. **Plan the cluster count and antipodal-merge step up front.** KMeans must be run with `2 * H` clusters (each neuron contributes `+a1` and `-a1` as distinct cluster centroids). Build a plan to pair antipodal centroids before any magnitude recovery — pairing after magnitude estimation is much harder.

## Procedure (and the mistakes to avoid at each step)

- **Sweep**: sample random unit directions `d`, sweep `t ∈ [-T, T]` with fine spacing, record `f(x0 + t*d)`.
- **Detect kinks via second differences**: `Δ²[t] = f[t+1] - 2*f[t] + f[t-1]`. Kinks are local maxima of `|Δ²|` above the threshold. Do **not** threshold on the first difference — that misses zero-crossings of small neurons.
- **Measure the jump**: at each kink, compute `grad_right - grad_left` via finite differences of `f` on either side of the kink. The result is a vector `j` proportional to `a2_i * a1_i`.
- **Normalize BEFORE clustering**: divide each `j` by `||j||`. *Critical mistake to avoid*: clustering the raw `j` vectors. Neurons with tiny `|a2_i|` have tiny `||j||` and either collapse to the origin or get pulled into wrong clusters. Unit-direction clustering handles all magnitudes uniformly.
- **Cluster with `K = 2H`** using KMeans on unit-normalized `j`. Merge antipodal pairs: for each centroid `c`, find the closest `-c` and pair them. Each pair identifies one `a1_i` direction (sign is convention).
- **Recover magnitude**: for each cluster pair, take the **median** of `||j||` across all kinks assigned to that pair. Median (not mean) is robust to the few kinks where multiple neurons activate together.
- **Validate**: compute cosine similarity between recovered rows and ground-truth rows. Because of permutation and sign ambiguity, use the **Hungarian assignment** of recovered rows to ground-truth rows to find the best matching — then report the median cosine similarity of the matched pairs.

## Stop signal

- **Threshold**: if the median cosine similarity of matched pairs is **below 0.9** after one full pipeline run, **STOP and reset**. Do not retry with more sweeps first.
- **Reset actions (in order)**:
  1. Recheck the kink threshold against the noise floor — most failures come from spurious or missed kinks, not from clustering.
  2. Confirm `2H` cluster count matches the actual hidden width — a wrong `K` is the second most common cause.
  3. Verify the unit-normalization step was actually applied before clustering (raw-vector clustering is the dominant bug).
  4. Only then increase the number of sweeps or sweep range.

A second run with the same root cause will produce the same failure; diagnose before re-sampling.