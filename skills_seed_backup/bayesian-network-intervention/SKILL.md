---
name: bayesian-network-intervention
description: Use when a task asks to learn a Bayesian network (BN) structure from continuous (or mixed) data, fit its CPDs, perform a hard causal intervention do(Y = value), and sample from the post-intervention distribution. Covers pgmpy structure learning (HillClimbSearch, PC), domain-constraint enforcement, parameter estimation, and do-intervention sampling. Triggers on phrases like "Bayesian network", "causal intervention", "do-operator", "intervene on", "BN structure learning", "pgmpy", "DAG learning".
metadata:
  type: procedure
---

# Bayesian Network Structure Learning + Causal Intervention

When a task requires learning a BN from data and then applying a `do()`-intervention, do NOT stop after installing pgmpy. The full pipeline has four mandatory stages; skipping any one yields an invalid result.

## Procedure

### 1. Learn the DAG from data
- **Continuous data**: use `pgmpy.estimators.HillClimbSearch` with a Gaussian BIC score (`K2Score` is for discrete only), OR `PC` with a continuous CI test (e.g., partial correlation).
- **Discrete data**: `HillClimbSearch` with BDeu or BIC.
- Pass domain constraints explicitly: `fixed_edges`, `tabu_edges`, `fixed_nodes` (root/leaf status), or a `start_dag` seeded with the required structure.
- After learning, print the DAG and verify edge count, acyclicity, and every stated constraint before moving on.

### 2. Fit the parameters
- Use `MaximumLikelihoodEstimator(model, data).get_parameters()` (or `BayesianEstimator` for small samples).
- Call `model.check_model()` — if it raises, the CPDs are inconsistent with the DAG.
- The result is a `BayesianNetwork` with fitted CPDs for every node.

### 3. Perform the hard intervention `do(Y = v)`
- In pgmpy: `intervened = model.do(intervention={(Y, v)})`.
- This removes all incoming edges to Y and replaces Y's CPD with a delta at `v`.
- For a hard intervention the variance is effectively zero; if the sampler needs a non-zero variance, use `1e-6` — do not omit the variance and do not use a wide distribution (that is a soft intervention, not `do()`).

### 4. Sample from the intervened model
- `samples = intervened.sample(n_samples=N, show_progress=False)`
- Verify: (a) Y's column equals `v` (within tolerance) for every row, (b) other columns vary according to the truncated DAG.
- Save to CSV with columns matching the original variable names, in the order the task specifies.

## Diagnostic checklist (run BEFORE scaling up)

1. **Constraint satisfaction** — print the learned DAG and confirm every domain rule holds (e.g., "U has no parents", "exactly K edges", "alphabetical directionality rule", "X is a root"). If violated, the search is ignoring constraints — re-run with `fixed_edges`/`tabu_edges` or a seeded `start_dag`.
2. **Acyclicity + CPD consistency** — call `model.check_model()`. Cycles or NaN CPDs mean the structure learner produced an invalid DAG; do not proceed.
3. **Intervention actually applied** — after `do()`, inspect Y's incoming edges in `intervened` (should be zero) and Y's fitted CPD (should be a delta at `v`). If either is wrong, the `do()` call was not effective.
4. **Sample sanity** — for a small `N` (e.g., 100), confirm Y is constant at `v` and the other variables follow the truncated dependency graph; do not scale to the full `N` until this passes.

## Stop signal

If the learned DAG violates a stated constraint on 2 consecutive attempts with the same search algorithm, **switch architecture** — do not iterate on flag tweaks:
- Seed the search with `start_dag=constraint_satisfying_dag` and let HillClimb refine only the unconstrained edges.
- Or enumerate candidate DAGs and filter by constraints before scoring.

If the post-intervention sample shows Y varying (not pinned to `v`), the `do()` call failed — verify the intervention dict format and that `model.do()` was actually called (not just defined). If 2 attempts both show Y varying, abandon the soft-intervention fallback and force the intervention by manually removing incoming edges and replacing Y's CPD.