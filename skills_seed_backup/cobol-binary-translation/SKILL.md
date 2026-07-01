---
name: cobol-binary-translation
description: Translate COBOL programs that read or write fixed-length binary sequential files to a modern language (Python, Java, Go, etc.). Use when modernizing a COBOL program whose FILE SECTION declares records with PIC X / PIC 9 clauses and you need to reproduce byte-exact I/O — space-padded ASCII strings, ASCII-digit numerics, and the fixed record length — using binary mode plus struct or byte slicing.
---

# COBOL Fixed-Length Binary File Translation

## When to use

The COBOL program opens a file as `ORGANIZATION IS SEQUENTIAL` (or just `FILE STATUS`-driven sequential) and its `FILE SECTION` defines records made of `PIC X` / `PIC 9` fields with no `USAGE IS COMP*` clause, or with `USAGE IS COMP` whose byte order you can pin down. The task is to reproduce the same on-disk bytes from a non-COBOL program.

## Procedure

### 1. Decode the COBOL FILE SECTION

For every `FD` and its `01` record, list each elementary field with its `PIC` clause and compute its byte width:

- `PIC X(n)` → n bytes, ASCII, **right-padded with spaces** (`x'20'`) when the value is shorter.
- `PIC 9(n)` → n bytes, **ASCII digit characters** — the on-disk form of 42 in `PIC 9(6)` is the literal six-byte string `000042`, not a binary integer.
- `PIC S9(n)` (display / no `USAGE`) → sign encoded by a separate `SIGN` clause: `SIGN TRAILING SEPARATE` adds one extra byte holding `+` or `-`; `SIGN TRAILING` overpunches the sign into the last digit's high nibble.
- `PIC 9(n)V9(m)` → no decimal point is stored; the `V` is virtual. Keep the digit count `n+m` and scale at the application layer.
- `USAGE IS COMP` / `BINARY` → true binary integer, **big-endian by default on mainframe COBOL**; width is `ceil((n+1)/2)` bytes for odd-digit values, `n/2` for even, with a halfword/byte sign convention. Only treat as ASCII digits if no `USAGE` is present.
- `FILLER`, `REDEFINES`, and `OCCURS` (fixed) all occupy real bytes — include them in the offset math, do not skip.

Sum the widths → that is `RECORD_LENGTH`, the fixed chunk size for I/O.

### 2. Open in binary mode

- **Python:** `open(path, "rb")` / `"wb"`. No text mode. No newline handling.
- **Java:** `DataInputStream` / `DataOutputStream` over `FileInputStream` / `FileOutputStream`. Use `readFully(byte[])` sized to `RECORD_LENGTH`.
- **Go:** `os.OpenFile(..., os.O_RDONLY, 0)` and `binary.Read` with a fixed-size struct, or manual `io.ReadFull`.
- **C/C++:** `fopen(..., "rb")` and `fread(buf, RECORD_LENGTH, 1, fp)`.

### 3. Sequential read/write loop

```
record_len = sum of PIC widths
with open(path, "rb") as f:
    while True:
        chunk = f.read(record_len)
        if len(chunk) < record_len:
            break           # EOF (or unexpected short record — log and decide)
        # parse fields from chunk at known offsets
```

For output, build each record as a `bytearray` of exactly `record_len`, populate fields at their offsets, then `f.write(buf)`. **Do not** insert newlines, separators, or length prefixes.

### 4. Field-level encoding helpers (Python)

```python
def read_pic_x(buf, off, n):
    return buf[off:off+n].decode("ascii").rstrip()

def write_pic_x(buf, off, n, val):
    s = val.encode("ascii") if isinstance(val, str) else val
    buf[off:off+n] = s.ljust(n, b" ")

def read_pic_9(buf, off, n):
    return int(buf[off:off+n].decode("ascii"))  # preserves leading zeros semantically

def write_pic_9(buf, off, n, val):
    buf[off:off+n] = str(val).zfill(n).encode("ascii")
```

### 5. Verify byte-exact output

- Produce a known reference run from the COBOL program (if available) and from the translated program using the same input.
- Compare with `cmp` / `fc /b`, or hash each `record_len` block with SHA-256 and diff the digests record by record.
- Common causes of mismatch:
  1. `rstrip()` applied to a numeric field — strips legitimate trailing zeros.
  2. Output opens in text mode and writes `\n` — file becomes record-length + 1 per row.
  3. Off-by-one offset because a `FILLER` or `REDEFINES` was skipped in the count.
  4. `PIC S9` sign byte forgotten, or its position wrong (leading vs trailing).
  5. `USAGE IS COMP` field treated as ASCII — produces a single digit where the original has a 2- or 4-byte big-endian integer.

## Quick reference: PIC → storage

| PIC                                  | Bytes | On-disk example for value 42      | Notes                              |
|--------------------------------------|-------|-----------------------------------|------------------------------------|
| `PIC X(10)`                          | 10    | `b"hi         "` (spaces pad)    | Trailing spaces carry meaning.     |
| `PIC 9(6)`                           | 6     | `b"000042"`                      | Leading zeros required on output.  |
| `PIC S9(5) SIGN TRAILING SEPARATE`   | 6     | `b"00042+"`                      | One extra byte for sign.           |
| `PIC 9(3)V9(2)`                      | 5     | `b"00000"` for 0.00, `b"12345"` for 123.45 | Decimal is virtual, scale later.   |
| `PIC 9(4) USAGE IS COMP`             | 2     | big-endian int16                 | Not ASCII — binary integer.        |

## Pitfalls checklist

- [ ] File is **fixed-record**, not line-oriented. No newlines in or out.
- [ ] All PIC widths sum to exactly the chunk size you read; `FILLER`/`REDEFINES`/`OCCURS` count.
- [ ] Numeric fields preserved as ASCII digits, not silently converted to binary.
- [ ] Sign byte position and presence verified per `SIGN` clause.
- [ ] `USAGE IS COMP*` fields identified and stored in their actual binary form, with correct endianness.
- [ ] Output written in binary mode with the same record length and the same byte values.
- [ ] Round-trip test against a reference COBOL run passes at byte level.