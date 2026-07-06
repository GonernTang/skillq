---
name: cobol-to-python
description: Migrate a COBOL program that processes sequential fixed-length records into an equivalent Python program. Use when the task is COBOL modernization, legacy-to-Python translation, or reproducing a COBOL batch file-processing program in Python. Covers reading the COBOL FILE SECTION for record layouts, mapping PIC clauses to Python struct formats, transcribing PROCEDURE DIVISION logic, and verifying byte-level equivalence against a compiled GnuCOBOL reference.
---

# COBOL Sequential-Record Program → Python

## When to apply

The source program:
- Reads and writes one or more **sequential files** of **fixed-length records**.
- Declares record layouts in a **FILE SECTION** using `FD`/`01` levels with `PIC` clauses.
- Implements batch logic (READ/WRITE/REWRITE, IF/PERFORM arithmetic, conditional updates) in the **PROCEDURE DIVISION**.

Goal: a Python program that reads, transforms, and writes the same files with **byte-identical** output to a GnuCOBOL-compiled reference.

## Procedure

### 1. Read the COBOL source for record structure

Read the entire program. Focus first on the **FILE SECTION**:
- `FD` entries for each file (record name, blocking if any).
- `01` record layouts with their sub-fields, `PIC` clauses, and `REDEFINES`.
- Note field order, lengths, and any filler/justified clauses.

Then read the **PROCEDURE DIVISION** for the algorithm: loops, conditionals, arithmetic, file open modes, EOF handling, control breaks, and any report/aggregation logic.

### 2. Confirm byte-level layout with hex dumps

PIC clauses lie. Verify the actual on-disk format with a hex dump of an input file (and, if available, a reference output):

```bash
od -An -c input.dat | head   # show characters/bytes
od -An -t x1 input.dat | head  # show hex bytes
```

Confirm:
- Record length (sum of `PIC` widths, accounting for `REDEFINES` and `FILLER`).
- Padding (space-padded `PIC X`, zero-padded `PIC 9`, sign overpunch if `SIGN LEADING`/`TRAILING`).
- Line endings (CRLF vs LF) and any block/record descriptor words.

### 3. Map PIC clauses to Python `struct` formats

Build a per-record struct format string and a parallel list of `(name, parser)` tuples:

| COBOL PIC | Python representation |
|---|---|
| `PIC X(n)`  | `'%ds' % n` (or raw `n` bytes after slicing) |
| `PIC 9(n)`  (display) | decode as ASCII digits; `int(field.decode('ascii'))` |
| `PIC 9(n) COMP` / binary | `'%di' % n` or `'<i'`/`'>i'` little/big endian |
| `PIC 9(n) COMP-3` / packed decimal | nibbles; decode manually (last nibble = sign: `C`/`D`/`F`) |
| `PIC S9(n)V9(m) COMP-3` | packed decimal with implied decimal point |
| `PIC 9(n)V9(m)` (display) | ASCII digits, insert decimal point before last `m` digits |

Build helpers:
- `pack_record(values)` — format a list of values using the format string.
- `unpack_record(buf)` — return a list of values from a fixed-length byte slice.
- `display_num(s, scale=0)` — for ASCII numeric fields.
- `packed_to_int(buf)` / `int_to_packed(n, size, scale)` — for COMP-3.

### 4. Write the Python equivalent

- Open files in **binary mode** (`'rb'`, `'wb'`). Do **not** use text mode — line-ending translation breaks byte equivalence.
- Iterate with `while True:` plus an `EOFError` or zero-length read pattern (Python has no native COBOL `AT END`).
- Transcribe `IF`/`PERFORM`/arithmetic logic 1:1. Be careful with:
  - **Rounding**: COBOL `ROUNDED` rounds away from zero on ties; Python `round()` is banker's rounding — implement truncation/rounding explicitly if needed.
  - **Signed zero**: COBOL preserves sign on zero results; Python `+0 == -0`.
  - **Truncation vs floor**: integer division in COBOL truncates toward zero; Python `//` floors for negatives.
- Write updated records back with `struct.pack` to the exact record length.

### 5. Build the reference with GnuCOBOL

```bash
cobc -x program.cbl -o reference
./reference       # produces reference output files
```

Use the same input files for both the reference and the Python version.

### 6. Verify byte-for-byte equivalence

```bash
cmp reference_output.dat python_output.dat
# or:
diff <(od -An -t x1 reference_output.dat) \
     <(od -An -t x1 python_output.dat)
```

If they differ:
- Hex-diff the first divergent record to identify the field.
- Check the field's PIC mapping (most common cause: wrong padding, wrong scale, wrong endianness, wrong sign nibble).
- Re-verify against the original hex dump from step 2.

### 7. Iterate until clean

Repeat until `cmp` is silent and any aggregated totals (counts, sums) match the reference program's report output.

## Common pitfalls

- **Line endings on Windows**: GnuCOBOL on Linux writes LF; if the reference runs on Windows it may write CRLF — normalize before comparing.
- **Trailing space stripping**: Python text-mode reads/writes may strip trailing spaces; always use binary mode for fixed-length records.
- **COMP-3 sign nibble**: `0xC` = positive, `0xD` = negative, `0xF` = unsigned — Python has no built-in, decode by hand.
- **REDEFINES**: only one variant is live per record; choose the correct one based on the COBOL control flow.
- **Edited fields** (`PIC ZZZ,ZZ9.99`): output formatting, not storage — replicate with Python format strings only when writing report output, not the underlying file.