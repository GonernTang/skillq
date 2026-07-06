---
name: polyglot-rust-cpp
description: Create a single source file that compiles as both valid Rust and valid C++ using the backslash line-splicing trick. Use when a task requires a polyglot file accepted by both `rustc` and `g++ -x c++`.
---

# Polyglot Rust + C++ source file

## Core trick: backslash line splicing

In C/C++, a backslash at the end of a line splices the next physical line into the current logical line. This works **even inside a `/* ... */` comment**, and even inside a `//` line comment.

In Rust, `//` is a line comment (backslash is just text) and `/* ... */` is a block comment.

This asymmetry is the lever. Use it to hide one language's code from the other.

## Recipe

1. **Open the C++ block comment from Rust's perspective.**
   First line: `// \` followed by `/*` on the next line.
   - Rust sees: `//` comment (rest of line ignored).
   - C++ sees: trailing `\` splices the next line in, so it sees `// <whitespace> /* ...` which still starts a block comment.

2. **Place C++ code inside the block comment.**
   Anything between the `/*` and the matching `*/` is hidden from Rust (block comment) and visible to C++.

3. **Close the block comment**, then start Rust code.

4. **Hide each Rust line from C++** by prefixing it with `// \`.
   - C++ sees the trailing `\` and splices the next line in, but since `//` is a line comment, the spliced line is still inside that comment and gets discarded with it.
   - Rust sees `//` and ignores the rest of the physical line.

## Minimal skeleton

```
// \
/*
#include <iostream>
#include <cstdlib>
int main(int argc, char** argv) {
    int n = std::atoi(argv[1]);
    // ... C++ implementation ...
    std::cout << result << std::endl;
    return 0;
}
*/
// \
fn main() {
// \
    let args: Vec<String> = std::env::args().collect();
// \
    let n: u32 = args[1].parse().unwrap();
// \
    // ... Rust implementation ...
// \
    println!("{}", result);
// \
}
```

## Build and test both compilers

```bash
# Rust
rustc main.rs -o rmain && ./rmain <N>

# C++ (force the file to be treated as C++ even with .rs extension)
g++ -x c++ main.rs -o cmain && ./cmain <N>
```

Both binaries must produce identical output for the same input.

## Common pitfalls

- The `\` must be the **last character** on the line (no trailing spaces) for the splice to fire.
- Don't accidentally close the C++ block comment with `*/` while still writing C++ code — keep all `*/` to the single terminator after the C++ section.
- Make sure C++ `main` and Rust `main` don't both try to link into the same binary — they don't, because they live in two different translation units (the file is compiled twice, once per compiler).
- Match numeric edge cases (e.g. Fibonacci base cases `f(0)=1, f(1)=1`) so both implementations agree.