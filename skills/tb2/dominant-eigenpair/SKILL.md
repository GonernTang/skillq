---
name: dominant-eigenpair
description: Compute the dominant eigenvalue and corresponding eigenvector of small real matrices (≤10×10). Use a hybrid approach: analytical solution for 2×2, LAPACK bindings for 3×3–10×10, fallback to numpy. Handles complex eigenpairs and numerical stability.
---

# Dominant Eigenpair of Small Real Matrices

When asked to compute the dominant (largest-magnitude) eigenvalue and its eigenvector of a small real matrix (≤10×10), follow this hybrid procedure.

## Inputs

- A real square matrix `A` as a NumPy `ndarray` (float64).

## Output

- A complex eigenvalue `λ` (Python complex) of largest magnitude.
- A complex eigenvector `v` (NumPy `complex128` array) satisfying `A v ≈ λ v` up to numerical tolerance.

## Procedure

### 1. 2×2 analytical path

Solve the characteristic polynomial directly:

```
λ² − tr(A)·λ + det(A) = 0
```

Using `cmath.sqrt`:

```python
import cmath, numpy as np

def _eig_2x2(A):
    tr = A[0, 0] + A[1, 1]
    det = A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0]
    disc = tr * tr - 4.0 * det
    s = cmath.sqrt(disc)
    l1 = 0.5 * (tr + s)
    l2 = 0.5 * (tr - s)
    # pick the one with larger magnitude
    lam = l1 if abs(l1) >= abs(l2) else l2
    # eigenvector: nullspace of (A - lam*I); pick the more numerically stable row
    M = A - lam * np.eye(2)
    if abs(M[1, 1]) >= abs(M[0, 0]):
        v = np.array([M[1, 1], -M[1, 0]], dtype=np.complex128)
    else:
        v = np.array([-M[0, 1], M[0, 0]], dtype=np.complex128)
    return lam, v
```

Picking the row with larger pivot magnitude avoids division blow-up when `M` is near-singular.

### 2. 3×3 to 10×10 LAPACK path

Use the low-level LAPACK routine `dgeev` via `scipy.linalg.lapack.dgeev`:

```python
from scipy.linalg.lapack import dgeev

def _eig_lapack(A):
    # jobvl=0 → skip left eigenvectors (faster)
    wr, wi, vl, vr, info = dgeev(A.astype(np.float64), jobvl=0, jobvr=1)
    # wr, wi are real/imag parts; vr packs each complex eigenvector in adjacent columns
    mags = np.hypot(wr, wi)
    idx = int(np.argmax(mags))
    lam = complex(wr[idx], wi[idx])
    if wi[idx] == 0.0:
        v = vr[:, idx].astype(np.complex128)
    else:
        # complex conjugate pair: reconstruct full complex eigenvector
        v = vr[:, idx].astype(np.complex128) + 1j * vr[:, idx + 1].astype(np.float64)
        # normalize: LAPACK scales such that ||v||_∞ = 1
        peak = np.max(np.abs(v))
        if peak > 0:
            v = v / peak
    return lam, v
```

Key points:
- `np.hypot` (vs `abs`) is robust when both real and imag parts are large.
- LAPACK packs a complex eigenvector across two adjacent columns of `vr`; column `idx` is the real part, column `idx+1` is the imaginary part (for the eigenvalue at index `idx`).
- Always return `complex128` for `v` so the downstream caller can handle complex eigenpairs uniformly.

### 3. Fallback

If SciPy is unavailable, use `numpy.linalg.eig`:

```python
vals, vecs = np.linalg.eig(A)
mags = np.abs(vals)
idx = int(np.argmax(mags))
return complex(vals[idx]), vecs[:, idx].astype(np.complex128)
```

## Dispatch

```python
def dominant_eigenpair(A):
    A = np.asarray(A, dtype=np.float64)
    n = A.shape[0]
    if n == 2:
        return _eig_2x2(A)
    if 3 <= n <= 10:
        try:
            return _eig_lapack(A)
        except Exception:
            pass
    vals, vecs = np.linalg.eig(A)
    idx = int(np.argmax(np.abs(vals)))
    return complex(vals[idx]), vecs[:, idx].astype(np.complex128)
```

## Numerical-stability checklist

- Return `complex128` eigenvectors even for real eigenvalues — downstream code that does complex arithmetic will not break.
- Use `np.hypot(real, imag)` instead of `abs(complex)` for magnitude comparison — avoids overflow on large components.
- Normalize complex eigenvectors reconstructed from LAPACK's packed storage by dividing by the infinity-norm peak so `‖v‖_∞ = 1`.
- For 2×2, when picking the eigenvector row, choose the row whose diagonal entry of `A − λI` has larger magnitude — avoids dividing by a near-zero pivot.

## Common pitfalls

- LAPACK's `vr` layout: a complex eigenvector lives in `vr[:, idx] + 1j * vr[:, idx+1]`; forgetting the imaginary part silently produces a wrong (real) answer.
- When the dominant eigenvalue is complex, `wi[idx] != 0`; do not index column `idx` alone.
- For matrices with very close dominant eigenvalues (e.g., repeated spectrum), `np.argmax(np.abs(...))` may tie-break unexpectedly — if precision matters, use a tolerance-aware selector.