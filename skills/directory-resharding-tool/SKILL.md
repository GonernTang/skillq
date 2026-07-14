---
name: directory-resharding-tool
description: Build a CLI tool that redistributes files from an arbitrary directory tree into a balanced "shard" layout (round-robin across shards with a per-shard file cap), preserving a manifest for lossless reverse operation. Use when a flat file tree must be reshaped into predictable, balanced subdirectories while keeping round-trip restorability verifiable by checksums.
---

# Directory Resharding Tool

## Goal

Reshape an arbitrary input directory of files into a balanced output directory where each subdirectory holds at most `N` files, distributed round-robin across `shard_XXXX` folders. The operation must be reversible from a JSON manifest, with bit-for-bit integrity checked by SHA-256.

## Parameters (defaults)

- `MAX_FILE_SIZE` = 15 MB — refuse files above this.
- `MAX_FILES_PER_DIR` = 30 — when a directory would exceed this, spawn another shard.
- Shard naming: zero-padded `shard_0000`, `shard_0001`, …
- Manifest path: `<output>/.reshard_manifest/manifest.json`.

## Compress procedure

1. **Walk & collect.** Recurse the input, building a list of `(relative_path, source_absolute_path)` pairs. Skip the manifest directory itself if re-running.
2. **Validate.** For each file, assert `size <= MAX_FILE_SIZE` — fail loudly on the first violator. Also fail on missing input directory or unreadable file.
3. **Build shard plan.** Initialize `num_shards = ceil(total_files / MAX_FILES_PER_DIR)`. Walk the list assigning each file to `shard[(index % num_shards)]`. Zero-pad the shard name to width 4.
4. **Copy & record.** For each planned placement:
   - Create the shard directory.
   - Handle **basename collisions**: track used basenames per shard; on collision append `_1`, `_2`, … to the new copy's name (do not mutate the *original* relative path stored in the manifest).
   - `shutil.copy2` the file into the shard.
   - Record `{ "original_relpath": "<as-walked>", "new_relpath": "shard_XXXX/possibly_renamed_name" }` in the manifest.
5. **Write manifest.** Persist `manifest.json` (formatted/indented for diffability) plus a `meta` block with `total_files`, `num_shards`, `max_files_per_dir`, `max_file_size`, and tool version.
6. **Verify round-trip.** As a self-check before declaring success, re-walk the manifest: for each entry, recompute SHA-256 of both source and placed copy; abort if any mismatch.

## Decompress procedure

1. **Locate manifest.** Require `<root>/.reshard_manifest/manifest.json`. If missing, abort with a clear error suggesting a re-run of compress.
2. **Restore.** Read entries; `os.makedirs` each parent of the original relative path; `shutil.copy2` the shard copy onto the original path (overwriting if it exists).
3. **Cleanup.** Walk shard directories: delete every file recorded in the manifest, then `os.rmdir` empty shard directories (skip-if-not-empty pattern). Finally `shutil.rmtree` the entire manifest directory.
4. **Verify.** Re-walk the restored tree by re-reading the source-list from the manifest's original_relpaths; recompute SHA-256 of each restored file and compare against the source checksum stored in `meta` if available; otherwise compare against the original input tree before deletion.

## Collision-rule detail

When two source files `a/foo.txt` and `b/foo.txt` would land in the same shard, only the second write needs renaming to `foo_1.txt`. The manifest entry for that file records `new_relpath: "shard_0001/foo_1.txt"` while `original_relpath` remains the unmodified `b/foo.txt`, so decompression restores correctly.

## CLI shape

- `python tool.py compress <input_dir> <output_dir> [--max-files-per-dir N] [--max-file-size BYTES]`
- `python tool.py decompress <output_dir>`
- Use `argparse` with subcommands; exit codes: `0` success, `1` validation/runtime error, `2` manifest mismatch.

## Implementation constraints

- **Standard library only**: `os`, `shutil`, `json`, `hashlib`, `argparse`, `pathlib`. No third-party deps.
- Always `os.makedirs(..., exist_ok=True)` for parent dirs.
- Capture metadata via `shutil.copy2` (preserves mtime/perms) — not `copy`.
- Read files in **chunked** mode when hashing (e.g., 64 KB blocks) to avoid loading huge files into memory.
- Make the idempotency check: if `<output>/.reshard_manifest/manifest.json` already exists, refuse to overwrite unless `--force` is passed.

## Test cases to include

1. **Empty input** → produces empty manifest and an output dir with zero shards.
2. **Round-trip with checksum verification** on a 200-file synthetic tree using mixed text/binary content.
3. **Subdirectory inputs** — files nested 3+ levels deep preserve their relative paths through compression and decompression.
4. **Collision scenario** — two source paths with identical basenames in different subdirs collide inside a shard and trigger the `_1` rename.
5. **Oversized file** — file exceeding `MAX_FILE_SIZE` is rejected before any copy occurs, no partial output written.
6. **Missing manifest** — decompression of a non-resharded directory produces a clear, actionable error.
7. **Idempotency** — running compress twice refuses the second run without `--force`.

## Failure modes & messages

- "Input directory does not exist: …" — check path.
- "File <relpath> exceeds max size (<bytes> > <limit>)." — split input or raise limit.
- "Manifest not found at <path>; nothing to decompress." — wrong root or already restored.
- "Checksum mismatch for <relpath>: src=<…> dst=<…>." — investigate before deleting originals.

## When NOT to use this skill

- The input is already flat and balanced (no reshaping needed).
- Files are larger than 15 MB on average — raise the cap or chunk the data first.
- The downstream consumer doesn't support the shard layout — confirm before resharding.