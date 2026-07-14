---
name: numpy-c-extension
description: Build a NumPy C extension that wraps raw pointer math for numerical computations (e.g., portfolio risk/return, matrix-vector products). Covers PyArg_ParseTuple with 'O!' format, PyArray_DATA zero-copy access, validation, module method table setup, setup.py build with -O3 flags, and verification against a Python baseline.
---

# NumPy C Extension for Numerical Kernels

Use this skill when you need to accelerate a numerical computation (matrix-vector products, dot products, reductions, quadratic forms) by writing a C extension that operates directly on NumPy array buffers.

## 1. Understand the Math from Baseline

Read the existing Python implementation first. Identify:
- **Inputs**: which arrays, what shapes/dtypes
- **Math**: e.g., `risk = sqrt(x^T · S · x)`, `return = x^T · r`
- **Output**: scalar or array, dtype

## 2. Parse NumPy Arrays in C

Use `PyArg_ParseTuple` with the `'O!'` format and `&PyArray_Type`:

```c
static PyObject *py_func(PyObject *self, PyObject *args) {
    PyArrayObject *arr1 = NULL, *arr2 = NULL;
    if (!PyArg_ParseTuple(args, "O!O!", &PyArray_Type, &arr1, &PyArray_Type, &arr2)) {
        return NULL;
    }
    ...
}
```

Validate dimensions before computing:
- 1D arrays must be 1-D (`ndim == 1`)
- 2D arrays must be square (`shape[0] == shape[1]`)
- Cross-dimension compatibility (e.g., `weights.shape[0] == cov.shape[0]`)

## 3. Zero-Copy Data Access

Get the raw `double*` pointer without copying:

```c
double *x = (double *)PyArray_DATA(arr1);
double *S = (double *)PyArray_DATA(arr2);
```

The data is C-contiguous, so `S[i * n + j]` indexes row `i`, column `j`.

## 4. Implement the Computation

For matrix-vector products, nest loops: `temp[i] = sum_j S[i,j] * x[j]`, then reduce. For simple dot products, a single loop suffices.

Return Python scalars with `PyFloat_FromDouble(...)` or `PyLong_FromLong(...)`. Return NULL on error after setting a Python exception.

## 5. Wire Up the Module

Declare a method table and module definition:

```c
static PyMethodDef Methods[] = {
    {"func_name", py_func, METH_VARARGS, "docstring"},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT, "_modname", NULL, -1, Methods
};

PyMODINIT_FUNC PyInit__modname(void) {
    import_array();  // required for NumPy C API
    return PyModule_Create(&moduledef);
}
```

`import_array()` must be called once per module before any `PyArray_*` use.

## 6. Python Wrapper

A thin wrapper imports the compiled module, casts inputs to `np.float64` (so the C `double*` cast is safe), and calls the C functions:

```python
import numpy as np
from . import _modname

def func_name(weights, matrix):
    weights = np.ascontiguousarray(weights, dtype=np.float64)
    matrix = np.ascontiguousarray(matrix, dtype=np.float64)
    return _modname.func_name(weights, matrix)
```

## 7. Build with setup.py

Use `setuptools.Extension` with optimization flags:

```python
from setuptools import setup, Extension
import numpy as np

setup(
    ext_modules=[Extension("_modname", ["src.c"],
                           include_dirs=[np.get_include()],
                           extra_compile_args=["-O3", "-ffast-math", "-funroll-loops"])],
)
```

Build with: `python3 setup.py build_ext --inplace`

## 8. Verify Correctness and Speedup

Run the C extension and the Python baseline on identical inputs. Accept results when:
- **Numerical agreement**: `abs(c_result - py_result) < 1e-10` (or appropriate tolerance)
- **Speedup**: C version faster than Python baseline by the target factor (e.g., >1.2x) for inputs of meaningful size (5000+ elements)

If correctness fails, suspect dtype mismatch (int vs float), non-contiguous input, or shape validation bugs. If speedup is missing, suspect missing `-O3`, accidental copies, or under-sized test inputs.

## Common Pitfalls

- Forgetting `import_array()` → silent crashes or `numpy/arrayobject.h` symbol errors
- Casting non-float64 arrays to `double*` → garbage values; always cast in the wrapper
- Returning a borrowed reference or skipping NULL return on error → segfaults
- Off-by-one in inner loops when the matrix is not symmetric (use `S[i*n+j]` not `S[j*n+i]`)