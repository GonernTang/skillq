---
name: sqlite-recovery
description: Recover records from a SQLite database file whose 100-byte database header is missing or corrupt but whose B-tree leaf pages (page type 0x0D) remain intact. Manually parses the B-tree page format, decodes varint-encoded cell metadata, interprets SQLite serial type codes, and reconstructs rows without relying on the sqlite3 CLI or library.
---

# SQLite Recovery from Truncated / Headerless Files

When a SQLite database file is truncated, partially overwritten, or stripped of its 100-byte header, the `sqlite3` library and CLI will refuse to open it (the magic string `SQLite format 3\0` and the page-size / page-count fields are gone). However, the B-tree leaf pages themselves are usually self-contained: each page carries everything needed to read its rows. You can recover records by parsing the raw page bytes directly.

## When to use this skill

- The file starts mid-stream (no `SQLite format 3\0` magic), or `sqlite3` returns `file is not a database`.
- You can see table-shaped data when running `strings` on the file.
- Page type byte `0x0D` (table B-tree leaf) is present at the start of the data region.

## Recovery procedure

### 1. Verify the page type

The very first byte of a B-tree leaf page (after the database header, which lives only at page 1) is the page type. For a table leaf page it must be `0x0D`:

- `0x0D` — table leaf (rows live here) ✅ recoverable
- `0x0A` — table interior (contains child pointers, not rows)
- `0x05` — freelist trunk
- `0x02` — index interior
- `0x0A` / `0x0D` variants for index leaves

If you only have `0x0A` or `0x02`, walk the tree: read the child-page pointers and recurse until you find leaves.

### 2. Parse the page header (offsets 1–7)

The 8-byte page header that follows the page type byte contains, in order:

| Offset | Size | Field |
|--------|------|-------|
| 1 | 2 bytes (big-endian) | First freeblock offset (0 if none) |
| 3 | 2 bytes (big-endian) | Number of cells on the page |
| 5 | 2 bytes (big-endian) | Start of cell-content area |
| 7 | 1 byte | Number of fragmented free bytes |

The cell count tells you how many records this page holds.

### 3. Walk the cell pointer array (offset 8 onward)

Immediately after the page header is an array of 2-byte big-endian pointers, one per cell. Each pointer is the byte offset (from the start of the page) of that cell's payload. There are exactly `number_of_cells` pointers.

### 4. Decode each cell

For each pointer, jump to that offset in the page and read:

1. **Payload length** — varint
2. **Rowid** — varint
3. **Record header length** — varint (this is the size of the header that follows, not the payload)
4. **Serial-type varints** — one per column, until the cumulative length equals the record-header length

**Varint encoding**: 1–9 bytes. For each byte, the high bit indicates continuation (1 = more bytes follow, 0 = last byte). Little-endian: the first byte holds the least-significant 7 bits, the next byte the next 7 bits, etc.

### 5. Decode each column by its serial type code

The data payload follows the record header. Use this table:

| Code | Meaning |
|------|---------|
| 0 | NULL |
| 1 | INT8 — 1 byte, signed |
| 2 | INT16 — 2 bytes big-endian, signed |
| 3 | INT24 — 3 bytes big-endian, signed |
| 4 | INT32 — 4 bytes big-endian, signed |
| 5 | INT48 — 6 bytes big-endian, signed |
| 6 | INT64 — 8 bytes big-endian, signed |
| 7 | FLOAT64 — 8 bytes, IEEE 754 big-endian |
| 8 | constant 0 (no bytes consumed) |
| 9 | constant 1 (no bytes consumed) |
| 10, 11 | reserved (error if seen) |
| ≥ 12, even | TEXT — `(code - 12) / 2` bytes, UTF-8 |
| ≥ 13, odd | BLOB — `(code - 13) / 2` bytes |

Advance the payload cursor by the column's size for each non-constant type.

### 6. Assemble and export

Group the decoded columns into a record (list/dict), repeat for every cell on every leaf page, and write the result to JSON, CSV, or whatever downstream consumer needs it.

## Tips and pitfalls

- **Page size** — for the first page of the file (which is also a leaf), the page size is normally 4096, but it could be 512, 1024, 2048, 32768, or 65536. If the header is gone, try 4096 first (most common) and look for the next `0x0D` byte if rows look truncated.
- **Big-endian everywhere** except varints — easy to mix up.
- **Cell pointer array length is variable** — it depends on cell count, not on a fixed offset. Compute it as `8 + 2 * number_of_cells` to find where the unallocated space starts.
- **Interior pages are not leaf pages** — `0x0A` means you must recurse into child pages to find data.
- **The record header length includes the serial-type varints themselves** but not the rowid or payload-length varints at the start of the cell.
- **Schema is not in the page** — without the database header (and the `sqlite_schema` table), you only have column ordinals and serial types, not column names. You'll need to map them by context (or recover the schema separately) for human-readable output.

## Minimal Python skeleton

```python
def read_varint(buf, i):
    n = 0
    for shift in range(0, 64, 7):
        b = buf[i]; i += 1
        n |= (b & 0x7F) << shift
        if not (b & 0x80): return n, i
    raise ValueError("varint too long")

def decode_serial(t, buf, i):
    if t == 0: return None, i
    if t == 1: return int.from_bytes(buf[i:i+1], "big", signed=True), i+1
    if t == 2: return int.from_bytes(buf[i:i+2], "big", signed=True), i+2
    if t == 3: return int.from_bytes(buf[i:i+3], "big", signed=True), i+3
    if t == 4: return int.from_bytes(buf[i:i+4], "big", signed=True), i+4
    if t == 5: return int.from_bytes(buf[i:i+6], "big", signed=True), i+6
    if t == 6: return int.from_bytes(buf[i:i+8], "big", signed=True), i+8
    if t == 7: return struct.unpack(">d", buf[i:i+8])[0], i+8
    if t == 8: return 0, i
    if t == 9: return 1, i
    if t >= 12 and t % 2 == 0:
        n = (t - 12) // 2; s = buf[i:i+n].decode("utf-8", "replace"); return s, i+n
    if t >= 13 and t % 2 == 1:
        n = (t - 13) // 2; b = bytes(buf[i:i+n]); return b, i+n
    raise ValueError(f"bad serial type {t}")

def recover_page(page):
    assert page[0] == 0x0D, "not a table leaf page"
    n_cells = int.from_bytes(page[3:5], "big")
    records = []
    for k in range(n_cells):
        ptr = int.from_bytes(page[8 + 2*k : 10 + 2*k], "big")
        i = ptr
        _, i = read_varint(page, i)        # payload length
        rowid, i = read_varint(page, i)
        hdr_len, i = read_varint(page, i)
        hdr_end = i + hdr_len
        types = []
        while i < hdr_end:
            t, i = read_varint(page, i); types.append(t)
        cols = []
        for t in types:
            v, i = decode_serial(t, page, i); cols.append(v)
        records.append({"rowid": rowid, "cols": cols})
    return records
```

Iterate this over every leaf page found in the file; concatenate the records; export as JSON.