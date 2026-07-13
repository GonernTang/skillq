---
name: numpy-c-extension
description: Build a fast Python C extension for numerical computations over NumPy arrays, including argument parsing, dtype/dim validation, vectorized kernels, setuptools build, and a Python wrapper with correctness/benchmark verification.
---

# Building a NumPy C Extension for Numerical Kernels

Use this skill when you need a Python-callable C extension that operates on `np.ndarray` inputs faster than pure Python/NumPy can deliver for tight inner loops (dot products, quadratic forms, custom matvec-style kernels).

## 1. Parse and validate NumPy arguments in C

In the C entry point, parse each array argument with `PyArg_ParseTuple` using the `O!` format and `&PyArray_Type`:

```c
if (!PyArg_ParseTuple(args, "O!O!", &PyArray_Type, &x_arr, &PyArray_Type, &y_arr))
    return NULL;
```

Then enforce dtype and dimensionality up front, returning `NULL` on any failure:

```c
if (PyArray_TYPE(x_arr) != NPY_FLOAT64 || PyArray_NDIM(x_arr) != 1) {
    PyErr_SetString(PyExc_ValueError, "expected 1-D float64 array");
    return NULL;
}
```

Get a raw pointer and length:

```c
double *x = (double *)PyArray_DATA(x_arr);
npy_intp n = PyArray_DIM(x_arr, 0);
```

For 2-D matrices compute row/column indices manually using `i * cols + j`, or read strides via `PyArray_STRIDE(arr, 0)` / `PyArray_STRIDE(arr, 1)` when you need stride-agnostic access. Keep `cols = PyArray_DIM(mat, 1)` and `rows = PyArray_DIM(mat, 0)` cached locally.

## 2. Implement the kernel as plain nested loops

For two-array operations:

- **Dot product** `x^T r` — a single loop, accumulate into a `double`, return it (wrapped as `PyFloat_FromDouble`).
- **Quadratic form** `sqrt(x^T S x)` — first compute `S * x` into a stack buffer or output array via nested `i,j` loops, then dot that intermediate with `x`, then take `sqrt`.

Keep loops simple so the compiler's `-O3 -ffast-math -funroll-loops` flags can auto-vectorize. Use `npy_intp` (not `int`) for all index variables to match NumPy's own widths.

Return Python floats via `PyFloat_FromDouble(...)`; return NULL after `PyErr_SetString` on any error path.

## 3. Wrap with a Python module function

Write a thin `.py` (or C-generated) wrapper that:

1. Coerces any sequence-like input to `np.float64` via `np.asarray(x, dtype=np.float64)`.
2. Calls the C function with the resulting arrays.
3. Returns the scalar result.

Normalizing through `np.asarray` lets callers pass Python lists, tuples, or arrays interchangeably.

## 4. Build with setuptools

Use `setuptools.Extension` with NumPy's headers on the include path and aggressive optimization flags:

```python
from setuptools import setup, Extension
import numpy

ext = Extension(
    "your_module",
    sources=["your_module.c"],
    include_dirs=[numpy.get_include()],
    extra_compile_args=["-O3", "-ffast-math", "-funroll-loops"],
)
setup(name="your_module", ext_modules=[ext])
```

Build in place with `python3 setup.py build_ext --inplace` so `import your_module` works from the project directory.

## 5. Verify correctness and benchmark speed

Before celebrating, prove two things:

- **Correctness** — compare the C-extension output against a pure-Python (and/or `np.dot`-based) reference implementation on non-trivial inputs; assertions should hold to within floating-point tolerance.
- **Speed** — measure wall-clock execution time on representative input sizes for both the C extension and the Python baseline, and confirm the C version is faster (typically many × for small/medium arrays where Python interpreter overhead dominates).

If either check fails, fix the underlying code — do not declare success on a partial verification.