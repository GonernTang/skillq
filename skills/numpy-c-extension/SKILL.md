---
name: numpy-c-extension
description: Build a Python C extension that consumes NumPy arrays via the NumPy C API. Use when implementing compute kernels (matrix expressions, dot products, reductions, math over NumPy buffers) where C speed matters and the inputs/ outputs are NumPy arrays or scalars.
---

# NumPy C Extension

## When to use

Implement a Python-callable C function that reads one or more NumPy
arrays and returns a scalar / array, exposing it as a `setuptools`
extension module. Typical case: a hot numeric kernel (e.g. a
quadratic-form risk `sqrt(xᵀ S x)`, a dot-product return `xᵀ r`,
matrix multiply, custom reduction) that is too slow in pure Python.

## Procedure

1. **Header / boilerplate**
   - At the top of the `.c` / `.cpp` file:
     `#define NPY_NO_DEPRECATED_API NPY_1_7_API_VERSION`
   - Include headers in this order: `<Python.h>`, `<numpy/arrayobject.h>`,
     then any standard math (`<math.h>`).
   - In the module init function, call `import_array()` once before
     registering methods, and return `-1` on failure.

2. **Argument parsing**
   - Parse each NumPy argument with
     `PyArg_ParseTuple(args, "O!", &PyArray_Type, &arr)`.
   - For multiple arrays use `"O!O!"` (one `O!` per array, each paired
     with a `PyArray_Type` reference and a `PyArrayObject*`).
   - Validate `PyArray_NDIM(arr) == expected` and dtype == `NPY_DOUBLE`
     before accessing data; return `NULL` (or `PyErr_SetString`) on
     mismatch.

3. **Accessing the data buffer**
   - Cast `PyArray_DATA(arr)` to the C type you need (e.g.
     `double *buf = (double *) PyArray_DATA(arr);`).
   - For multi-dim arrays use `PyArray_DIMS(arr)[i]`; for 1-D buffers
     just `PyArray_DIM(arr, 0)` (or `n` from step 2).
   - Treat the buffer as row-major / C-contiguous (the NumPy default
     for `np.asarray(..., dtype=np.float64)`). For a covariance matrix
     `S` you can index as `S[i * n + j]`.

4. **Compute kernel**
   - **Scalar return via temp buffer** (for `xᵀ S x`-style expressions):
     allocate `double *tmp = malloc(n * sizeof(double))` (or a stack
     array `double tmp[N]` when `n` is bounded), fill it with the
     intermediate vector, then accumulate the final scalar with a
     second pass. Free `tmp` before returning.
   - **Simple dot product**: single nested loop, accumulate directly
     into a `double` accumulator.
   - Take `sqrt` (or other math) via `<math.h>` at the end.
   - Return the scalar with `PyFloat_FromDouble(result)` (or build a
     NumPy array with `PyArray_SimpleNew` + `PyArray_DATA` for array
     outputs).

5. **Python wrapper module**
   - In the `PyMODINIT_FUNC` (or `PyInit_*`) function create the
     module with `PyModule_Create(&moduledef)` and add the methods
     table (`PyMethodDef`) containing one entry per exposed C function.
   - Each `PyMethodDef` needs `ml_name`, `ml_meth = METH_VARARGS`
     wrapper, `ml_flags = METH_VARARGS`, `ml_doc`.
   - Cast the C function pointer with `(PyCFunction)`.

6. **Python-side wrapper function (recommended)**
   - Convert inputs defensively: `w = np.asarray(weights, dtype=np.float64)`
     and same for the covariance / matrix.
   - Call the C function with the raw arrays.
   - Cast the returned scalar with `float(...)` and return.

7. **Build configuration (`setup.py`)**
   - Use `setuptools.Extension` with `sources=["your_module.c"]`.
   - `include_dirs=[numpy.get_include()]` — required so the NumPy
     headers resolve.
   - `extra_compile_args=["-O3", "-ffast-math", "-funroll-loops"]`
     for release-style numerics.
   - Build with `python setup.py build_ext --inplace` (or
     `pip install .`).

8. **Verification**
   - Implement a pure-Python reference (NumPy expressions) for the
     same formula.
   - Call both implementations on a deterministic test case and assert
     numerical closeness with `np.allclose` (or `abs(a-b) < tol` for
     scalars).
   - Run a small benchmark loop (`timeit`) to confirm the C version is
     faster than the Python baseline for non-trivial sizes.

## Common pitfalls

- Forgetting `import_array()` → silent crash or `NULL` deref on first
  NumPy call.
- Forgetting `numpy.get_include()` in `include_dirs` → "找不到
  arrayobject.h".
- Passing lists instead of `np.float64` arrays → either accept
  conversion in the Python wrapper or call `PyArray_FROMANY` in C.
- Not freeing a `malloc`'d temp buffer → leak on every call.
- Mixing row/column-major assumptions on multi-dim arrays — for a
  symmetric covariance created from NumPy defaults, `S[i,j]` is
  `S[i*n+j]`.

## Quick checklist

- [ ] `NPY_NO_DEPRECATED_API` defined
- [ ] `import_array()` in module init, init returns `-1` on failure
- [ ] Each array arg parsed with `"O!"` + `PyArray_Type`
- [ ] `dtype` and `ndim` validated before buffer access
- [ ] Buffer accessed via `PyArray_DATA`, dims via `PyArray_DIMS` /
      `PyArray_DIM`
- [ ] Scalar return via `PyFloat_FromDouble`
- [ ] Python wrapper coerces inputs with `np.asarray(..., dtype=float64)`
- [ ] `setup.py` includes `numpy.get_include()` in `include_dirs`
- [ ] C baseline verified numerically against pure-Python reference