---
name: numpy-c-extension
description: Build a C extension for numerical linear algebra with Python using the NumPy C API — covers parsing arrays, validating dimensions, raw data access, setuptools compilation, and a Python wrapper that coerces inputs to contiguous float64.
---

# Building a NumPy C Extension for Numerical Kernels

Use this procedure when you need a Python-callable C extension that operates on NumPy arrays (matrix-vector multiply, dot product, custom linear-algebra kernels) and want to avoid Python-loop overhead.

## 1. Write the C source

- Include `<numpy/arrayobject.h>` (not just `<Python.h>`).
- Call `import_array()` inside the module init function. Without it the NumPy C API segfaults on first use.
- Parse each array argument with `PyArg_ParseTuple` using the `O!` format and `&PyArray_Type`:
  `PyArg_ParseTuple(args, "O!O!", &PyArray_Type, &a, &PyArray_Type, &b)`
- Validate shape before touching data:
  - Vectors: `PyArray_NDIM(a) == 1` and matching length for operands.
  - Matrices: `PyArray_NDIM(a) == 2`, with `PyArray_DIM(a,0)` (rows) and `PyArray_DIM(a,1)` (cols).
  - Inner dimensions must agree (e.g. cols of A == length of x for matvec).
- Pull raw buffers with `PyArray_DATA(a)` (returns `void*`, cast to `double*` for float64) and strides with `PyArray_STRIDE(a, axis)` only if you need to honor non-contiguous layout.
- Implement the kernel as plain C `for` loops. For BLAS-1/2 kernels (dot product, axpy, matvec) a naïve triple-loop is the right starting point — keep the inner loop body trivial so `-O3 -ffast-math` can vectorize it.

## 2. Build with setuptools.Extension

- Use `numpy.get_include()` for `include_dirs` so `<numpy/arrayobject.h>` resolves:
  ```python
  from setuptools import Extension, setup
  import numpy
  ext = Extension("mymod", sources=["mymod.c"],
                  include_dirs=[numpy.get_include()],
                  extra_compile_args=["-O3", "-ffast-math", "-march=native"])
  setup(ext_modules=[ext])
  ```
- On Windows, gate `-march=native` / `-ffast-math` behind a `sys.platform != "win32"` check.
- Build with `python setup.py build_ext --inplace`.

## 3. Write the Python wrapper

- Coerce any list/tuple/array input to a contiguous float64 buffer before handing it to C. The C side assumes double-precision, C-contiguous memory:
  ```python
  import numpy as np
  A = np.ascontiguousarray(A, dtype=np.float64)
  x = np.ascontiguousarray(x, dtype=np.float64)
  ```
  Without `np.ascontiguousarray`, a non-contiguous slice will pass the type check but produce wrong results when the C code assumes row-major contiguous strides.
- Cast scalar returns with `float(...)` so callers comparing to Python literals (`== 0.0`) don't trip on `np.float64` truthiness quirks.
- Catch shape mismatches in Python with a clear `ValueError` before the C call — cheaper than letting the C function return NULL and chasing the traceback.

## 4. Sanity-check the extension

- Verify against NumPy: `assert np.allclose(my_matvec(A, x), A @ x)` and `abs(my_dot(a, b) - np.dot(a, b)) < 1e-10`.
- Test with non-contiguous inputs (transpose views, strided slices) to confirm the `ascontiguousarray` coercion path works.
- Benchmark vs the pure-Python/NumPy version to confirm the C path is actually faster on the target sizes; for very small n the FFI overhead can dominate.

## Common pitfalls

- Forgetting `import_array()` → silent segfault on the first NumPy C API call.
- Assuming row-major contiguous strides without `ascontiguousarray` on the Python side → silent wrong answers on transposed views.
- Building against a system NumPy header instead of `numpy.get_include()` → version mismatch crash at import.
- Returning `npy_float64` directly from the wrapper when the caller expects a Python `float` → equality comparisons fail.