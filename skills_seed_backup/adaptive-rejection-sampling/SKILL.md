---
name: adaptive-rejection-sampling
description: Implement Adaptive Rejection Sampling (ARS, Gilks & Wild 1992) for log-concave densities. Use when the task involves sampling from a one-dimensional unnormalized density whose log is concave (e.g., truncated normal, exponential, beta on a bounded interval, Gamma with shape≥1). Encodes guard rails for log-concavity verification, boundary handling, location-scale parameters, and the n=1 edge case.
metadata:
  domain: statistical-computing
  algorithm: adaptive-rejection-sampling
---

# Adaptive Rejection Sampling — Guard Rails

ARS is exact (no accept-reject rejection rate) only when the target density `f(x)` is **strictly log-concave** on its support. The piecewise-linear upper hull derived from `h(x) = log f(x)` evaluated at the abscissae must satisfy `h_k(x) >= h(x)` for all `x` in the support. If this invariant is violated, every "exact" sample is silently wrong — there is no rejection step to catch the error.

## Procedure

1. **Confirm log-concavity before writing a single line of the sampler.**
   For analytical `h(x)` (e.g., `dnorm`/`dexp`/`dgamma`), verify mathematically or numerically that `h''(x) <= 0` on the support. If the caller has provided an arbitrary user function, sample `h` at ~50 points across the support and check that second differences are non-positive.
2. **Choose initial abscissae based on the domain.**
   - Full real line `(-Inf, Inf)`: use `mode ± k*sd` with `k ∈ {1, 2}`, plus one extra point far in each tail.
   - Half-line `[a, Inf)`: include the boundary `a` itself and one interior point plus a tail point.
   - Bounded `[a, b]`: include both endpoints.
   Never start with all interior points when the support is half-bounded — the hull will not be defined outside the leftmost abscissa.
3. **Hull construction with location-scale parameters.**
   For the normal distribution with arbitrary `mean` and `sd`, work internally on the standardised density and shift/scale the final samples back. Do **not** naively shift the abscissae by `mean` while leaving the hull heights in the original `sd` scale — the hull will no longer touch `log f`.
4. **Squeeze test on every accepted point.**
   Compute `h(x_star)` at the sampled point. If `h(x_star) <= h_lower(x_star)`, accept without exponentiation (squeeze pass). Otherwise compute `exp(h(x_star) - h_upper(x_star))` for the rejection-shrink step.
5. **Update abscissae set with the accepted point and reset the hull.**
   Sort, deduplicate, and rebuild the piecewise-linear `h_k` and the integral `H_k` segments. Always include the mode abscissa.
6. **Loop termination for `n = 1`.**
   Special-case `n = 1` explicitly: run the sampling loop exactly once and return a length-1 vector. Do not assume the loop's general termination condition covers this branch — many implementations iterate over `range(n)` and mis-handle the boundary.

## Diagnostic checklist

Run these BEFORE committing to the main sampler:

1. **Log-concavity probe.** Evaluate `h(x)` at 100 evenly-spaced points across the support and assert that the second-difference array is `<= 0` everywhere (within `1e-10`). If not, the sampler will not be exact — abort and tell the user, do not "fix" by adding accept-reject.
2. **Hull containment check.** After building the initial hull, sample 1000 random points in the support and assert `h_upper(x) >= h(x)` for every one. Any violation means the abscissae placement or boundary handling is wrong.
3. **n=1 smoke test.** Call the sampler with `n = 1` and confirm it returns a length-1 vector inside the support (no `NaN`, no out-of-range).
4. **Moment comparison.** Generate `N = 10000` samples from a known distribution (e.g., `N(mean, sd)` truncated to `[lo, hi]`) and assert `|sample_mean - theoretical_mean| / theoretical_sd < 0.1` and similarly for variance. Fail loudly otherwise — silent moment drift is the most common ARS bug.

## Stop signal

If any of the four diagnostic checks fails **twice in a row** after fixing the obvious cause (boundary handling, location-scale shift, abscissae placement), stop and re-derive the algorithm from scratch using the Gilks & Wild 1992 pseudocode rather than iterating on a broken architecture. Spending more time tuning initial points or hull-piece counts on a fundamentally non-log-concave or wrongly-parameterised density is wasted effort — switch to plain accept-reject or a non-ARS method (e.g., inverse-CDF for invertible `F`, slice sampling, or HMC if the density is multi-modal) and report the switch to the user.

## Common pitfalls

- **Assuming the caller passes a standard parameterisation.** Normal density with `mean = 5, sd = 3` is not the same as the standard normal shifted/scaled in the same way the user expects. Verify on a hand-computed case.
- **Forgetting the left boundary for `[0, Inf)`.** The first abscissa must be `0` (or arbitrarily close) so the leftmost hull segment exists.
- **Re-using global RNG state across multiple `ars()` calls** without re-seeding the abscissae per call — the second call inherits the first call's hull.
- **Returning `NaN` instead of raising** when the density evaluates to `-Inf` outside the support. Clip to the support boundary explicitly.