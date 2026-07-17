---
name: bayesian-network-intervention
description: Recover a Bayesian network DAG from continuous data, fit parameters, and perform causal interventions by modifying the graph and sampling from the intervened model.
---

# Bayesian Network Recovery, Fitting, and Intervention

This skill covers the end-to-end workflow for (1) learning a directed acyclic graph (DAG) from continuous observational data, (2) fitting conditional probability distributions, and (3) performing `do()`-style interventions by editing the graph and forward-sampling.

## When to Use

Use this skill when you need to:
- Discover causal structure from a continuous-valued dataset.
- Combine score-based and constraint-based learning with prior knowledge.
- Fit a Bayesian network and run an intervention (e.g., `do(X = x)`).

Do **not** use for purely discrete data (use the categorical equivalents of the estimators/scores) or for purely predictive modeling without a causal graph.

## Procedure

### 1. Load and Inspect Data

- Load the dataset into a pandas DataFrame.
- Verify all variables of interest are continuous (`df.dtypes`, `df.select_dtypes`).
- Check for missing values and decide on an imputation strategy (the Bayesian estimator handles it; document the choice).
- Compute summary statistics to catch obvious scale issues — standard score-based Gaussian learners assume the variables are real-valued.

### 2. Learn Skeleton with a Score-Based Search

- Use `pgmpy.estimators.HillClimbSearch` with `K2Score` (categorical) or `BICGauss` / `BICScore` (continuous Gaussian) as the scoring method.
- Start from an empty or domain-informed DAG.
- Encode prior knowledge as `black_list` / `white_list` edges or as forbidden-parent constraints via the `fixed_edges` / `expert_knowledge` argument where supported.
- Run the search with a tabu list size sufficient for the graph size (start with `tabu_length=100`; scale up if the search plateaus on the same graph).
- Repeat with several random restarts and keep the highest-scoring model to mitigate local optima.

### 3. Validate Skeleton with a Constraint-Based Check

- Run the `PC` algorithm (`from pgmpy.estimators.PC` on continuous data, `independence_estimator=partial_correlation`).
- Compute the skeleton and inspect conditional independencies — they should agree with the score-based skeleton where overlap exists.
- For edges the PC algorithm leaves undirected (typical when v-structures are absent), apply a heuristic orientation rule (alphabetical order, e.g., `from pgmpy.base.DAG.PDAG` and the `meek` rules, or simply enforce `node_1 < node_2 → node_1 → node_2`).
- Resolve conflicts between the two learners in favor of edges supported by conditional independence tests at the agreed significance level.

### 4. Fit Parameters

- Instantiate the chosen DAG.
- Fit with `BayesianEstimator` (BDeu prior for discrete; naturally handles Gaussian via mean-variance updates).
- Alternative: `MaximumLikelihoodEstimator` for point estimates; `ExpectationMaximization` when latent/missing variables are present.
- Inspect CPDs of root nodes (should reflect marginals) and a handful of children to confirm the parameters are sensible.

### 5. Perform an Intervention

An intervention `do(X = x)` severs all incoming edges to `X` and fixes its value to `x`.

- Copy the fitted model: `intervened = model.copy()`.
- Get the DAG: `dag = intervened.get_cpds_node()` or `intervened.dag.copy()`.
- For each parent `P` of `X`, remove the edge `P → X`:
  - `dag.remove_edge(P, X)` (or `dag.remove_edges_from([(P, X)])`).
- Replace the CPD of `X` with a deterministic constant distribution equal to `x` (a tabular CPD with a single state for `x`, weights 1.0).
- Re-fit / re-state the intervened CPD for `X` with the modified DAG using `BayesianEstimator` or by manually constructing the constant CPD (`TabularCPD(variable=X, variable_card=1, values=[[1.0]], ...)`, or its Gaussian equivalent with `mean=x, std=0`).
- Sanity-check: the intervened CPD should not depend on any other variable.

### 6. Forward-Sample from the Intervened Model

- Use forward sampling: `from pgmpy.sampling import BayesianModelSampling` (or `BayesianNetwork.forward_inference`).
- Call `inference = BayesianModelSampling(intervened); samples = inference.forward_sample(size=n, evidence={X: x}, show_progress=False)` — passing `evidence={X: x}` is functionally equivalent to the intervention for forward sampling.
- Verify invariants on the sample:
  - All values of `X` equal `x` (modulo floating-point noise for continuous `X`).
  - Descendants of `X` reflect the change in distribution (compare against a baseline sample without the intervention).
  - Non-descendants of `X` have unchanged marginals (a quick sanity check that no unintended edges were altered).

### 7. Report Results

- Show the original DAG (edges, parents of each node).
- Show the intervened DAG (parents removed from the target).
- Show first few rows of the sample, plus the invariant checks above.
- Note any modeling assumptions: Gaussianity, prior strength for the Bayesian estimator, search hyperparameters, and how undirected edges were oriented.

## Common Pitfalls

- **Continuous-only assumption**: `BICGauss` and partial-correlation tests assume continuous data; mixing types breaks them silently.
- **Local optima in `HillClimbSearch`**: a single run from the empty graph can be far from the global optimum; always restart.
- **Forbidden edges**: forgetting to express "this node has no parents" via the blacklist instead of just structural constraints causes the search to rediscover the same wrong edge.
- **Intervention direction**: removing edges is the do-operator; using `evidence=` in forward sampling is a conditioning (`observe`), not an intervention. Both are valid operations but answer different causal questions.
- **Floating-point determinism**: for continuous interventions, check `np.isclose` rather than `==` to allow noise tolerance.

## Minimal Libraries

- `pgmpy` (≥0.1.19 for PDAG-friendly PC and `BayesianModelSampling`).
- `pandas`, `numpy`.
- Optionally `networkx` for custom DAG manipulation outside pgmpy's API.