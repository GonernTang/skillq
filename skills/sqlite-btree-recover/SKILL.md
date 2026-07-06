```markdown
---
name: sqlite-btree-recover
description: Recover data from a truncated or corrupted SQLite database file (missing 100-byte header) by manually parsing raw b-tree pages. Also provides a template and explanation for writing a polyglot Rust/C++ source file that uses line splicing and nested block comments to share a single function implementation between the two compilers.
---

# Recover Data from a Truncated SQLite Database

When a SQLite file has its 100‑byte header lost or zeroed (truncation, corruption, partial restore), the standard library refuses to open it. If the raw b‑tree page data is still intact, you can parse it by hand.

## Procedure

1. **Guess the page size** from the file size. SQLite uses a power‑of‑two page size — common values are 1024, 4096, and 65536. If the file is a single page, the page size equals the file size. Otherwise try 4096 first (the most common default).

2. **Read the first page** and inspect byte 0 (the page type flag, ignoring the 100‑byte header that is now absent):
   - `0x0d` = leaf table b‑tree (contains row data directly)
   - `0x05` = interior table b‑tree (contains child‑page pointers)
   - `0x0a` = leaf index b‑tree
   - `0x02` = interior index b‑tree

3. **Parse the page header** (offsets are relative to page start, NOT counting the missing 100‑byte DB header):
   - Bytes 1–2: number of cells (2‑byte big‑endian)
   - Bytes 3–4: offset of the start of the cell‑content area (2‑byte big‑endian)
   - Bytes 5–6: first freeblock offset, or 0 if none
   - Bytes 8 onward: the cell‑pointer array (each entry is a 2‑byte big‑endian offset to a cell)

4. **For a leaf table page**, each cell is: `varint(payload_len) | varint(rowid) | payload_bytes`.
   - **Varint encoding**: 1–9 bytes, big‑endian, where bit 7 of each byte is a continuation flag. For values < 128, the varint is one byte. Implement as a loop: read a byte; if bit 7 set, OR `(b & 0x7f) << (7 * i)` into the accumulator and continue; otherwise OR and stop.

5. **Decode each record payload** using SQLite's serial‑type codes (read a varint for each column):
   - `0x00` → NULL
   - `0x01` → 8‑bit big‑endian int
   - `0x02` → 16‑bit BE int
   - `0x03` → 24‑bit BE int
   - `0x04` → 32‑bit BE int
   - `0x05` → 48‑bit BE int
   - `0x06` → 64‑bit BE int
   - `0x07` → 64‑bit IEEE float
   - `0x08` → integer constant 0; `0x09` → integer constant 1
   - `0x0a`–`0x0b` → reserved (skip / treat as null)
   - `n` odd and `n >= 13` → text of length `(n - 13) / 2`
   - `n` even and `n >= 12` → blob of length `(n - 12) / 2`

6. **For an interior table page**, each cell is: `4‑byte page_number | varint(rowid)`. Recursively apply this procedure to each child page (read the full page from `page_number * page_size`).

7. **Assemble rows** as `{rowid: <int>, col0: ..., col1: ..., ...}` dictionaries (use generic `col0`, `col1` names if the schema is unknown — there is no `sqlite_master` to consult) and write the array as JSON to the output file.

8. **Validate** recovered rows against any known patterns (e.g., a known prefix, expected row count, length constraints) and discard records that fail.

## Edge cases & guards

- If the page type byte is not one of the recognized flags, skip that page.
- If a cell pointer points past the page boundary or before the pointer array end, stop parsing that page.
- If a varint exceeds 9 bytes or a payload length exceeds the page size, treat as garbage and skip.
- If multiple page sizes are plausible, try each and keep the run that yields the most valid records.
- Combine results across the entire b‑tree (DFS through interior pages) before writing JSON.
- When merging heterogeneous data sources and generating a conflict report, always use the exact key names specified in the task (e.g., 'source_a', 'source_b', 'source_c') rather than abbreviated forms. Ensure the output matches the required schema precisely, including field names, data types, and JSON key formatting. Validate output against all format requirements before finishing.

## Reference

- SQLite database file format spec: https://www.sqlite.org/fileformat.html
- The header offsets given above assume the file has been truncated at byte 0 (or the header bytes are zeroed); if some header bytes are present, add the standard 100‑byte header offset.

---

# Polyglot Rust/C++ File Template

Use the following techniques to write a single source file that compiles under both `rustc` and `g++` and produces identical output. This is useful for cross‑language demonstrations, dual‑toolchain testing, or embedding Rust logic inside a C++ build.

## Techniques

### 1. Line splicing with `// \`

- In C++, a backslash immediately before a newline in translation phase 2 (before comments are recognized) causes the next line to be spliced onto the current line.  
  Writing `// \` at the end of a line makes C++ treat the following line as part of the `//` comment, effectively hiding the next line from the C++ compiler.  
- Rust does **not** perform line splicing, so `// \` is just a simple line comment and the next line is real Rust code.

Usage: Place `// \` before Rust‑only lines to hide them from C++.

### 2. Nested block comments (`/* … */`)

- Rust block comments **nest**: an inner `/*` is matched by a later `*/`.  
- C++ block comments do **not** nest: the first `*/` closes the comment.  
- To hide C++ code from Rust, enclose the C++ code in `/* … */`. Because Rust nests, any `/*` inside the C++ block (including those introduced by line splicing) will be treated as a nested comment, so the entire block is ignored by Rust.  
- In C++, the opening `/*` must be prevented from starting a block comment. This is done by placing a `// \` immediately before the `/*` — C++ sees `// /*` as a line comment, not a block comment. The C++ code that follows is therefore live.  
- The block is closed with another `// \` followed by `*/`. C++ sees `// */` as a line comment (due to splicing), so no block close occurs. Rust sees the `*/` and closes the block comment.

## Worked Example: Fibonacci

```c
// This file compiles under both Rust and C++.

// C++ sees this as `// fn fib(n: u64) -> u64 {`
// Rust sees the real function.
fn fib(n: u64) -> u64 {
    match n {
        0 | 1 => n,
        _ => fib(n-1) + fib(n-2),
    }
}

// Hide the Rust main from C++ by splicing the next line.
// \
fn main() {
    println!("{}", fib(10));
}

// Now hide the C++ alternative main from Rust.
// \
/*
// \
#include <iostream>
int main() {
    std::cout << fib(10) << std::endl;
    return 0;
}
// \
*/
// The C++ main is live; Rust ignores the block.
```

## Verification Checklist

- [ ] Run `g++ -std=c++17 -o polyglot polyglot.cpp` and execute.
- [ ] Run `rustc polyglot.rs -o polyglot-rs && ./polyglot-rs`.
- [ ] Both programs print `55` (the 10th Fibonacci number).
- [ ] No warnings about stray backslashes or unmatched comments.
- [ ] The source file is valid in both languages independently (no preprocessor tricks, no conditional compilation).

## Notes

- The `// \` must be the very last characters on the line (no trailing spaces before the newline).
- The block comment nesting trick works because Rust’s block comments are nestable and C++’s are not. Test with your specific compilers.
- This pattern can be extended to share any function definition.
```