---
name: stan-mcmc-pipeline
description: Hierarchical Bayesian MCMC sampling using Stan via R. Use when the user wants to fit a multilevel (partial-pooling) model with a Beta-Binomial or similar hierarchical structure, sample from its posterior, and report summary statistics of higher-level parameters.
---

# Stan Hierarchical MCMC Pipeline

This skill captures the end-to-end procedure for fitting a hierarchical Bayesian model in Stan (Beta-Binomial style), sampling from its posterior with `rstan`, and reporting the posterior means of the hyperparameters.

## When to use

Use this skill when the task asks to:
- Fit a hierarchical/multilevel model in Stan with R.
- Use a non-informative prior on concentration/scale parameters.
- Sample with multiple chains and a long iteration budget.
- Report posterior summaries (means) of the hyperparameters.

Typical signals: CSV with per-group successes/trials, partial pooling, Beta-Binomial, hierarchical Beta, Jeffreys-like prior on α and β.

## Procedure

### 1. Inspect the data

- Read the CSV (e.g. with R, pandas, `head -n`).
- Identify the columns: per-row `y` (successes) and `n` (trials). Record `N` = number of rows.
- Both `y` and `n` must be integer-typed in Stan's data block.

### 2. Write the Stan model

Typical hierarchical Beta-Binomial model. Adapt block names to your parameters.

```stan
data {
  int<lower=0> N;
  int<lower=0> y[N];
  int<lower=0> n[N];
}
parameters {
  real<lower=0> alpha;
  real<lower=0> beta;
  vector<lower=0, upper=1>[N] theta;
}
model {
  // Jeffreys-like prior on concentration: p(alpha,beta) ∝ 1/(alpha+beta)
  target += -2.5 * log(alpha + beta);
  theta ~ beta(alpha, beta);
  y ~ binomial(n, theta);
}
```

Key modeling conventions:
- Use `target +=` for the log prior on α, β (a `-2.5 * log(alpha + beta)` term implements the `(α+β)^(-5/2)` Jeffreys-like prior).
- Keep α, β as `real<lower=0>`.
- Keep θ as a vector with `<lower=0, upper=1>`.

### 3. Install rstan + system deps

Before installing the R package, ensure system C/C++ headers are present:
- `libcurl-dev`, `libssl-dev`, `libxml2-dev` (Ubuntu/Debian names).
- A working C++ compiler (g++ ≥7).
Then in R: `install.packages("rstan")`.

### 4. Write the R driver

Outline:

```r
library(rstan)
rstan_options(auto_write = TRUE)
options(mc.cores = parallel::detectCores())

# Load CSV; build y and n vectors
d <- read.csv("data.csv")
stan_data <- list(N = nrow(d), y = d$y, n = d$n)

# Compile + sample
mod <- stan_model("model.stan")
fit <- sampling(mod, data = stan_data,
                chains = 4, iter = 100000, seed = 1)

# Extract hyperparameters and write summaries
post <- rstan::extract(fit)
write(as.character(mean(post$alpha)), "alpha_mean.txt")
write(as.character(mean(post$beta)),  "beta_mean.txt")

# Convergence diagnostics
print(fit, pars = c("alpha", "beta"))   # check Rhat ~ 1, n_eff large
```

Knobs to tune if needed:
- `iter` (total iterations per chain incl. warmup). 100,000 is conservative.
- Default warmup is half of `iter`; expose explicitly if you need different ratios.
- Always set `seed` for reproducibility.
- Use `parallel::detectCores()` for `mc.cores`.

### 5. Verify

- Rhat for α and β should be ~1.0 (≤1.01).
- Effective sample sizes (n_eff) should be at least a few hundred.
- Trace plots should look like "fuzzy caterpillars."

### 6. Persist artifacts

Save the Stan source, the R driver, the input CSV, and the resulting `.txt` summary files in one folder so the run is fully reproducible.

## Common pitfalls

- Forgetting `auto_write = TRUE` makes repeated runs slow.
- Not parallelizing (`mc.cores`) wastes the 4-chain budget on wall-clock time.
- Storing α, β without `<lower=0>` causes divergent transitions.
- Reporting medians/HPDs without convergence checks — always print Rhat first.
- Treating `<lower=0, upper=1>` constraints on θ as optional; without them, samples can drift to {0,1} and stress the sampler.

## Deliverables checklist

- [ ] `model.stan` — Stan source with `data`, `parameters`, `model` blocks.
- [ ] `run.R` — loads data, compiles, samples, writes summaries.
- [ ] `alpha_mean.txt`, `beta_mean.txt` — posterior means.
- [ ] Convergence notes (Rhat, n_eff) printed.
- [ ] Input data CSV preserved alongside.