---
name: ars-gilks-wild
description: Implement the Adaptive Rejection Sampling (ARS) algorithm of Gilks & Wild (1992) in R. Use this skill when the task asks for sampling from a univariate log-concave density via ARS, when writing R scripts that contain backslashes or other JSON-escape-prone characters, or when a sampler must support both pointwise and derivative evaluation of the log-density with a piece-wise exponential squeeze/envelope.
---

# ARS (Gilks & Wild, 1992) in R

## When to use this skill

- The task requires sampling from a univariate density `f(x)` known only up to a normalising constant.
- You can supply `h(x) = log f(x)` and `h'(x)` (the derivative of the log density).
- The density is unimodal and `h` is **concave** on the support (log-concavity).

If `h` is NOT concave, do not use vanilla ARS — fall back to a Metropolis-Hastings scheme and warn the user.

## Diagnostic checklist (run BEFORE writing the sampler)

1. **Concavity probe** — evaluate `h''(x)` at a grid of `x` values spanning the support. If `h''(x) < 0` everywhere, proceed; otherwise reject or restructure.
2. **Boundary sanity** — confirm `h(x)` is finite at the proposed abscissae `T_k` (no `NaN`/`-Inf` from log of zero or negative density). If not, tighten the support or pick different starting points.
3. **Reproducible test** — seed the RNG (`set.seed(42)`) and verify a short run (`n = 1000`) returns the correct shape by comparing with `integrate()` or a histogram against the known pdf.
4. **File-write smoke test** — after writing the .R file, verify with `file.info(file)$size > 0` and `readLines(file, n = 5)` that backslashes and escapes survived intact (R regex strings like `"\\("`, `"\\s+"` are notorious for JSON corruption).

## Implementation guard rails

### Modular layout
Split into clearly-named functions rather than one monolith:
- `init_abscissae(h, hprime, support, n_start = 3)` — pick starting `T_k` values.
- `update_envelope(T, h, hprime)` — build the piecewise-linear `z_k` and piecewise-exponential `u_k` / `l_k` (squeeze & hull).
- `sample_one(z, u, l)` — draw one proposal via squeeze-then-accept; returns either accepted `x`, rejected `x`, or a "squeeze-fail" indicator that triggers an abscissa insertion.
- `ars(n, h, hprime, support, n_start)` — main loop, calling the above.

### File-writing technique (critical)
The single most common failure mode when generating large R scripts via tool calls is JSON-escape corruption of backslashes. R strings like `"\\("`, `"\\1"`, regex `"\\s+"`, Windows paths `"C:\\foo\\bar"`, or LaTeX escapes all contain backslashes that get mangled when passed as raw `content`.

**Preferred ordering:**
1. **First choice — heredoc via Bash**: `cat > file.R <<'EOF' ... EOF` (note the *quoted* delimiter `'EOF'` disables shell expansion so backslashes pass through verbatim).
2. **Second choice — base64 round-trip**: `base64 -d > file.R` of a pre-encoded payload.
3. **Last resort — Write tool**: use it only for short, backslash-free R. After writing, immediately run `readLines(file, n = 20)` to verify, and re-issue if any line shows a stray newline or truncation.

### Validation & statistical tests
- Always run `set.seed(<fixed>)` so the test suite is reproducible.
- After sampling, compare empirical CDF against the analytic CDF with `ks.test()` (Kolmogorov-Smirnov). Reject implementations whose p-value falls below `0.01` on a few thousand draws from a known shape (e.g. `N(0,1)`, `Exp(1)`, `Beta(2,5)`).
- Cross-check the **acceptance rate** (ratio of accepted to total proposals). For well-tuned ARS on a log-concave target, this is typically > 50 % and almost always > 20 %. Persistent low acceptance means the abscissa set is too sparse or `h` isn't actually concave.

### Log-concavity check
Before the sampling loop ever runs, verify `h''(x) < 0` for `x` in the support. A common debug trick: plot `hprime` over a grid — it must be strictly decreasing.

## Stop signal

- If the KS test fails **three times in a row** with different seeds and the acceptance rate stays below 20 %, do NOT keep tweaking the envelope math. Stop, re-check the log-concavity assumption, and verify `h` / `hprime` are being called with the correct argument (vectorised over `x`, returning the same length vector).
- If you have rewritten the same `sample_one` or `update_envelope` function three times and the diagnostic still fails, **abandon the current architecture**: switch from a piecewise-exponential envelope to a piecewise-linear-on-log-scale formulation, or replace the sampler with a simple accept-reject against a coarse global envelope.

## Quick reference: the algorithm

```
1. Start with T = {t_1 < ... < t_k} (k >= 3), abscissae in support.
2. Compute h(T) and h'(T).
3. Build z_k = intersection of tangents at consecutive t's (hull knots).
4. Build u_k = piecewise-linear exp(h) over [t_k, t_{k+1}]   (upper hull).
5. Build l_k = piecewise-exponential lower bound (squeeze) from secants.
6. Repeat until n samples collected:
   a. Draw X from s(x) ∝ u_k(x) on each interval (piecewise exponential).
   b. Draw W ~ Uniform(0,1).
   c. If W <= l_k(X) / u_k(X): accept X (squeeze test).
   d. Else if W <= h(X) / u_k(X): accept X (hull test).
   e. Else: insert X as a new abscissa, rebuild envelope, continue.
```

## Reference test distributions

Always include at least one of these in the test suite — they are log-concave and have known closed-form h, h', and CDF:

| Distribution | `h(x)` | `h'(x)` | support |
|---|---|---|---|
| `N(mu, sigma^2)` | `-(x-mu)^2 / (2 sigma^2)` | `-(x-mu)/sigma^2` | `(-Inf, Inf)` |
| `Exp(lambda)` | `log(lambda) - lambda*x` | `-lambda` | `[0, Inf)` |
| `Beta(alpha, beta)`, both > 1 | `(a-1)log x + (b-1)log(1-x)` | `(a-1)/x - (b-1)/(1-x)` | `(0, 1)` |
| truncated `N(0,1)` on `[a,b]` | same as N | same | `[a, b]` |

A correct implementation passes `ks.test` against the analytic CDF with `p.value > 0.05` for all four.