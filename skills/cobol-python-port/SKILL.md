---
name: cobol-python-port
description: Re-implement a COBOL program with fixed-length sequential files in Python, validated byte-for-byte against the COBOL reference output.
---

# Porting a COBOL fixed-record program to Python

Use this procedure when the goal is a Python replacement that produces byte-identical `.DAT` files to the original COBOL implementation.

## 1. Reverse-engineer the record layout

- Read the COBOL source and locate every `FILE-CONTROL` and `FD` entry.
- For each FD, list: file name, `RECORD CONTAINS n CHARACTERS` (or the sum of its fields), and every field with its `PIC` clause and position.
- Decode PIC clauses:
  - `PIC X(n)` → `n` characters, space-padded on the right.
  - `PIC 9(n)` → `n` ASCII decimal digits, zero-padded on the left; treat as a string, not a Python `int`, until you need to compute.
  - `PIC 9(n)V9(m) COMP-3` or signed variants — convert in code if present, but most legacy `.DAT` ports use plain display decimals.
- Confirm the layout against the actual data file with `od -A x -t x1z file.DAT | head` (or `xxd`). COBOL SEQUENTIAL files are concatenated fixed-length records with no delimiters, so record length × record count must equal file size exactly.

## 2. Build the I/O layer in Python

For each file, define a `record_size` constant and a small class or `dataclass` that maps each PIC field to a `(offset, length, kind)` triple. Two implementation choices:

- **`struct` module** — concise, but only convenient when every field is fixed-width and numeric. Encode `PIC X(n)` as `s` (padding with `b" "`) and `PIC 9(n)` as zero-padded ASCII bytes (still using `s`, not an integer).
- **Manual `bytes` slicing** — read the whole file as `data = path.read_bytes()`, then slice `data[i:i+record_size]` for each record, and `field = record[offset:offset+length].decode("ascii")` for each field. This is usually clearer and matches the COBOL mental model 1:1.

Write helpers:

```python
def read_records(path: Path) -> list[bytes]: ...
def write_records(path: Path, records: list[bytes]) -> None: ...
def get(rec, off, ln): return rec[off:off+ln].decode("ascii")
def put(rec, off, ln, val, kind): ...  # kind = "x" or "9"
```

For `kind="9"` pad on the left with `b"0"`; for `kind="x"` pad on the right with `b" "`. Validate `len(val) <= ln` before padding so overflow fails loudly.

## 3. Port the PROCEDURE DIVISION

Translate each paragraph in order, preserving:

- The exact sequence of `READ` / `REWRITE` / `WRITE` operations.
- Conditional branches (especially "not found", "ownership", and "insufficient funds" type checks) — COBOL `IF ... ELSE ... END-IF` becomes `if/else`.
- When the file is saved: most legacy programs rewrite the record in place only on the success branch; do not save on the failure branch.
- Numeric arithmetic: parse `PIC 9` to `int`, do the math, re-encode back to the same width with `str(val).zfill(n).encode("ascii")`. Watch for overflow when the result could exceed the field width.

Keep the program's external interface (the input prompt format, the screen output) similar enough that the same operator script can drive both implementations.

## 4. Establish the COBOL reference

- Compile with GnuCOBOL: `cobc -x -o program program.cbl`.
- Build a small set of test inputs covering normal cases plus edge cases: zero amounts, self-transactions, missing IDs, duplicate IDs, balance overflow.
- Run the COBOL binary on each input and snapshot every `.DAT` output (and any printed report) into a `reference/` directory. These are the ground truth.

## 5. Diff Python output against the reference

Run the Python script on the same inputs, then compare byte-for-byte:

```bash
for f in reference/*.DAT out/*.DAT; do cmp "$f" "${f#reference/}" && echo "OK $f" || echo "MISMATCH $f"; done
```

For any mismatch, `od -A x -t x1z` the differing record from both files side by side and inspect: padding direction, trailing spaces vs zeros, field-order swap, off-by-one offset, or a missing `REWRITE`.

## 6. Iterate until clean

Repeat step 5 until every `.DAT` and every printed report is identical to the COBOL reference for the full test set. Common pitfalls to watch for:

- Forgetting to right-pad `PIC X` after writing (Python string slicing drops trailing spaces silently).
- Confusing `PIC 9` with leading zeros vs trailing zeros.
- Re-reading a record after a `REWRITE` instead of using the in-memory copy.
- Writing to the wrong file in ORGANIZATION rewrite mode.

## When to skip this skill

- The COBOL program uses VSAM, indexed files, or `SELECT ... ASSIGN ... ORGANIZATION IS INDEXED` — those need a different I/O strategy.
- Output format is allowed to differ (only business semantics matter).
- The `.DAT` files have line-based records or delimiters (then they're not fixed-length sequential in the COBOL sense).