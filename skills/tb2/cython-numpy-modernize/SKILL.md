---
name: cython-numpy-modernize
description: Modernize Cython extensions for NumPy >=2.0 and Python 3.9+. Fix deprecated dtype aliases, modernize stdlib imports, adapt third-party C API renames, then rebuild and verify.
---

# Modernize Cython Extensions for NumPy 2.0+

Use when porting a Cython-based package (with `.pyx`/`.pxd` files compiled via `setup.py build_ext`) to run on NumPy 2.0+ and Python 3.9+. The package may also depend on a native C library exposed through Cython.

## Step 1 — Audit source for deprecated NumPy aliases

Scan **every** `.py` and `.pyx` file (use ripgrep, not the shell `grep`) for the deprecated scalar aliases that NumPy 2.0 removes:

| Deprecated | Replace with |
|---|---|
| `np.int` | `int` (Python) or `np.int64` (in `.pyx` dtype specs) |
| `np.float` | `np.float64` |
| `np.bool` | `bool` |
| `np.complex` | `complex` |
| `np.object` | `object` |
| `np.str` | `str` |
| `np.long` | `np.int64` |

Special case for `.pyx` files: in `np.ndarray(..., dtype=...)` calls, `np.int` will *not* resolve to a Python `int` — substitute an explicit `np.int_`/`np.int64` or a plain Python `int`.

## Step 2 — Fix Python 3.9+ stdlib removals

Replace `from fractions import gcd` with `from math import gcd`. `fractions.gcd` was removed in Python 3.9. Apply the same audit to other removed-in-3.9 symbols if the code targets older behavior (`math.floor` semantics, `threading.currentThread`, etc. — only act if the codebase uses them).

## Step 3 — Adapt third-party C-API renames

If the package wraps a native library through Cython, check that library's changelog for renamed struct fields or functions. Common pattern: a graph/planarity-style library renaming `pos`/`start`/`end` to `vertex_position`/`vertex_start`/`vertex_end`. Update every call site in both `.pyx` and `.pxd`.

## Step 4 — Rebuild in place

```
python setup.py build_ext --inplace
```

This recompiles every `.pyx` against the patched headers. Run from the repo root so `setup.py` finds `Extension(...)` sources. If it fails with `numpy/...` symbol errors, you missed an alias in Step 1.

## Step 5 — Verify with tests and target use case

Run the package's test suite, then exercise the actual feature the user asked about (don't stop at "it imports"). Cython type errors only surface at the call boundary, so import success ≠ working extension.

## General rules

- Apply Step 1 across `.py` and `.pyx` together — partial fixes leave the package half-working.
- Cython dtype fixes must use a concrete NumPy dtype, not the Python builtin, because Cython type-generators don't coerce bare `int`.
- After every batch of edits, rebuild before testing — stale `.so` files mask regressions.
- If the build linker complains about missing symbols from the wrapped C library, re-check Step 3; the rename was likely missed in one site.