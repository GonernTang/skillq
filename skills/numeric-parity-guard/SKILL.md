---
name: numeric-parity-guard
description: Guard-rail for porting numerical/linear-algebra code (C extensions, SIMD, GPU kernels) that must exactly reproduce a pure-language baseline. Use before committing to an optimized implementation to avoid silent precision, layout, or ordering mismatches.
---

# Numeric Parity Guard

When you rewrite a numerical routine (matrix products, quadratic forms,
reductions) in a faster backend that must **match an existing baseline**,
tiny differences in ordering, dtype, or memory layout produce answers that
look "close" but fail exact comparison. Establish parity *before* optimizing.

## Diagnostic checklist (run BEFORE committing to the fast path)

Answer each with evidence, not assumption:

1. **Dtype & accumulation.** Does the fast code accumulate in the *same*
   precision as the baseline (e.g. `double`/`float64`), not a narrower
   intermediate? Confirm every temporary's type.
2. **Operation order & layout.** Is the multiplication/reduction order
   identical, and are inputs forced to **contiguous** arrays in the layout
   the kernel expects (row- vs column-major)? Add explicit conversion in
   the wrapper rather than trusting the caller.
3. **Decompose composite ops.** For expressions like a quadratic form,
   compute in the *same sub-steps* as the baseline (e.g. `t = S·x` then
   `sqrt(x·t)`), not a fused rearrangement that changes rounding.
4. **Small-input equivalence.** On small random inputs, do outputs match
   the baseline element-by-element within a defined tolerance (ideally
   bit-exact for integer/ordered ops)? Run this before any large run.

## Stop signal

If element-wise comparison on small random inputs fails **twice** in a row,
STOP tuning the fast path. Reset: revert to calling the baseline, then
re-derive the fast version one operation at a time, diffing against the
baseline after each step until parity holds. Only after parity is proven do
you enable optimization flags (e.g. `-O3`) and re-run the benchmark to
confirm both correctness *and* the expected speedup.