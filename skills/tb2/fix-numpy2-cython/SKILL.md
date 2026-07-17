---
name: fix-numpy2-cython
description: Fix Numpy 2.0 compatibility issues in a Cython-based Python package. Covers deprecated type-alias replacements, Python stdlib removals, third-party library key renames, Cython rebuild, and verification.
---

# Fix Numpy 2.0 Compatibility in Cython Extensions

## When to use

A Python package uses Cython (`.pyx` files) and depends on Numpy. After upgrading to Numpy 2.0, the build or runtime fails with `AttributeError` for removed type aliases, or downstream libraries break.

## Procedure

### 1. Replace deprecated Numpy type aliases

Numpy 2.0 removed the `numpy.` prefixed scalar aliases. Search both `.py` and `.pyx` files and apply these substitutions:

| Old (deprecated) | New |
|------------------|-----|
| `np.float` | `float` (or `np.float64` if explicit dtype needed) |
| `np.int` | `int` (or `np.int64` if explicit dtype needed) |
| `np.bool` | `bool` (or `np.bool_` if explicit dtype needed) |
| `np.complex` | `np.complex128` |
| `np.object` | `object` (or `np.object_`) |
| `np.str` | `str` (or `np.str_`) |
| `np.long` | `int` |

Tip: use a project-wide regex search (e.g. `\bnp\.float\b`, `\bnp\.int\b`, `\bnp\.bool\b`, `\bnp\.complex\b`) to enumerate every site.

### 2. Replace removed Python stdlib functions

If the code uses `fractions.gcd`, switch to `math.gcd`:

```python
# before
from fractions import gcd
# after
import math
gcd = math.gcd
```

Audit other stdlib names removed in recent Python versions if encountered (e.g. `collections.MutableMapping`, `imp`).

### 3. Update third-party library attribute keys

Some C/C++-backed Python libraries (e.g. `planarity`) renamed internal attribute-dict keys across versions. If a `KeyError` arises for keys like `'pos'`, `'start'`, `'end'`, consult the upstream changelog and apply the rename. Common pattern:

| Old key | New key |
|---------|---------|
| `'pos'` | `'vertex_position'` |
| `'start'` | `'vertex_start'` |
| `'end'` | `'vertex_end'` |

Apply analogous renames for any parallel edge-data or face-data keys.

### 4. Rebuild the Cython extensions

Ensure `Cython` and `numpy` are installed in the build environment, then rebuild in place:

```bash
python setup.py build_ext --inplace
```

If the project uses a `pyproject.toml` with `setuptools` and `cythonize`, prefer:

```bash
pip install -e .
```

which triggers a fresh Cython compile of all `.pyx` → `.c` → `.so`.

### 5. Install the package

Install in editable mode so subsequent code edits don't require reinstalling:

```bash
pip install -e .
```

### 6. Run the test suite

Run the package's tests, excluding any known problematic or dead test files (broken upstream fixtures, deprecated APIs unrelated to the migration, etc.):

```bash
pytest path/to/tests --ignore=path/to/dead_tests
```

If failures appear, re-inspect: most migration errors surface as `AttributeError` or `KeyError` at import or first call.

## Pitfalls

- `np.float` and `np.int` silently fell back to Python builtins in some Numpy 1.x versions; replacing them with `float`/`int` changes nothing semantically for arithmetic but is required for code that stored them as type objects.
- `np.bool` is a reserved word in NumPy 2.0 and shadows Python's `bool`; never write `np.bool` again.
- Cython `.pyx` files go through the C compiler — re-run `build_ext --inplace` after every source edit, even tiny ones.
- Renamed dict keys in third-party libraries (step 3) only matter if your code reads those keys directly; pure API callers are unaffected.