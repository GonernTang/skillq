---
name: dominant-eigenvalue
description: Compute the dominant eigenvalue and eigenvector of a real square matrix efficiently in NumPy. Use when asked for the "largest eigenvalue", "principal eigenvalue", "dominant eigenvalue", or to accelerate a baseline numpy.linalg.eig call. Covers scipy.linalg.eig as a faster LAPACK path, a power-iteration fallback, Rayleigh-quotient refinement, complex-dtype handling, and the standard A v = λ v correctness check.
---

# Dominant Eigenvalue Procedure

Goal: produce `(eigenvalue, eigenvector)` for the largest-magnitude eigenpair of a real square matrix `A`, faster than the naive `numpy.linalg.eig` baseline.

## 1. Establish a fair baseline

- Build a representative real square matrix at the target size (e.g., `np.random.RandomState(0).randn(n, n)`).
- Time the baseline over many trials and report the **median**, not the mean — first-call overhead and GC jitter distort averages.
- `numpy.linalg.eig` is the reference for both speed comparison and correctness.

## 2. Look for an accelerated LAPACK path before reinventing

- If `scipy` is available, prefer `scipy.linalg.eig(A)` — its LAPACK bindings often have lower Python-side overhead than NumPy's and may include optimized divide-and-conquer drivers.
- If only NumPy is available, try `numpy.linalg.eigh` for symmetric matrices (much faster, uses symmetric solvers) before falling back to `eig`.

## 3. Power-iteration fallback (no scipy / not faster enough)

When the LAPACK path is unavailable or slower than needed, implement power iteration:

1. Initialize `v` to a random vector (or `np.ones(n)` for reproducibility).
2. Loop: `v = A @ v`; track the eigenvalue estimate as `λ = v_new · v_old` (vector inner product, not a norm) or as the Rayleigh quotient `λ = (vᵀ A v) / (vᵀ v)`; then `v = v / ||v||`.
3. Stop when `|λ_new - λ_old|` falls below a tolerance (e.g., `1e-10`) or after a hard iteration cap.
4. **Refine the eigenvalue after convergence** with the Rayleigh quotient `(vᵀ A v) / (vᵀ v)` — the running estimate during iteration is a rough proxy; the final quotient is quadratic in the error.

The iteration converges linearly at rate `|λ₂/λ₁|`. It will fail (return a non-dominant eigenpair) if `A` has multiple eigenvalues of equal largest magnitude — handle that edge case explicitly or document the limitation.

## 4. Return complex-capable outputs

Even for real input, the eigenvalue may be complex (rotation matrices, defective matrices). Always:

- Allocate the eigenvalue as a complex scalar/array and the eigenvector as a complex vector up front, OR cast at the end with `np.asarray(..., dtype=complex)`.
- This prevents silent dtype truncation when the caller expects complex.

## 5. Correctness check

Verify with the eigenpair equation at default tolerance:

```python
np.allclose(A @ eigenvec, eigenval * eigenvec)
```

This is the canonical check; a tight custom tolerance hides bugs that `allclose`'s relative+absolute defaults would catch.

## 6. Sign ambiguity

`eig` and power iteration may return `v` or `-v`; both are valid. Either fix a sign convention (e.g., require `v[0] > 0`) or document that callers should compare up to sign.

## Common pitfalls

- Using `numpy.linalg.eigh` on non-symmetric `A` silently returns wrong results — confirm symmetry first or stick with `eig`.
- Power iteration diverges or oscillates if the matrix has a dominant complex-conjugate pair; detect by checking that successive λ estimates are real and converging.
- Allocating the eigenvector as `float` when the true eigenvector is complex loses the imaginary part; the eigenpair equation then fails the `allclose` check.
- Comparing with a tolerance tighter than `np.allclose`'s default (e.g., `atol=0`) makes the check brittle on near-degenerate inputs.