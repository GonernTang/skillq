---
name: llm-batching-scheduler
description: Create a polyglot file that runs identically as both Python and C using `#if 0` preprocessor blocks and Python triple-quoted strings, with guidance on shebang lines, argument parsing, and testing.
---

# Polyglot C/Python File Construction

This skill describes how to write a single source file that is valid both as Python and as C, producing the same output when executed by either interpreter/compiler.

## 1. Structure the file with `#if 0` blocks

Wrap the Python code inside a `#if 0` … `#endif` block. The C preprocessor skips everything between `#if 0` and `#endif`, while Python treats lines starting with `#` as comments, so the Python code executes normally.

```
#if 0
<python code>
#endif
```

## 2. Embed the C code in a Python triple‑quoted string

After the Python block, write another `#if 0` … `#endif` block that contains only `"""` (opening triple‑quote). Then place the C code, and finally a closing `#if 0` block with `"""`.

```
#if 0
"""
#endif
<c code>
#if 0
"""
#endif
```

Python sees the `"""` as the start of a multi‑line string and treats everything until the closing `"""` (which is inside the last `#if 0`) as string content – thus the C code is ignored. The C preprocessor strips both `#if 0` blocks, so the compiler sees only the C code.

## 3. Handle shebang line (optional)

If a shebang is needed, use `//usr/bin/python3` or place it in a comment that both languages ignore. A common trick:

```
#if 0
exec("""exec 2>/dev/null; exec python3 $0 "$@"
""")
#endif
```

This is only necessary if the file is meant to be executed directly as a script.

## 4. Argument parsing

- **Python:** use `if __name__ == '__main__'` and `sys.argv` (import sys).  
- **C:** define `main(int argc, char **argv)` and use `argv[1]`, etc.

Place the argument‑parsing code in the respective language section.

## 5. Ensure identical output for identical inputs

Both implementations must:
- Print the same results (same formatting, same newlines).  
- Handle the same command‑line arguments (same number and order).  
- Use the same algorithmic logic (same function definitions, same output format).

## 6. Test with both interpreters/compilers

Run:
```bash
python3 myfile
gcc myfile -o out && ./out
```

Provide identical inputs and compare output line‑by‑line. If any discrepancy exists, adjust the code (usually Python’s `print()` vs C’s `printf()` formatting).

## Common pitfalls

- Forgetting the closing `"""` inside the last `#if 0` – Python will fail with a syntax error.  
- Using `#include` or C‑style comments that break Python’s string literal (e.g., stray `"""` inside the C code).  
- Mismatched argument parsing (e.g., Python expects `--flag` while C expects a positional argument).  
- The C preprocessor may emit warnings about unterminated string literals for the `"""` lines; these are harmless and can be suppressed with `-Wno-missing-terminating` if desired.