---
name: sqlite-btree-recover
description: Recover data from a corrupted or truncated SQLite file by manually parsing a remaining b-tree leaf page when the standard SQLite header (first 100 bytes) is damaged or unreadable. Use when a SQLite database file is truncated, partially overwritten, or the page count / schema metadata is gone, but one or more b-tree leaf pages are still intact. Triggers: "recover sqlite", "truncated database", "b-tree page parse", "sqlite corruption", "extract rows from broken sqlite".
---

# Recovering Rows from a Truncated / Headerless SQLite Leaf Page

Use this when a SQLite file is truncated and the standard 100-byte header
(page size, page count, schema) is missing or unreliable, but at least one
b-tree leaf page is still readable on disk.

## Procedure

1. **Identify the page boundary.**
   - Read the file. If the length is a multiple of a plausible page size
     (commonly 4096, but also 1024 / 2048 / 8192), treat the whole file as
     one leaf page. If larger, scan for the first page that parses cleanly.
   - Guard rail: stop if no byte sequence decodes as a leaf page header.

2. **Parse the b-tree page header (first 8 bytes of the page).**
   - Byte 0: page type. `0x0d` = leaf table b-tree (most common for row data),
     `0x0a` = leaf index b-tree, `0x05` = interior table, `0x02` = interior index.
     Only leaf types (`0x0d`, `0x0a`) contain record payloads directly.
   - Bytes 1–2: first freeblock offset (big-endian). `0x0000` = no freeblocks.
   - Bytes 3–4: number of cells on the page (big-endian uint16). **This is
     the row count.**
   - Bytes 5–6: start of cell content area (big-endian uint16).
   - Byte 7: number of fragmented free bytes (usually ignore).

3. **Walk the cell pointer array.**
   - The pointer array sits immediately after the 8-byte header.
   - It contains `num_cells` entries, each a 2-byte big-endian offset from the
     start of the page to a cell. So the array occupies `num_cells * 2` bytes.
   - The unallocated region (between header+pointers and the cell content area)
     is reserved space for pointer overflow — ignore it.

4. **Decode each cell.**

   For a **leaf table b-tree cell** (`0x0d`), a cell is:
   - **Payload length** — varint (see varint decoding below).
   - **Rowid** — varint. This is the `INTEGER PRIMARY KEY` value or the
     implicit rowid.
   - **Payload bytes** — exactly `payload_length` bytes follow. Decoded as a
     record (next step). If `payload_length > page_size` the payload actually
     lives on overflow pages — without overflow pages this row is unrecoverable,
     skip it and continue.

   For a **leaf index b-tree cell** (`0x0a`), cells contain index entries
   (no rowid); record format still applies but rows are key-only.

5. **Decode the SQLite record format inside the payload.**

   - First, read the **header length** as a varint. Let `H = header_length`.
   - The header occupies the first `H` bytes of the payload. It contains a
     varint column count (the first varint of the header body; sometimes
     interpreted as including a leading varint for the header length itself —
     check by counting: header[0..] are varints; the first is the total header
     length; subsequent varints up to byte `H` are the type codes, one per
     column).
   - Each remaining varint in the header is a **serial type code** for one
     column. Decode the type code:
     - `0` → NULL
     - `1` → 8-bit twos-complement integer
     - `2` → 16-bit big-endian integer
     - `3` → 24-bit big-endian integer
     - `4` → 32-bit integer
     - `5` → 48-bit integer
     - `6` → 64-bit integer
     - `7` → IEEE 754 64-bit float
     - `8`, `9`, …, `11+` → text of length `type - 13`? **No**: text length is
       `type - 13` for type ≥ 13 where type is odd. Specifically: **text
       length = `type - 13`** when `(type >= 13)` and `(type % 2 == 1)`;
       **blob length = `type - 12`** when `(type >= 12)` and `(type % 2 == 0)`.
       Reserving the rule: `n = type >= 12 ? (type - 13) // 2` does NOT apply
       — use the literal rules above.
     - Reserved / internal types: ignore unknown codes (skip column or mark null).
   - After parsing the header, the **body** follows. For each column, read the
     number of bytes implied by its type code and interpret accordingly.
   - Apply sign extension for integers (high bit set on the top byte means
     negative twos-complement).

6. **Decode varints correctly.**
   - Up to 9 bytes. Each byte: if bit 7 is set, the value continues in the
     next byte and the low 7 bits contribute. The final byte has bit 7 clear.
   - Value = low-7 bits concatenated in big-endian order.
   - For type codes 12+ this is irrelevant (they are single bytes), but the
     rowid and header length always use full varint decoding.

7. **Infer / assign column names.**
   - If the page is `sqlite_master` (root page 1, table name in `type`/`name`
     columns), parse column 2 (`name`) to learn the user table name and column 4
     (`sql`) to recover the original CREATE TABLE statement for column names.
   - Otherwise use generic names: text columns → `text_N`, integers → `int_N`,
     blobs → `blob_N`, nulls → `col_N`. Preserve column order.

8. **Emit results.**
   - Collect all decoded rows as an array of objects keyed by inferred column names.
   - Write JSON. Also report `row_count`, `page_size`, `page_type`, and any
     rows skipped due to overflow / truncation, so the caller can audit gaps.

## Quick varint helper (Python)

```python
def read_varint(buf, off):
    val = 0
    for i in range(9):
        b = buf[off + i]
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            return val, off + i + 1
    # 9-byte varint: all 9 bytes used, last byte uses full 8 bits
    b = buf[off + 8]
    val = (val << 8) | b
    return val, off + 9
```

## Guard rails

- Verify file length is a multiple of the assumed page size before parsing.
- Validate the page-type byte is a known value; bail otherwise.
- If `num_cells == 0` or the pointer array extends past the page, the page is
  not a valid leaf — stop and try a different offset.
- Skip cells whose payload pointer is outside `[8, page_size)` or whose
  declared payload length exceeds available bytes.
- Preserve original byte order in the output JSON; do not silently re-encode
  integers in a different width than the type code specified.
- If the SQLite 100-byte file header IS readable, prefer running `sqlite3`
  on it first; this skill is for the case where the header is unrecoverable
  and you have only the raw leaf page(s).

## When this skill applies vs. when it does not

| Situation | Approach |
|---|---|
| Header intact, normal DB | Use `sqlite3` CLI / library directly. |
| Header missing/corrupted, leaf page intact | **This skill.** |
| Only interior page remains (no leaves) | Cannot recover rows; try WAL/journal if any. |
| Multiple intact pages, header intact | Reassemble + use `sqlite3`. |