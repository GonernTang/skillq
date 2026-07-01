---
name: sqlite-wal-recovery
description: Guide for SQLite WAL recovery and corrupted WAL scenarios. Use when a SQLite database's write-ahead log (WAL) file is missing, empty, or appears to have been consumed by a checkpoint, and the main database file shows only base page data without recent transactions. Triggers include "WAL gone", "missing wal file", "recover WAL", "sqlite-wal", "checkpoint consumed WAL", "WAL recovery", "corrupted WAL".
---

# SQLite WAL Recovery

When a SQLite database in WAL journal mode loses its `*-wal` sidecar file (often consumed silently by a passive or full checkpoint during a read), the main `.db` file still contains *all* committed data — checkpointing merges WAL frames into the main database before truncating the WAL. The risk is treating missing WAL as "data lost" instead of "WAL state needs reconstruction".

## Diagnostic checklist

Run these BEFORE declaring the WAL unrecoverable:

1. **Run `PRAGMA wal_checkpoint(TRUNCATE);`** on a *copy* of the database. If it succeeds, the WAL was empty/already checkpointed — your data is in the main file. Do not skip this even if the WAL file does not exist on disk.
2. **Inspect `PRAGMA journal_mode`** and `PRAGMA wal_checkpoint(PASSIVE)` to confirm the journal mode and confirm whether frames remain unmerged.
3. **Check for sibling `-shm` and `-wal` files** in the same directory. The `-shm` shared-memory file may hold index information even if `-wal` is gone. Recover from backup or filesystem snapshot before attempting reconstruction.
4. **Verify integrity** with `PRAGMA integrity_check;` and `PRAGMA page_count;`. If integrity passes and page_count matches expectations, the base pages contain the truth — query the tables directly instead of trying to "replay" the WAL.

## Recovery procedure

1. **Stop all writers** to the database. Take a filesystem-level copy before any recovery attempt — recovery is destructive.
2. **Probe WAL state**: open the DB read-only, run `PRAGMA wal_checkpoint(PASSIVE)` and inspect any returned `(busy, log_frames, checkpointed_frames)` values. `log_frames == 0` means checkpoint already consumed everything.
3. **Reconcile against the main DB**: query the affected tables. If the rows expected to be in the WAL are *already present*, no recovery is needed — the WAL had been merged.
4. **If frames are missing from the main DB** (rare — implies the WAL was truncated mid-checkpoint): attempt recovery in this order:
   a. Restore `-wal` and `-shm` from the most recent backup/snapshot.
   b. Open with `sqlite3 db.sqlite ".recover"` (CLI) which scans free pages, the WAL, and the rollback journal for recoverable content.
   c. Run `PRAGMA wal_checkpoint(FULL);` to flush any recovered frames.
5. **Last resort — hex/structure parsing**: only if `sqlite3 .recover` yields nothing, parse the raw `.db` file by walking B-tree pages, reading cell payloads from leaf pages per the SQLite file format spec. Extract strings/text from `sqlite_master` to recover schema, then iterate user tables. This is slow and error-prone — record exactly which pages were parsed and which rows were reconstructed.

## Stop signal

- If `PRAGMA integrity_check` reports `ok` on the main DB and the rows you expected from the WAL are present in queries → **stop**: the WAL was already checkpointed, no recovery procedure is needed. Do not enter a hex-dump spiral on healthy data.
- If you have attempted 2 distinct recovery paths (`.recover` CLI + page-level reconstruction) and neither yields the missing rows → **stop and surface the gap** to the user with a list of which pages were inspected and which tables remain incomplete. Do not loop on the same parser with minor variations — the SQLite file format is the source of truth, not your reconstruction logic.
- If a fresh `sqlite3 .recover` scan returns 0 rows but integrity_check is `ok` → treat the database as complete; the "missing" WAL data was never written or was already merged.

## Common pitfalls

- **Treating missing `-wal` as data loss.** A checkpointed WAL is *correct* state, not corruption.
- **Writing to the DB before recovery.** Any write may overwrite free pages that still hold old data; always recover from a copy.
- **Trusting `PRAGMA wal_checkpoint(TRUNCATE)` on a damaged file** to fail loudly — it often silently succeeds on truncated/empty WALs. Always check the returned frame counts.
- **Skipping `sqlite3 .recover`.** This CLI command is purpose-built for this case and walks free pages, WAL, and journal files in one pass. It must be attempted before any custom parser.