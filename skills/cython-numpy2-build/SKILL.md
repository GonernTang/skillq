---
name: cython-numpy2-build
description: Build or repair a Cython extension that depends on NumPy >= 2.0. Use when a `.pyx`/`.pxd` file or `setup.py` uses a deprecated NumPy C API (direct `ndarray.data`, old `PyArray_*` macros, legacy module init) and fails to compile or import against modern NumPy. Covers detecting deprecated calls, applying NumPy 2.0 API replacements, configuring `cythonize` and `include_dirs`, building in place, installing, and verifying with the package's test suite.
---

# Build a Cython extension against NumPy >= 2.0

When a Cython project breaks after upgrading to NumPy 2.0, the cause is almost always a deprecated C API call. The repair procedure is the same regardless of which package: scan, replace, configure, build, verify.

## Procedure

### 1. Inventory `.pyx` / `.pxd` files for deprecated API use
Grep every Cython source for the patterns that NumPy 2.0 removed or changed:

- Direct buffer/data pointer access on `ndarray` (e.g. `arr.data`, `np.PyArray_DATA` used inconsistently).
- Legacy `PyArray_*` macros whose semantics changed (sizing, zero-stride, casting, object-touching).
- Module-init boilerplate that still assumes NumPy 1.x layout.

List each site with file + line so the next step is mechanical.

### 2. Apply NumPy 2.0 API replacements in each `.pyx`

- Reach ndarray buffers through the official macros (`PyArray_DATA`, `PyArray_SHAPE`, `PyArray_STRIDES`, `PyArray_DTYPE`, `PyArray_NDIM`) rather than direct field access.
- Cast buffers with the typed macros (`PyArray_DATA(arr)` cast to `dtype*`) — do not rely on implicit conversions.
- Call `import_array()` (or the `np.import_array()` wrapper) inside `cdef` blocks exactly once, with version guards if the package still supports old NumPy.
- Rewrite any hand-rolled `PyInit_<module>` so the module table matches what `cythonize` emits for NumPy 2.0; do not paste in legacy init code.
- Keep behavioural changes minimal: replace the call, preserve the surrounding logic.

### 3. Configure `setup.py` correctly

- Add `numpy.get_include()` to `include_dirs` so `numpy/arrayobject.h` (and the new public headers) resolve.
- Pass the Cython sources through `Cython.Build.cythonize(...)` with the compiler directives the package needs (language level, boundscheck, nonecheck, etc.). Do not skip `cythonize` even if `.c` files exist — let it regenerate.
- For an editable install prefer `pip install -e .`; for an in-place check use `python setup.py build_ext --inplace`.

### 4. Build, install, and verify

1. Clean any stale build artefacts from previous NumPy versions (`rm -rf build/ *.so` is usually enough).
2. `python setup.py build_ext --inplace` to confirm the extension compiles against NumPy 2.0.
3. `pip install .` (or `-e .`) so the package metadata picks up the new build.
4. Run the package's own test suite, excluding tests known to be dead or unrelated to the C extension. A green run on the extension's path is the verification signal.

## Pitfalls

- A `.c` file generated against NumPy 1.x will not be regenerated if `cythonize` is skipped; the deprecation warnings then hide behind stale C code.
- `import_array()` called outside a `cdef` block, or called twice, breaks module load silently on some platforms.
- `setup.py` that hardcodes `/usr/include` or an old numpy path will compile but crash at import — always derive the include path from `numpy.get_include()`.
- Do not blanket-rewrite surrounding logic while fixing the API call; the smallest diff that compiles and tests green is the right diff.

## Done when

- `build_ext --inplace` succeeds with no NumPy 2.0 deprecation errors.
- `pip install .` completes.
- The package's test suite (excluding known-dead tests) passes.