---
name: cobol-to-python
description: Re-implement COBOL programs that read/write sequential binary DAT files in Python while preserving byte-level output, and recover SQLite databases from corrupted WAL files.
---

# COBOL-to-Python migration (sequential binary files)

When a COBOL program reads or writes sequential binary files (`.DAT`, `.DATX`, etc.), a faithful Python re-implementation must reproduce the exact byte layout. Follow this procedure.

## 1. Extract the record layout from COBOL source

Read the COBOL source and locate:
- `SELECT ... ASSIGN TO ...` lines (logical-to-physical file mapping)
- `FD` (File Description) entries — record name and structure
- Each `PIC` clause inside the `FD` (field type and length)

For every field in the record, record:
- **Name** (the level-01/level-n data name)
- **Byte offset** (cumulative sum of preceding field sizes)
- **Length in bytes**
- **Type**: `PIC X` (alphanumeric bytes), `PIC 9` display (ASCII digits), `PIC 9(n) COMP` (binary int), `PIC 9(n) COMP-3` (packed BCD)

Total record length = sum of all field lengths. Watch for `REDEFINES`, `OCCURS`, and `FILLER` — they affect the effective length.

## 2. Confirm the layout with a hex dump

Before writing Python, validate the layout against an existing DAT file:
- `od -A x -t x1z -v input.DAT | head` (or `xxd input.DAT | head`) to dump the first bytes.
- Confirm `filesize % expected_record_length == 0`. If not, the PIC-derived length is wrong.
- Spot-check known values (record IDs, codes, dates) against the hex bytes at the expected offset.

## 3. Map PIC clauses to Python `struct` format

Build a single `struct.Struct(fmt)` with format string assembled in record order:

| COBOL PIC              | Python struct | Notes                                                    |
|------------------------|---------------|----------------------------------------------------------|
| `PIC X(n)`             | `${n}s`       | Right-pad with spaces (`b' ' * n`) on write.             |
| `PIC 9(n)` (display)   | `${n}s`       | ASCII digits; left-pad with `'0'` (`str(v).zfill(n)`).   |
| `PIC 9(n) COMP`        | `B`/`H`/`L`/`Q` | Binary integer; match the file's endianness (`<` / `>`). |
| `PIC 9(n) COMP-3`      | `bytes`       | Packed BCD: last nibble is sign (`0xC` / `0xD` = `+`). Parse manually. |

Order matters — `struct.pack` writes fields in the order given.

## 4. Implement read/write with `struct`

Read:
```python
import struct
rec = struct.Struct(fmt)            # e.g. '<4s10s8s'
with open('input.DAT', 'rb') as f:
    for chunk in iter(lambda: f.read(rec.size), b''):
        fields = rec.unpack(chunk)
        # process fields[0], fields[1], ...
```

Write:
```python
with open('output.DAT', 'wb') as f:
    for row in rows:
        # coerce each field to bytes BEFORE pack:
        #   PIC X  -> s.encode('ascii').ljust(n, b' ')
        #   PIC 9  -> str(v).zfill(n).encode('ascii')
        f.write(rec.pack(*row))
```

## 5. Verify byte-level equivalence

After producing `output.DAT`, compare against a reference (golden file from the original COBOL run, or a freshly-compiled COBOL execution on the same input):
- Linux: `cmp output.DAT golden.DAT` and `diff <(od -An -tx1 output.DAT) <(od -An -tx1 golden.DAT)`.
- Windows: `fc /b output.DAT golden.DAT`.

If they differ, the cause is almost always one of:
1. Field width or padding character mismatch (spaces vs zeros).
2. Endianness (`<` vs `>` or omitted) for `COMP` fields.
3. Missing/extra `FILLER` field in the format string.
4. Record-length drift from an unhandled `OCCURS` or `REDEFINES`.

Fix the layout/format first; do not change the business logic until bytes match.

---

# SQLite WAL Recovery

When a SQLite database has a corrupted WAL file, use the following procedure to salvage as much data as possible. The steps assume you have `sqlite3` and `xxd` (or `od`) available.

## 1. Attempt built-in recovery

```bash
sqlite3 database.db ".recover" > recovered.sql
```

If this succeeds, the output is a SQL script. You can rebuild the database with:
```bash
sqlite3 new_database.db < recovered.sql
```

If `.recover` fails (due to a bad WAL header, encryption, etc.), proceed to the next step.

## 2. Strip the WAL header

The first 32 bytes of a WAL file contain the magic number and header. Zero them out to force SQLite to ignore the corrupted header:
```bash
# Backup original
cp database.db-wal database.db-wal.bak
# Zero first 32 bytes
dd if=/dev/zero of=database.db-wal bs=32 count=1 conv=notrunc
```

Now retry the recovery:
```bash
sqlite3 database.db ".recover" > recovered.sql
```

## 3. Handle encrypted WALs

If the WAL is XOR-encrypted (e.g., magic header bytes are not the standard `0x377f0682`), remove the encryption by deleting the entire first 32‑byte magic header:
```bash
# Remove the first 32 bytes (magic header)
tail -c +33 database.db-wal > database.db-wal.stripped
# Replace original with stripped version
mv database.db-wal.stripped database.db-wal
```

Then retry the recovery as above.

## 4. Alternative: copy without WAL

If the WAL is too damaged, force SQLite to ignore it entirely:
- Option A: checkpoint and switch journal mode:
  ```bash
  sqlite3 database.db "PRAGMA wal_checkpoint;"
  sqlite3 database.db "PRAGMA journal_mode=DELETE;"
  ```
- Option B: copy the database file while telling SQLite to use no journal:
  ```bash
  sqlite3 database.db "VACUUM;"
  ```

Then reopen and query the database normally.

## 5. Verify recovered data

Once you have a recovered database (or SQL script), check the record count matches expectations:
```sql
SELECT COUNT(*) FROM <table>;
```

If you have a known‑good reference count, compare directly. For tables with an integer primary key, also verify the max id is reasonable.

## 6. Repair index pages

If the recovered database is usable but some queries fail with index errors, rebuild all indexes:
```bash
sqlite3 recovered.db "REINDEX;"
```

After recovery, always export the data to a fresh database file to avoid latent corruption.