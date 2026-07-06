---
name: python-grpc-server
description: Step-by-step pattern for creating a Python/C polyglot single source file that compiles as C and runs as Python, using #if 0 / #endif preprocessor guards combined with triple-quoted strings, with a Fibonacci computation template and testing guidance.
---

# Python/C Polyglot Source File

## When to use
Use this skill when you need a single file that is both valid C (compilable with gcc) and valid Python (run with python3). This is useful for projects that must be distributed as a single file, for cross-language demonstrations, or for embedding logic that can be tested in both environments.

## Procedure

### 1. Understand the trick
The polyglot works by exploiting the C preprocessor and Python’s triple-quoted string syntax together:

- Python’s `#` starts a comment, so `#if 0` is a comment in Python.
- C’s preprocessor respects `#if 0` … `#endif` to skip code.
- A triple-quoted string `"""` in Python spans multiple lines.  
  When placed inside a `#if 0` block, C skips it, but Python sees the `"""` and starts a multi-line string that absorbs everything until the closing `"""`.

The structure is:

```
#if 0
"""  # ← opens Python string, C skips
#endif

/* C code here (seen by C, ignored by Python because string is open) */

#if 0
"""  # ← closes Python string, C skips
#endif

#if 0
/* Python code here (seen by Python after comments, skipped by C) */
#endif
```

### 2. Write the file template
Create a file (e.g., `polyglot.c.py`) with the following skeleton:

```c
#if 0
"""
#endif

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

/* C implementation here */

int main(int argc, char **argv) {
    /* parse argv, compute Fibonacci, print result */
}

#if 0
"""
#endif

#if 0
# Python implementation here
def fibonacci(n):
    ...
if __name__ == "__main__":
    import sys
    ...
#endif
```

### 3. Fibonacci-specific guidelines
- **C side**: Use `unsigned long long` (0 to 18446744073709551615) for values up to fib(93).  
  Accept N as a command-line argument (`argv[1]`). Validate and convert with `strtoull`. Print result with `printf("%llu\n", result)`.
- **Python side**: Use simple integer arithmetic (unbounded).  
  Accept N from `sys.argv[1]`. Print result with `print(result)`.
- Both paths should produce identical output for N from 0 to 93. Python can go higher.

### 4. Compile and run
```bash
# Compile with gcc (warnings about stray `"""` are expected and harmless)
gcc -o polyglot polyglot.c.py

# Run as C binary
./polyglot 10

# Run as Python script
python3 polyglot.c.py 10
```

### 5. Test both paths for agreement
For several values of N (0, 1, 2, 40, 93) compare output:
```bash
diff <(./polyglot $N) <(python3 polyglot.c.py $N) && echo "match"
```

### 6. Edge case handling
- Missing argument → print error to stderr, exit code 1.
- Negative N → print error to stderr, exit code 1.
- Non-numeric argument → print error to stderr, exit code 1.
- N > 93 (C side) → can either reject with error or accept but note overflow (unsigned long long wraps). Python is safe for larger N.

## Common pitfalls
- Do not put any blank lines before the first `#if 0` line – Python’s indentation rules may cause `SyntaxError` if the `#if 0` comment is preceded by a blank line (though usually fine). Safe to start file with `#if 0`.
- The C compiler will warn about a string literal `"""` being malformed; these warnings are harmless and can be suppressed with `-Wno-stray-string-literals` if desired.
- The `#endif` lines must be exactly that; no trailing spaces.
- For more complex C code, ensure all includes and definitions are after the first `#if 0`...#endif block and before the second one. Python code goes after the closing `#if 0` block.

## Example file (Fibonacci, compiled & tested)
Refer to the full template above; the same pattern works for any algorithm that can be expressed in both languages.