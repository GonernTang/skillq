---
name: bayesian-network-modeling
description: Recover a Bayesian network DAG from data, fit it, perform causal interventions with do(), and sample from the intervened model. Use when the task involves structure learning, pgmpy, BayesianNetwork fitting, do-operations, or causal inference on continuous/discrete data.
---

# Bayesian Network Modeling with pgmpy

## When to use
Tasks that require: recovering a DAG from tabular data, fitting a Bayesian network, performing causal interventions (`do()`), and sampling from the intervened model.

## Procedure

1. **Load and inspect data**
   - Read the dataset (CSV/tabular).
   - Check columns and dtypes. Identify continuous vs discrete variables.

2. **Install pgmpy if missing**
   ```bash
   pip install pgmpy
   ```

3. **Structure learning**
   - Use `pgmpy.estimators.HillClimbSearch` with `BicScore` (or `K2Score` / `BDeuScore` for discrete).
   - Apply **edge constraints** when domain knowledge is available:
     - `edge_blacklist=[(parent, child)]` or `fixed_edges`
     - Enforce root nodes via blacklist (no incoming edges).
     - Optionally cap the number of edges via `max_indegree` or scoring thresholds.
   - Run `.estimate()` to obtain the DAG.
   - **Direction rule for undirected/score-tied edges:** when the search returns an undirected edge or ambiguity, orient by alphabetical rule — the node later in the alphabet is the parent.

4. **Fit the Bayesian network**
   - Instantiate `BayesianNetwork(learned_edges)`.
   - For **continuous data**, use `MaximumLikelihoodEstimator` (linear Gaussian).
   - For **discrete data**, use `BayesianEstimator` (BDeu/K2 prior) or `MaximumLikelihoodEstimator`.
   - Call `.fit(data)`.

5. **Causal intervention**
   - Use `pgmpy.inference` `do()` operator on the fitted model (or manually drop incoming edges to the intervened node, replace its CPD with a delta at the target value).
   - Set the intervened variable to the target value (exact constant or near-zero variance).

6. **Save intervened DAG edges**
   - Capture the post-intervention edge set (often identical to the learned DAG since `do()` severs only incoming edges to the intervened node).

7. **Sample from the intervened model**
   - Use the model's `.sample(n=...)` method.
   - Verify output column names match the original data schema.

## Common pitfalls
- Forgetting `edge_blacklist` lets the search add forbidden parents (e.g., a true root node gaining spurious parents).
- For continuous data, `BayesianEstimator` is wrong — use `MaximumLikelihoodEstimator` with linear-Gaussian CPDs.
- After `do(X=x)`, X's outgoing edges remain; only incoming edges are cut.
- Sampled column names must match training columns exactly.

## Minimal skeleton
```python
from pgmpy.estimators import HillClimbSearch, BicScore
from pgmpy.models import BayesianNetwork
from pgmpy.estimators import MaximumLikelihoodEstimator

hc = HillClimbSearch(data)
dag = hc.estimate(
    scoring_method=BicScore(data),
    black_list=forbidden_edges,
    white_list=required_edges,  # optional
    max_indegree=k,             # optional cap
)

# orient undirected edges alphabetically (later → parent)
oriented = [(p, c) if p < c else (c, p) for (p, c) in dag.edges()]

model = BayesianNetwork(oriented)
model.fit(data, estimator=MaximumLikelihoodEstimator)  # continuous
# model.fit(data, estimator=BayesianEstimator, prior_type='BDeu', equivalent_sample_size=5)  # discrete

intervened = model.do(variables=[X], interventions={X: value})
samples = intervened.sample(n=N)
```