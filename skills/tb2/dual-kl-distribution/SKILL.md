---
name: dual-kl-distribution
description: Construct a probability distribution over a large vocabulary N that satisfies both forward and backward KL divergence constraints (KL(P||U) = KL(U||P) = D) for a target D. Use a multi-group model and a nonlinear solver.
---

# Constructing a Distribution Satisfying Dual KL Constraints

When the task is: "find a probability distribution P over a vocabulary of size N such that both `KL(P || U) = D` and `KL(U || P) = D`" (where U is uniform, so `U[i] = 1/N`), use the multi-group construction below.

## When to use this skill

- The user gives a vocabulary size N (e.g. `N = 10^6`) and a target KL value D.
- Both forward and backward KL divergences between P and the uniform distribution must equal D simultaneously.
- An exact solution is required (within numerical tolerance), not just an approximate sketch.

## Procedure

1. **Choose a multi-group model.** A single uniform bump cannot match both KLs; use **at least three groups** of tokens with different probabilities. A common layout: `hot` (highest probability), `medium` (intermediate), `cold` (lowest, close to uniform).

2. **Set the cold group analytically from the backward-KL constraint.** With `K_L` cold tokens at probability `p_cold`, the cold group's contribution to `KL(U || P) = sum_i U_i * log(U_i / P_i)` is approximately
   `K_L * (1/N) * log((1/N) / p_cold) = D` (when cold dominates the sum). So
   `p_cold = exp(-D * N / K_L) / N`. If `K_L ≈ N` (i.e. most tokens are cold), this simplifies to
   `p_cold = exp(-D) / N`.

3. **Solve the remaining equations numerically.** Treat `(K_H, K_M, p_H, p_M)` (or whatever free parameters are left after step 2) as unknowns, with the constraints:
   - `K_H + K_M + K_L = N` (group sizes sum to vocabulary)
   - `K_H * p_H + K_M * p_M + K_L * p_cold = 1` (probabilities sum to 1)
   - `K_H * (1/N) * log(p_H / (1/N)) + K_M * (1/N) * log(p_M / (1/N)) + K_L * (1/N) * log(p_cold / (1/N)) = D` (forward KL)
   - The backward-KL constraint is already satisfied by step 2 (check as a residual).

   Solve with a nonlinear solver (e.g. `scipy.optimize.fsolve`) starting from a reasonable initial guess (e.g. `p_H ≈ 1`, `K_H ≈ 1` for a dominant hot token, `p_M` near `1/N`).

4. **Discretize to integer token counts.** Round the continuous group sizes to integers. To preserve the sum constraint exactly, adjust one group's probability (not its count) so that `K_H * p_H + K_M * p_M + K_L * p_cold = 1` holds. Re-check both KLs after rounding — small adjustments to one probability usually bring both back within tolerance.

5. **Verify.** After construction, compute:
   - `sum(P) = 1`
   - `KL(P || U) ≈ D` (within tolerance, e.g. `1e-6`)
   - `KL(U || P) ≈ D` (within tolerance)
   - `min(P) > 0` (all probabilities strictly positive)

   If either KL is off, perturb the free group (typically the medium group) and re-verify.

## Implementation tips

- Work in log-space when computing KLs to avoid underflow: `KL(P||U) = sum(P * (log P + log N))` and `KL(U||P) = log N - sum(P * log P)` for uniform U. These are numerically stable.
- The solver may need bounded initial guesses because the equations are highly nonlinear near the boundary where `p_H → 1`.
- For very large D, `p_cold` can become sub-normal; verify it is still positive in floating point.
- For very small D, the cold group probability approaches `1/N` and the construction degenerates; flag this if the resulting hot/medium groups become indistinguishable from cold.

## Key formulas

- `U[i] = 1 / N`
- `KL(P || U) = sum_i P_i * log(P_i * N)`
- `KL(U || P) = log(N) - sum_i P_i * log(P_i)`
- Cold-group probability: `p_cold = exp(-D * N / K_L) / N` (or `exp(-D) / N` if `K_L ≈ N`)