---
name: stan-pystan-migration
description: Use when converting an RStan (rstan) script to PyStan, or porting any Bayesian model between Stan-based frameworks. Covers hyperparameter remapping, data-shape and indexing equivalences, jitter/seed handling, and equivalence verification against a known-good baseline. Triggers on phrases like "rstan to pystan", "convert rstan", "port Stan model to Python", or any Bayesian translation between R and Python.
---

# Stan-to-PyStan Conversion Guard Rails

When porting a Bayesian model from RStan to PyStan, the model is usually correct in shape but fails on hyperparameter naming, matrix vs array typing, seed/jitter semantics, or 1-based vs 0-based indexing. The pattern across failures is the same: the converted script *runs* and produces numbers, but those numbers diverge from the R baseline silently. Below is the procedure to follow before declaring the conversion done.

## Procedure

### 1. Map Stan code blocks line-by-line
- Copy the `model` block verbatim into the Python `stan_model` source string. Do not "modernize" syntax or rewrite vectorised statements.
- Copy the `functions` block identically if present — these are the highest-risk area for silent divergence (e.g., GP kernels, custom likelihoods).
- Copy the `data` declarations exactly. Pay attention to whether each variable is declared `matrix[...]` vs `array[...]` — these are NOT interchangeable in Stan and behave differently when slicing or indexing.
- Copy the `generated quantities` block identically if present.

### 2. Map the RStan control hyperparameter set
| RStan (R) | PyStan (Python) | Notes |
|-----------|-----------------|-------|
| `init_r = 2` | `init_radius = 2` | PyStan uses distance, not radius-count |
| `adapt_delta = 0.8` | `delta = 0.8` | Naming change |
| `max_treedepth = 10` | `max_depth = 10` | Naming change |
| `iter = 2000` | `iter = 2000` | Direct |
| `warmup = 1000` (RStan arg name) | `warmup` or `num_warmup` | Name varies by version — check |
| `chains = 4` | `chains = 4` | Direct |
| `seed = 42` | `seed = 42` | Direct — but verify the RNG path matches |
| `cores = 4` | `cores = 4` | Direct |

Skip any control parameter you cannot match — but log the omission; later sections will check whether the missing control caused posterior drift.

### 3. Translate data shape conventions
- R is 1-based; Python/NumPy is 0-based. Stan itself is 1-based inside the model — do not subtract 1 in the data passed to Stan.
- R matrices (`matrix()`) passed to RStan become NumPy arrays of shape `(rows, cols)`. Verify the shape with `np.array(...).shape` BEFORE passing.
- R vectors passed as R `numeric` of length `n` map to flat 1-D arrays — NOT column vectors. RStan reshapes these internally; PyStan will not.
- Factor/categorical columns become integer indices; do not pass R factor objects.

### 4. Match kernel-specific tweaks exactly
If the Stan `functions` block contains an ARD kernel, matern, or any custom covariance:
- Confirm the jitter term (often `1e-6`) is added to the diagonal in *exactly* the same order of operations as the R original.
- Confirm lengthscale and signal-variance priors match in both location and declared type.
- Confirm that any matrix multiply inside the kernel uses the same orientation (R `%*%` vs `@`); reversing the operands is a common silent error.

### 5. Run and verify against the R baseline
This is the step most often skipped, and it is the failure mode this skill exists to prevent.

After the PyStan script completes:
- Extract posterior means (or quantiles if means are unstable).
- Compare to the means from the original R script using the same seed and same data — within a tolerance appropriate for the model (e.g., 5–10% for means, larger for tail statistics).
- If they diverge: do NOT keep tweaking the PyStan code in isolation. Return to step 1 (Stan code blocks) and step 2 (hyperparameter map) before suspecting PyStan itself.

## Diagnostic checklist

Before declaring the conversion successful, run ALL of these:

1. **Stan source diff.** `diff` the `model`, `functions`, and `generated quantities` blocks of the original RStan script against the strings inside the new PyStan `stan_model` call. The only allowed diffs are whitespace and comment reformatting. Any structural diff is a bug.
2. **Data shape check.** Print the shape and dtype of every array passed to `data=`. Confirm `(N,)` for inputs the RStan call treated as vectors and `(N, D)` for inputs it treated as matrices. Mismatch here is the single most common silent failure.
3. **Hyperparameter diff.** For each `*_control(` argument in the R call, confirm the corresponding PyStan kwarg is present and mapped per the table above. Any unset default in PyStan should be verified against the R default (which is implementation-defined — check the RStan release notes).
4. **Seed and jitter.** Set `seed=` to the same value in both runs. Confirm the jitter term in the kernel is identical (look for `+ 1e-X` or similar on the diagonal).

## Stop signal

If, after running the diagnostic checklist, the posterior means still diverge from the R baseline by more than the agreed tolerance across **two** independent fixes (each fix targeting a *different* suspected cause), STOP. The next step is to dump both scripts side-by-side and walk every variable end-to-end — not to keep mutating the PyStan code. Repeated failed mutations are the marker that the model interpretation is wrong, not the syntax.

When the diagnostic checklist passes AND the posterior means match within tolerance: ship the conversion.