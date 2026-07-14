---
name: mailman-postfix-setup
description: Recover data from SQLite databases when the WAL file is corrupted or XOR-encrypted, without relying on pattern inference.
---

# SQLite WAL Recovery (Encrypted / Corrupted)

## ⚠️ Guard-rail

**Never query the database before backing up the WAL file.**  
Any SQLite read will reset/truncate an invalid WAL and destroy the data.

## 1. Backup

Make a byte‑level copy of the WAL file *before* any SQLite operation:

```bash
cp main.db-wal main.db-wal.backup
```

If the database itself is intact, also back it up:

```bash
cp main.db main.db.backup
```

## 2. Detect encryption

Read the first 4 bytes of the WAL file:

```bash
xxd -l 4 main.db-wal
```

A valid SQLite WAL header (big‑endian) starts with `0x377f0682`.  
If the bytes are different (e.g. `0x753d44c0`), the WAL has been XOR‑encrypted.

## 3. Determine XOR key

The XOR key is the difference between the observed first byte and `0x37`:

```bash
# Example: first byte = 0x75 → key = 0x75 XOR 0x37 = 0x42
python3 -c "print(hex(0x75 ^ 0x37))"
```

If multiple bytes are available, verify the key by checking that `(observed_byte XOR key)` matches the known magic.

## 4. Decrypt the WAL

Use Python to XOR every byte of the WAL with the key and write the result to a new file:

```python
key = 0x42
with open('main.db-wal', 'rb') as f:
    data = f.read()
decrypted = bytes(b ^ key for b in data)
with open('main.db-wal.decrypted', 'wb') as f:
    f.write(decrypted)
```

## 5. Restore and query

Replace the encrypted WAL with the decrypted one, then query normally:

```bash
mv main.db-wal.decrypted main.db-wal
sqlite3 main.db "SELECT * FROM your_table;"
```

SQLite will now see a valid WAL and apply all committed transactions.

## 6. If the WAL has been reset/truncated

If the WAL file was already destroyed (zero bytes), but you have a hex dump taken before destruction:

1. Decrypt the captured hex dump using the same XOR key.
2. Parse the decrypted hex dump to reconstruct WAL frames (each frame is 4096 bytes of page data plus a 24‑byte header).
3. Write the reconstructed frames into a new WAL file (starting with the correct 32‑byte header) or directly extract page images and attach them to the database.

## 7. Fallback – database only

If the WAL is truly lost and no backup exists, query the main database file alone.  
**Do not invent records based on patterns or alphabetic progression** – only real, recoverable data is valid.

## Troubleshooting

- **"No such table"** – the encrypted WAL was destroyed before decryption; restore from backup.
- **XOR key mismatch** – re‑check the first 4 bytes; if the magic still differs after XOR, the file may be encrypted with a different algorithm.
- **SQLite error "file is not a database"** – ensure the decrypted WAL has the 4‑byte magic `0x377f0682` at offset 0.