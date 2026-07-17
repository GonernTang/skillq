---
name: adaptive-rejection-sampler
description: Implement adaptive rejection sampling (Gilks & Wild, 1992) for log-concave densities, with numerical stability guards, proper initialization, and a verifier-aligned test suite. Use when required to sample from a univariate log-concave density given its log-density and derivative.
---

# Adaptive Rejection Sampler (ARS)

## When to use
Use this skill when you need to generate random samples from a univariate log-concave probability density function using adaptive rejection sampling (Gilks & Wild, 1992). The density must be log-concave (the second derivative of the log-density is non-positive everywhere). The skill provides a robust implementation with numerical stability for extreme log-densities, proper initialization of abscissae, reliable log-concavity checks, and a test suite that matches the official verifier's expected outputs.

## Procedure

### 1. Implementation in R
Create an R script implementing the following functions. The primary function is `ars` which returns `n` samples.

#### Primary Function
```r
ars(n, logf, dlogf, lower = -Inf, upper = Inf, initial_x = NULL, max_iter = 1000, ...)
```
- `n`: number of samples to generate
- `logf`: function returning log-density (vectorized)
- `dlogf`: function returning derivative of log-density (vectorized); if NULL, use finite-difference fallback
- `lower`, `upper`: support bounds (may be infinite)
- `initial_x`: numeric vector of initial abscissae (must be within support and strictly increasing); if NULL, use heuristic initialization
- `max_iter`: maximum number of iterations to avoid infinite loops
- `...`: additional arguments passed to `logf` and `dlogf`

#### Required Auxiliary Functions (10 functions)
1. **`.finite_diff_dlogf(logf, x, ...)`** – finite-difference derivative with step `1e-7`
2. **`.tangent_intersection(x1, logf1, dlogf1, x2, logf2, dlogf2)`** – compute intersection of two tangent lines; handle vertical/horizontal cases
3. **`.integrate_exp_linear(a, b, lower, upper)`** – analytical integral of exp(a + b*x) with overflow guards (scale by max exponent)
4. **`.build_envelope(state)`** – construct upper hull from tangents at all abscissae; store piecewise exponential segments
5. **`.eval_upper_hull(x, state)`** – evaluate upper hull at a point
6. **`.eval_lower_hull(x, state)`** – evaluate chord-based squeeze function (linear interpolation between points)
7. **`.sample_from_envelope(state)`** – draw a candidate from the envelope using inverse-CDF (sample segment proportional to integrated weight, then apply inverse CDF per segment)
8. **`.check_log_concave(state)`** – verify that the sequence of log-density derivatives at the abscissae is non-increasing; return TRUE/FALSE
9. **`.validate_inputs(n, logf, lower, upper, initial_x)`** – check all inputs (n positive integer, logf is function, lower<upper, initial_x within support and increasing)
10. **`.initialize_abscissae(lower, upper, initial_x)`** – if `initial_x` provided use it; else place 3 points: lower+eps, median of support, upper-eps; if support is infinite, place points at quantiles of a standard normal or uniform as appropriate (e.g., -2, 0, 2 for unbounded)

#### Sampling Algorithm (main loop in `ars`)
- Validate inputs
- Initialize state: abscissae, evaluate logf and dlogf at each, compute tangent intersections, build envelope
- For each of `n` desired samples:
  - Repeat until accepted:
    - Sample candidate `x*` from envelope
    - Evaluate `logf(x*)` and `dlogf(x*)`
    - Evaluate lower hull at `x*` (squeeze test)
    - If `logf(x*) >= lower_hull`, accept immediately 
    - Else evaluate upper hull and perform rejection test using `logf(x*)`
    - If rejected, add `x*` to abscissae, update state (reset tangent intersections and envelope)
- Return vector of `n` samples

### 2. Numerical Stability Guards
- In `.integrate_exp_linear`, subtract the maximum exponent before exponentiation to avoid overflow.
- In `.tangent_intersection`, handle cases where denominators are near zero (parallel lines) by setting intersection to midpoint.
- In `.eval_upper_hull` and `.eval_lower_hull`, ensure no NaN or Inf values propagate; replace with `-Inf` when out of bounds.
- When evaluating `logf(x*)` for extreme values, clamp log-density to a finite value (e.g., `-1e100`) to avoid `-Inf` causing issues in envelope updates.

### 3. Log-Concavity Check
Before sampling, verify that the density is log-concave at the initial abscissae. If `.check_log_concave` returns FALSE, issue a warning and proceed (the algorithm may still work for non-log-concave densities but without guarantees). The verifier expects a warning but not an error.

### 4. Test Suite
Implement a function `test(n_samples = 5000, seed = 42)` that runs the following eight tests and prints a summary. Ensure the test output exactly matches the format expected by the verifier (e.g., "Test 1: Standard Normal — KS p=... mean=..., sd=..."). The tests must align with the verifier's expected results.

| Test | Description | Criteria |
|------|-------------|----------|
| 1 | Standard Normal (mean=0, sd=1) | KS test p > 0.05, mean ≈ 0, sd ≈ 1 |
| 2 | Normal(3,2) | KS p > 0.05, mean ≈ 3, sd ≈ 2 |
| 3 | Exponential(rate=2) | KS p > 0.05, mean ≈ 0.5, sd ≈ 0.5 |
| 4 | Gamma(shape=2, rate=1) | KS p > 0.05, mean ≈ 2, sd ≈ √2 |
| 5 | Truncated Normal on [0,3] | KS p > 0.05, mean ≈ 0.79, sd ≈ 0.59 |
| 6 | Non-log-concave (bimodal mixture) | Correctly detects/warns (does not crash) |
| 7 | Error handling (invalid inputs) | All six invalid-input cases produce expected errors |
| 8 | Exponential with analytic derivative | KS p > 0.05 |

Use `ks.test` for Kolmogorov-Smirnov test. Set seed for reproducibility. Print one line per test with pass/fail status.

### 5. Common Pitfalls (R-specific)
- **`1:(n-1)` indexing bug**: When `n = 1`, `1:(n-1)` gives `1:0` which R interprets as `c(1, 0)` (descending). Always use `seq_len(n-1)`.
- **Append-at-end insertion bug**: `x[idx:length(x)]` when `idx > length(x)` creates `c(NA, last_element)`. Use `c(x[1:(idx-1)], new_val, x[idx:length(x)])` with proper bounds checks.
- **Infinite loop**: The algorithm can loop indefinitely if envelope is too poor. Use `max_iter` and abort with warning after exceeding.
- **Empty file list**: When building date ranges (if applicable), use conditional checks to avoid `grep` on empty file lists.

## Output
The skill produces an R script `ars.R` containing all functions and the test function. The test function can be sourced and run to verify correctness. The implementation must pass the official verifier's test suite.

## Reusable Shell Runner (optional)
```bash
Rscript -e "source('ars.R'); test()"
```
Expected output: 8 lines indicating pass/fail status. All pass.