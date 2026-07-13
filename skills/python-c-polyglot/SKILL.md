---
name: python-c-polyglot
description: Build a single source file that compiles and runs as both valid C and valid Python (a C/Python polyglot). Use when the task requires one file to be executable by both `gcc` and `python3`.
---

# Python/C Polyglot

A polyglot source file is one that is simultaneously valid in two (or more) languages. For Python and C, the trick is **mutual hiding**: each language ignores the other's code via constructs that are inert in that language.

## Core technique

- **Hide Python from C:** wrap Python code in `#if 0 ... #endif`. The C preprocessor discards it; Python treats `#if 0` as a comment (`#` starts a line comment).
- **Hide C from Python:** wrap C code in a Python triple-quoted string `""" ... """`. Python stores it as an unused string literal; C treats it as the body of a multi-line string literal that the preprocessor will skip (place it inside `#if 0`).

## File skeleton

1. Start the file with `#if 0` then immediately open a Python triple-quote:
   ```c
   #if 0
   """
   ```
   This begins both the C-disabled block and the Python string that will swallow the C source.

2. Write the C code (includes, main, logic). All C content lives *inside* the Python string literal — it is therefore a string to Python and (because of `#if 0`) a comment to C. The preprocessor discards it before parsing reaches `main`.

3. Close the Python string, end the `#if 0` block, then write the Python code:
   ```c
   """
   #endif

   # Python implementation here
   def solve(n):
       ...

   if __name__ == "__main__":
       solve(...)
   ```

4. End the file with `#endif` if the structure requires it (it does when the C portion itself sits inside an outer `#if 0`).

## Compile and run

- Compile: `gcc -o prog file.c` (Python code is gone before parsing).
- Run Python: `python3 file.c` (C code is just an unused string).

## Implementing the shared algorithm in both languages

For Fibonacci (and similar numeric sequences), implement an **iterative loop** for O(n) performance:

- **Python:**
  ```python
  def fib(n):
      a, b = 0, 1
      for _ in range(n):
          a, b = b, a + b
      return a
  ```

- **C:** (place *outside* any `#if 0` so gcc compiles it)
  ```c
  #include <stdio.h>
  long long fib(int n) {
      long long a = 0, b = 1;
      for (int i = 0; i < n; i++) {
          long long t = a + b;
          a = b;
          b = t;
      }
      return a;
  }
  int main(int argc, char **argv) {
      int n = argc > 1 ? atoi(argv[1]) : 0;
      printf("%lld\n", fib(n));
      return 0;
  }
  ```

Use `printf` in C and `print()` in Python. Use `atoi(argv[1])` to read a CLI argument in C; in Python use `sys.argv[1]` or `int(input())`.

## Validation

Test both paths against the same edge cases:
- `n = 0` → expect `0`
- `n = 1` → expect `1`
- `n = 20` → expect `6765` (Fibonacci(20) by F(0)=0, F(1)=1 convention)

Run all three through both interpreters and diff outputs. Any divergence means the Python and C implementations disagree on indexing or the initial values of `a`/`b`.

## Common pitfalls

- **Forgetting the final `#endif`:** causes gcc to see the Python code as a syntax error.
- **Opening `"""` inside the C string literal only once:** Python needs the closing `"""` *before* `#endif` so the C code below is real C, not a Python string continuation.
- **Quotation marks inside the C code:** if your C contains `"""`, escape it or use Python's raw string / single-triple-quote alternative.
- **Indexing convention:** confirm both implementations use the same F(0)=0, F(1)=1 convention before comparing outputs.