---
name: adaptive-rejection-sampling
description: Guardrails for implementing Adaptive Rejection Sampling (ARS) algorithms. Use when building samplers that draw from univariate log-concave densities using piecewise-linear envelopes and squeeze tests. Prevents the common failure modes of skipping log-concavity validation, leaking log-density evaluation outside the support, and producing silently biased samples.
---

# Adaptive Rejection Sampling

When implementing an ARS algorithm, three failure modes silently corrupt every
sample the function returns. Run the diagnostic checks below before committing
to the standard "envelope → squeeze → reject → update" loop.

## Diagnostic checklist

Run all four checks **before** the first sample is drawn:

1. **Log-concavity invariant holds at initial abscissae.** Sort the initial
   points, evaluate `h'(x)` at each one, and verify the sequence is
   non-increasing. If not, abort — ARS provably fails on non-log-concave
   densities; no amount of envelope refinement will save it.
2. **Envelope support stays inside the density's domain.** When constructing
   each piece of the upper hull from tangents, clamp the piece's x-range to
   `[lower, upper]` (the user-supplied bounds). Evaluating `h(x)` or `exp(h(x))`
   outside the support is a silent NaN/Inf source and produces wrong samples
   that still pass naive KS tests on small `n`.
3. **Initial points are finite and inside the support.** Reject any initial
   abscissa that is `NA`, `NaN`, `±Inf`, or outside `[lower, upper]`. Truncate
   `±Inf` bounds to a large finite sentinel (e.g. `±1e300`) only when needed
   for numerical envelope construction; document the truncation.
4. **Derivative is available before the sampling loop starts.** If the caller
   did not supply `dlogf`, install a finite-difference fallback
   `(h(x+eps) - h(x-eps)) / (2*eps)` once, not per-sample. A per-iteration
   fallback doubles `h`-evaluations and skews the rejection-rate accounting.

## Sampling loop (the safe version)

For each candidate `x*`:

1. Draw `x*` from the piecewise-linear upper envelope via inverse-CDF
   (uniform `u` → linear piece by cumulative mass → solve for `x*`).
2. **Squeeze test first** (cheap): draw `v ~ U(0,1)`, accept if
   `log(v) <= h_lower(x*) - h_upper(x*)`. Never skip this step — it is the
   whole point of ARS.
3. On squeeze failure, evaluate `h(x*)` and `h'(x*)`, then do the **full
   rejection test**: accept if `log(v) <= h(x*) - h_upper(x*)`.
4. On rejection, insert `x*` into the sorted abscissa list, re-check the
   non-increasing-derivative invariant over the updated abscissae, and
   rebuild only the affected envelope pieces.

## Stop signal

If at any point the derivative sequence across abscissae is **not
non-increasing**, or any envelope piece evaluates to `NaN`/`Inf` at an
interior point, **abort immediately** with a structured error identifying
which invariant failed and at which abscissa. Do not return a partial sample
— the envelope is no longer a valid upper bound and downstream samples are
biased in a way KS tests cannot detect. Recovery requires rebuilding the
hull from new abscissae on a strictly log-concave density, not patching
the existing one.

## Test harness expectations

A battery run that doesn't include KS tests on at least three distinct
distribution families (e.g. truncated-normal, exponential, gamma with
shape>1) is insufficient. For each family: compare sample mean and sd to
analytic values within tolerance, run a two-sided KS test against the
target CDF at a fixed `n`, and print a structured pass/fail summary.
A single passing distribution proves nothing — ARS has known failure
modes that only show up on specific shapes.