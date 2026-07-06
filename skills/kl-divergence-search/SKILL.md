---
name: kl-divergence-search
description: Find a probability distribution satisfying one or more KL divergence targets by parameterizing the distribution through a small number of classes (count + probability-ratio per class), deriving closed-form KL expressions, and optimizing continuous parameters with scipy.optimize while brute-forcing any small integer counts.
---

# Fitting a distribution to KL divergence targets

Use this procedure when you need a discrete probability vector `P` of length `N` (often a large vocabulary) such that one or more divergences between `P` and a known reference distribution `Q` (commonly uniform `U`) hit specific numeric targets, e.g. `KL(P || Q) = c` and/or `KL(Q || P) = c`.

## When to use

- You are given divergence targets and need a distribution that satisfies them.
- The full distribution is too large to optimize directly, but its structure is "blocky": a few groups, each with a shared probability ratio and an integer count of members.
- Closed-form forward/backward KL between `P` and a uniform `Q` can be written from the group parameters.

## Procedure

1. **Cluster the support into K classes.** Each class `i` is described by:
   - `n_i` — integer count of tokens in the class (often small: 1, 2, 3, ...).
   - `r_i` — probability ratio (e.g. `r_i > 1` for "hot", `r_i = 1` for baseline, `r_i < 1` for "cold"), continuous.
   - Sum constraint: `Σ n_i = N`, classes partition the support.

2. **Normalize the distribution analytically.** Let the baseline mass be:
   `B = N / (Σ_i n_i / r_i)`
   Then `p_i = r_i / B` for each class. Multiplying by `r_i` within a class gives the per-token probability.

3. **Derive closed-form KL expressions** in terms of `{n_i}` and `{r_i}`.
   - Forward `KL(P || U) = log(r) + (p - 1/N) · r · n` summed per class, where `r` is the effective ratio after normalization.
   - Backward `KL(U || P) = -log(r) - (1/N) · (1/r) summed and inverted appropriately.
   - Use `log` (natural). Compute each divergence in one pass over the K classes, not over N tokens.

4. **Formulate the objective.** For targets `(t1, t2, ...)`:
   - Sum of squared deviations: `f = Σ (KL_j(P) - t_j)^2`, or
   - Sum of absolute deviations if you need a sharper penalty near zero.
   - Add a small regularization on `B` only if needed; the normalization already enforces a valid distribution.

5. **Set up the optimization.**
   - Continuous variables: the `r_i` for the non-baseline classes (the baseline class is pinned at `r = 1` or used to set `B`). Use `scipy.optimize.minimize` with `method='L-BFGS-B'`.
   - Bounds: enforce ordering (e.g. `r_hot >= r_warm >= r_cold`); all ratios strictly positive (`r_i > 0`); baseline class may be fixed.
   - Integer variables: the small class sizes `n_i`. Brute-force over plausible tuples (1, 2, 3; 1, 2; etc.) when the count space is tiny. Wrap the continuous optimize inside the brute-force loop.

6. **Solve and select.** Run the optimization for each integer tuple. Pick the tuple whose best objective is below tolerance; keep both the parameters and the achieved divergences for that tuple.

7. **Reconstruct the full vector.** Expand classes back to length `N` (each class `i` contributes `n_i` copies of its class probability). Verify:
   - All entries non-negative.
   - Sums to 1 within float tolerance.
   - Each target divergence is within the agreed tolerance.

8. **Persist.** Save the resulting vector as a `.npy` file and record the achieved divergence values alongside (printed, logged, or written to a small metadata file).

## Guardrails

- Always verify normalization and KL values after reconstruction — optimizer-internal values can drift due to float reduction.
- If no tuple of integer counts reaches the tolerance, broaden the brute-force grid or relax ordering, do not silently accept a bad fit.
- Keep `K` small (3–5). Beyond that, the brute-force over `n_i` explodes and the closed-form advantage is lost.
- Use `np.log` carefully — collapse-by-zero in `KL(U||P)` when any class probability is exactly 0; guard with `eps` on `r_i`.