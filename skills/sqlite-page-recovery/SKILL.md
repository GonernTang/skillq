---
name: sqlite-page-recovery
description: Recover data from a single SQLite b-tree page when the database header is missing or truncated. Use when a .db/.sqlite/.sqlite3 file has lost its 100-byte header but still contains a usable b-tree leaf page (e.g., after truncation, partial corruption, or header overwrite).
---

# Recover Data from a Single SQLite B-Tree Page

When a SQLite database file is truncated or its 100-byte header is wiped but a single b-tree leaf page survives intact, you can parse that page directly and recover the rows without needing the SQLite library.

## When This Procedure Applies

Use this when:
- The file's first byte is `0x0d` (table leaf page) — confirms it's a usable leaf.
- The 100-byte database header is missing/corrupted, so `sqlite3_open` fails.
- Only **one page** worth of data matters (overflow / multi-page trees are out of scope).

If the file's first byte is `0x00` or `0x05` it is a b-tree interior page, not a leaf — recovery here only covers leaf pages. If you see `SQLite format 3\0` at offset 0 the header is intact and you should just open the file normally; this skill is the fallback.

## Step 1 — Verify the Page Type

Read byte 0. `0x0d` = table b-tree leaf page. Stop if it is not `0x0d`.

## Step 2 — Parse the 8-Byte Page Header

Starting at offset 0:
- Byte 0: page type flag (must be `0x0d`).
- Byte 1: offset to first freeblock (big-endian u16; ignore unless freelist recovery is needed).
- Bytes 2–3: **number of cells** (big-endian u16).
- Bytes 4–5: start of cell-content area (big-endian u16).
- Byte 6: number of fragmented free bytes.
- Byte 7 (only if leaf): offset to right-child pointer; otherwise `0`.

Let `n_cells = u16_be(page[2:4])` and `content_start = u16_be(page[4:6])`.

## Step 3 — Walk the Cell Pointer Array

For `i` in `0..n_cells`, read a big-endian u16 at offset `8 + 2*i` → that is the byte offset of cell `i` within the page. Cells grow upward from `content_start`; the pointer array grows downward from offset 8.

## Step 4 — Parse Each Cell

For each cell offset `p`:

1. **Payload length** — read a varint at `p`. (Varint = 1–9 bytes; for each byte, if high bit is set, continue; final byte's value is the low 7 bits. Value uses lower 7 bits of each of up to 9 bytes, little-endian.)
2. **Rowid** — read a varint immediately after the payload-length varint.
3. **Payload** — that many bytes.
4. Inside the payload: read a varint **header size** (length of the record-header area).
5. After the header size, read N header bytes where N = header_size. These bytes are themselves a sequence of varints — one **serial type** per column.
6. Then the column values follow, in the order their serial types appeared.

## Step 5 — Decode Serial Type Codes

SQLite record format serial types:

| Serial type | Meaning | Bytes to read |
|---|---|---|
| 0 | NULL | 0 |
| 1 | 8-bit twos-complement int | 1 |
| 2 | 16-bit BE twos-complement int | 2 |
| 3 | 24-bit BE twos-complement int | 3 |
| 4 | 32-bit BE twos-complement int | 4 |
| 5 | 48-bit BE twos-complement int | 6 |
| 6 | 64-bit BE twos-complement int | 8 |
| 7 | IEEE 754 float (big-endian) | 8 |
| 8 | integer literal 0 | 0 |
| 9 | integer literal 1 | 0 |
| 10, 11 | reserved/internal | 0 |
| N ≥ 12, even | BLOB of length `(N-12)/2` | `(N-12)/2` |
| N ≥ 13, odd | TEXT of length `(N-13)/2` | `(N-13)/2` |

For numeric types 1–6, sign-extend if the top bit of the highest byte is set (e.g., for a 1-byte value `0xff`, treat as `-1`; for a 4-byte value with high bit set, subtract `2**32`).

For TEXT, decode the bytes as UTF-8.

## Step 6 — Assemble and Emit

For each cell, build a dict (or list, if the schema is unknown — emit columns as `[col_0, col_1, ...]` in header order). Write the array of records as JSON. Without a schema, a list-of-lists preserves the column order even when names are lost.

## Reference Implementation Sketch (Python)

```python
import struct, json

def varint(buf, i):
    val = 0
    for shift in range(0, 64, 7):
        b = buf[i]; i += 1
        val |= (b & 0x7f) << shift
        if not (b & 0x80): return val, i
    return val, i  # malformed past 9 bytes — clamp

def decode_column(buf, i, t):
    if t == 0: return None, i
    if t == 1: return struct.unpack('>b', buf[i:i+1])[0], i+1
    if t == 2: return struct.unpack('>h', buf[i:i+2])[0], i+2
    if t == 3: # 24-bit: read as 32-bit with leading sign byte
        b = buf[i:i+3]
        n = int.from_bytes(b, 'big', signed=False)
        if n & 0x800000: n -= 0x1000000
        return n, i+3
    if t == 4: return struct.unpack('>i', buf[i:i+4])[0], i+4
    if t == 5: # 48-bit
        b = buf[i:i+6]
        n = int.from_bytes(b, 'big', signed=False)
        if n & 0x800000000000: n -= 0x1000000000000
        return n, i+6
    if t == 6: return struct.unpack('>q', buf[i:i+8])[0], i+8
    if t == 7: return struct.unpack('>d', buf[i:i+8])[0], i+8
    if t == 8: return 0, i
    if t == 9: return 1, i
    if t >= 12 and t % 2 == 0:
        n = (t - 12) // 2
        return bytes(buf[i:i+n]), i+n
    if t >= 13:
        n = (t - 13) // 2
        return bytes(buf[i:i+n]).decode('utf-8', 'replace'), i+n
    raise ValueError(f"unknown serial type {t}")

def parse_page(page):
    assert page[0] == 0x0d, "not a table leaf page"
    n_cells   = struct.unpack('>H', page[2:4])[0]
    # content_start = struct.unpack('>H', page[4:6])[0]
    rows = []
    for c in range(n_cells):
        ptr = struct.unpack('>H', page[8 + 2*c: 10 + 2*c])[0]
        payload_len, p = varint(page, ptr)
        # rowid, _ = varint(page, p)  # uncomment if you want rowids
        # p = _p
        _, p = varint(page, p)  # skip rowid
        hdr_size, p = varint(page, p)
        hdr_end = p + hdr_size
        types = []
        while p < hdr_end:
            t, p = varint(page, p); types.append(t)
        cols = []; i = hdr_end
        for t in types:
            v, i = decode_column(page, i, t); cols.append(v)
        rows.append(cols)
    return rows

with open('truncated.db', 'rb') as f:
    page = f.read()  # for one-page files; otherwise slice the right page
print(json.dumps(parse_page(page), indent=2, default=str))
```

## Caveats

- Works on a **single page** only. Overflow pages, interior pages, and schema recovery from `sqlite_master` require walking the full b-tree.
- Schema (column names, types) is **not** recoverable from a single page. Output columns positionally unless you also have an intact `sqlite_master` page.
- `WITHOUT ROWID` tables, virtual tables, and indexes store data with a different format (key bytes prepended to the record) — adjust the per-cell parser accordingly.
- Verify output: spot-check a known row against the original application if possible.