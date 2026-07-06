---
name: rstan-hierarchical-mcmc
description: Step-by-step guide for running MCMC sampling with RStan on a hierarchical Bayesian model written in Stan — covering dependency setup, .stan model authoring (data/parameters/model blocks, priors via target +=), R driver script (data list, sampling with multiple chains and long iteration counts, extract(), colMeans()), and persisting posterior summaries as text files.
---

# RStan Hierarchical MCMC Sampling

## When to use
Fitting a hierarchical Bayesian model with NUTS/HMC via Stan from R, when you need multi-chain MCMC with many iterations and want posterior point estimates (means) of hyperparameters saved as plain text.

## Prerequisites — verify before coding
1. Working C++ toolchain (R 4.x on Linux/macOS/Windows: install `Rtools` / Xcode CLT / `r-base-dev`).
2. RStan installed from CRAN. RStan pulls in `StanHeaders`, `BH`, `RcppEigen`; install these explicitly to surface toolchain errors early:
   `install.packages(c("rstan", "StanHeaders", "BH", "RcppEigen"))`.
3. Makevars flags (only needed on some systems): set `CXX14 = -O2` and matching C++14 standard in `~/.R/Makevars` if you hit compilation errors.

## Author the .stan model
Structure the model file with three blocks:

- **data** — declare what R will pass. Use `int<lower=0>` for counts/sizes, `int y[N]` / `int n[N]` for group-level observations, `vector[N]` for predictors.
- **parameters** — top-level hyperparameters (`real alpha`, `real beta`) and group-level latent parameters (`vector[N] theta` or `real theta[N]`). Give sensible bounds for sampling stability (`real<lower=0> alpha;`).
- **model** — likelihood first, then priors. For each group: `y[i] ~ binomial(n[i], theta[i]);`. Hyperprior: `theta ~ beta(alpha, beta);`. Non-standard priors on hyperparameters use the log-density accumulator, e.g. `target += -2.5 * log(alpha + beta);` for a `(alpha+beta)^(-5/2)` prior.

## Write the R driver script
1. `library(rstan)`.
2. Build a named list matching the `data` block exactly (same names, same types).
3. Either compile once with `stan_model(file = "model.stan")` then call `sampling()`, or pass `file` directly into `sampling()` for one-shot runs (slower if you rerun, but simpler for a script).
4. Run `sampling()` with explicit reproducibility and enough warmup/samples to converge:
   - `chains = 4`
   - `iter = 100000` (includes warmup; sampler splits warmup/iter automatically when `warmup` not given, or set `warmup` explicitly)
   - `seed = 1`
5. Extract posterior: `posterior <- extract(fit)` (drop the warmup samples automatically).
6. Compute posterior means of hyperparameters: `colMeans(posterior$alpha)`, `colMeans(posterior$beta)` (colMeans works whether the parameter is a scalar or vector — for scalars it returns the single mean).
7. Write each scalar as a text file: `writeLines(as.character(mean_alpha), "alpha_mean.txt")` or `write(mean_alpha, file = "alpha_mean.txt")`.

## Checklist before declaring done
- Model compiles without warnings (`rstan` prints C++ compile log the first time).
- `sampling()` reports no divergent transitions; if it does, increase `adapt_delta` (e.g. `0.95`) and re-check `n_eff` / `Rhat`.
- All four chains converged (`Rhat` near 1, `n_eff` adequate).
- Each posterior-summary text file contains exactly one numeric value.
- Rerun end-to-end from a fresh R session — `seed = 1` must reproduce the same numbers.

## Common pitfalls
- Naming mismatch between the data list and the `.stan` `data { ... }` block — `rstan` will error with "variable not found in data".
- Forgetting `<lower=0>` on positive hyperparameters leads to unconstrained sampling and many divergences.
- Using `print()` inside the Stan `model` block slows sampling dramatically — only for debugging.
- `extract()` returns a *list* of arrays; access via `posterior$alpha`, `posterior$beta`, not by position.