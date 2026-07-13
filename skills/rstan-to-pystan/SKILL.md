```markdown
---
name: rstan-to-pystan
description: Convert an RStan script to an equivalent PyStan 3.10.0 script, or create Rust/C++ polyglot single-file executables (multi-language single-file pattern).
---

# Polyglot Rust/C++ Template (use when the task requires a Rust/C++ polyglot file)

To create a Rust/C++ polyglot single file that computes a mathematical function (e.g., Fibonacci):

1. Start the file with `// \` (line break after backslash). This line is a C++ comment that splices the next line.
2. On the next line, write `/*` – in C++ it's still part of the commented/spliced line; in Rust it starts a block comment.
3. Write all C++ code (includes, function definitions, main) inside the Rust block comment. End the block with `// This ends the Rust block comment: */`. The `//` in front of `*/` prevents C++ from seeing the `*/` and ending the comment prematurely.
4. After the `*/`, write Rust code. Each line of Rust must be preceded by `// \` so that C++ sees a line comment that splices and hides the following line.
5. Every Rust line – including opening/closing braces, else branches, etc. – must have the `// \` prefix, because C++ will otherwise interpret bare `}` or other syntax.
6. Test compilation with both compilers (`rustc` and `g++ -x c++`). If one fails, check that no Rust syntax leaks into the other language (especially braces, semicolons, or keywords). Add missing `// \` prefixes as needed.
7. The two languages share the same I/O (stdout) so ensure print statements produce the same format.

**Sanity-test procedure:** test at least N=0,1,2 and a larger value (e.g., N=20) with both compilers, and compare outputs byte-for-byte.

---

# Convert RStan → PyStan 3.10.0

Use this when porting a script that calls `rstan::stan()` into a Python script that calls `stan.build()` + `posterior.sample()` and writes posterior means to CSV.

## 1. Extract the model

The Stan model code typically lives inside an R string literal. Copy it verbatim into a Python triple-quoted string (use a raw `r"""..."""` style or any triple-quote). Do not modify `data {}`, `parameters {}`, or `model {}` blocks — Stan syntax is identical.

## 2. Load data

| R | Python |
|----|----|
| `read.csv("file.csv")` | `pandas.read_csv("file.csv")` |
| `fromJSON("file.json")` | `json.load(open("file.json"))` |
| `as.matrix(X)` | `X.to_numpy()` (or `np.asarray(X)`) |

Build the design matrix the way R's `cbind()` does:

```python
H = np.column_stack([np.ones(N), X[:, col0], X[:, col1]])
```

Pass everything to the model via a Python `dict` whose keys match the model's `data { ... }` declarations. Cast types explicitly where Stan expects `int` (`int(N)`).

## 3. Map sampling hyperparameters

RStan and PyStan use different names for the same NUTS controls. Translate the RStan call's arguments:

| RStan | PyStan 3 `stan.build` / `posterior.sample` |
|----|----|
| `iter = I` | `num_samples = I - W`, `num_warmup = W` (total iterations = samples + warmup) |
| `warmup = W` | `num_warmup = W` |
| `thin = T` | `num_thin = T` |
| `seed = S` | `random_seed = S` (in `stan.build`) |
| `init_r = R` | `init_radius = R` |
| `control = list(adapt_delta = AD)` | `delta = AD` |
| `control = list(max_treedepth = MT)` | `max_depth = MT` |
| `control = list(adapt_gamma = G)` | `gamma = G` |
| `control = list(adapt_kappa = K)` | `kappa = K` |
| `control = list(adapt_init_buffer = IB)` | `init_buffer = IB` |
| `control = list(adapt_term_buffer = TB)` | `term_buffer = TB` |
| `control = list(adapt_window = W)` | `window = W` |

Place `random_seed` in the `stan.build(stan_model=..., data=..., random_seed=...)` call. Place the rest as kwargs on `stan.build(..., **controls)` or, if using the `sample()`-level API, pass them there. Per-chain `init` lists or random `init` are not needed when `init_radius` is set.

## 4. Sample

```python
import stan
import numpy as np

model = stan.build(model_code, data=data, random_seed=seed, **controls)
fit = model.sample(num_samples=..., num_warmup=..., num_thin=...)
```

## 5. Extract posterior means and write CSVs

PyStan 3 returns a `posterior` object whose keys are the model parameters. Shape conventions:

- **Scalar parameter** `p` → `fit["p"]` has shape `(num_chains * num_samples,)`. Mean with `np.mean(fit["p"])`.
- **Vector parameter** `v` of length `K` → `fit["v"]` has shape `(K, num_chains * num_samples)`. Mean across samples with `np.mean(fit["v"], axis=1)`, producing a length-`K` vector.
- **Matrix parameter** `M` of shape `(R, C)` → `fit["M"]` has shape `(R, C, num_chains * num_samples)`. Mean with `np.mean(fit["M"], axis=2)`.

Write each posterior mean to its own CSV: scalar as a single number; vector as one number per line; matrix as a 2D array with no header unless the R output specifies one. Use `np.savetxt("out.csv", arr, delimiter=",")` for plain numeric output.

## 6. Gotchas

- `stan.build` compiles the model — first call is slow; reuse the compiled object across runs with different data only if signatures match.
- Posterior dict keys match the parameter names declared in Stan, **including** any transformations (e.g. `beta` not `mu_beta` unless that is the declared name).
- `random_seed` must be an `int`, not a NumPy scalar — convert with `int(seed)`.
- If the R script chains multiple `stan()` calls with different models, port each independently.
- Hyperparameters omitted in R fall to RStan defaults; in PyStan, omit them to use PyStan's defaults (they may differ — verify if results must match exactly).
```