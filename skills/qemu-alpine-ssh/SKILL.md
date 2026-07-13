---
name: qemu-alpine-ssh
description: Create a single-file Rust/C++ polyglot that compiles and runs with both rustc and g++ using comment tricks. Use when you need an identical binary from two languages for cross‑validation or demonstration.
---

# Rust/C++ Single‑File Polyglot

Produce a single `.rs`/`.cpp` file that compiles and runs **identically** under `rustc` and `g++`. The technique relies on C++ line splicing (`// \`) and Rust block comments (`/* … */`) to hide each language’s code from the other compiler.

## Prerequisites

- `rustc` (Rust compiler)
- `g++` (C++ compiler)
- Both must be on `$PATH`

## Procedure

### 1. Write the polyglot file

The file must have the following structure (comments explain the mechanism):

```
// \           ← C++ sees a line comment that continues to the next line (line splicing)
/*             ← In C++: still inside the line comment (ignored)
               ← In Rust: starts a block comment → everything below is hidden from Rust

   // ---- C++ code that goes here (hidden from Rust) ----
   #include <cstdio>
   long long fib(int n) {
       if (n <= 1) return 1;          // note: f(0)=1, f(1)=1
       return fib(n-1) + fib(n-2);
   }
   int main() {
       int n = 15;
       printf("%lld\n", fib(n));
       return 0;
   }

// This ends the Rust block comment: */   ← `*/` ends Rust's block comment

// \           ← hides the following Rust line from C++ (line splicing)
fn fib(n: u64) -> u64 {
// \           ← each line inside fn main() must be preceded by `// \`
    if n <= 1 { 1 } else { fib(n-1) + fib(n-2) }
}

// \
fn main() {
// \
    let n = 15;
// \
    println!("{}", fib(n));
// \
}
// \           ← trailing backslash-newline avoids C++ warning
```

**Key points:**
- Every Rust line after the first `// \` must be prefixed with `// \` (including the `fn main()` declaration and all lines inside it).
- The C++ code is placed *after* the opening `/*` and *before* the closing `*/`.
- The closing `*/` must be on its own line, typically after a comment like `// This ends the Rust block comment: */`.

### 2. Compile and run

```bash
# Compile as Rust
rustc polyglot.rs -o polyglot_rust
./polyglot_rust

# Compile as C++
g++ -x c++ polyglot.rs -o polyglot_cpp
./polyglot_cpp
```

Both binaries must print the same number.

### 3. Verify multiple inputs

Extend the test to cover `n = 0, 1, 2` (edge cases) and a few more values. The Fibonacci definition used here is **shifted** so that `f(0) = 1, f(1) = 1`. Both languages must implement the same formula.

Example output for `n = 15`: `987`

## Reuse checklist

1. Ensure every Rust line is preceded by `// \` (including the final line).
2. Ensure the file ends with `// \` (no newline after the backslash).
3. Verify that `g++` does not emit a “backslash‑newline at end of file” warning.
4. Test at least `n=0,1,2` to confirm the sequence matches between compilers.

## Troubleshooting

- **Rust compilation error** – most likely an unclosed `/*` or a Rust line missing the `// \` prefix.
- **C++ compilation error** – check that the opening `// \` is on the very first line and that `/*` is on the next line. C++ line splicing only works if the backslash is the last character on the line.
- **Different outputs** – the Fibonacci implementations must use the same base cases. Change both `if n <= 1` conditions to match.

## Notes

- The file extension `.rs` is conventional; `g++` needs `-x c++` to treat it as C++.
- No external dependencies are required – only `rustc` and `g++`.