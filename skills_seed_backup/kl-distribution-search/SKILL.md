---
name: kl-distribution-search
description: Numerically synthesize a discrete probability distribution over an N-token vocabulary that satisfies both a target forward KL divergence and a target backward KL divergence from the uniform distribution. Use when you need to construct a distribution constrained by two KL targets simultaneously (e.g. generating reference distributions for language-model experiments, calibration tests, or divergence benchmarks).
---

# KL-Constrained Distribution Search

## When to use

Use this procedure when you must produce a discrete probability vector
`p` of size `N` such that:
- `KL(p || uniform) = target_forward_KL` (forward KL)
- `KL(uniform || p) = target_backward_KL` (backward KL, i.e. cross-entropy minus entropy of uniform)
- Both equalities hold within a stated tolerance.

## Procedure

### 1. Reduce to a two-valued family

Assume `p` takes only two distinct values:
- `m` tokens have probability `a / N`
- `N - m` tokens have probability `b / N`

with unknowns `(m, a, b)`. The simplification makes the constrained
system tractable and works well in practice because the two KL
divergences from uniform are dominated by the extremes of `p`.

### 2. Set up the three-equation system

Define residuals:

1. **Probability sums to 1:**
   `m*a + (N - m)*b - N = 0`
2. **Forward KL matches target:**
   `(m*a*log(a) + (N - m)*b*log(b)) / N - target_forward_KL = 0`
3. **Backward KL matches target:**
   `-(m*log(a) + (N - m)*log(b)) / N - target_backward_KL = 0`

(Use natural log; the `log` terms are inside sums so the `N` factors
cancel correctly. The `-1` term from uniform entropy is folded into
the right-hand side.)

### 3. Solve continuously with `scipy.optimize.fsolve`

```python
import numpy as np
from scipy.optimize import fsolve

def residuals(x, N, fwd, bwd):
    m, a, b = x
    r1 = m*a + (N - m)*b - N
    r2 = (m*a*np.log(a) + (N - m)*b*np.log(b)) / N - fwd
    r3 = -(m*np.log(a) + (N - m)*np.log(b)) / N - bwd
    return [r1, r2, r3]

m0, a0, b0 = 7.0, N / 7.0, np.exp(-target_backward_KL)
m, a, b = fsolve(residuals, [m0, a0, b0], args=(N, target_forward_KL, target_backward_KL))
```

Provide physically sensible initial guesses: a small `m0`, `a0` near
`N/m0`, and `b0` near `exp(-backward_KL)` (the typical size of the
small probability under cross-entropy pressure).

### 4. Snap `m` to an integer

`m` must be an integer. Rounding to the nearest int may violate the
KL tolerances. For each integer `m_int` in a small window around the
continuous `m` (e.g. `range(round(m) - 2, round(m) + 3)`):

1. Solve the remaining 2×2 system for `(a, b)` from equations 1 and 2
   (or 1 and 3).
2. Re-evaluate both KL divergences of the constructed distribution.
3. Accept the first `m_int` whose residuals fall within tolerance.

### 5. Build and validate the distribution

Construct the probability vector:

```python
p = np.full(N, b / N)
p[: int(m_int)] = a / N
```

Then independently recompute both KL divergences and confirm:

- `|KL(p || uniform) - target_forward_KL| <= tol`
- `|KL(uniform || p) - target_backward_KL| <= tol`

If no integer `m` satisfies the tolerance, widen the search window or
relax the initial guess before declaring failure.

### 6. Save the result

Persist `p` as a NumPy `.npy` (or whichever format the task expects).
Also store `m`, `a`, `b`, and the achieved KL values alongside it so
the solution is reproducible.

## Common pitfalls

- **`log(0)`** — clip or floor `a` and `b` away from zero before any
  log; the two-valued family is only valid when both values are
  strictly positive.
- **Wrong sign in backward KL** — backward KL from uniform is
  `-sum(log(p_i)) / N - log(N)`; double-check the constant.
- **Tolerance asymmetry** — the two KLs are differently sensitive to
  `a` vs `b`; if only one tolerance fails, perturb `b` (the tail mass)
  rather than `a`.
- **`fsolve` divergence** — if the solver wanders into negative `a`
  or `b`, re-run with tighter initial guesses or use `least_squares`
  with bounds.