---
name: dataset-resharding
description: Reshard a flat directory of files into a balanced tree of shards with per-directory entry limits and per-file size limits, using a manifest for roundtrip. Use when you need to redistribute a large flat file collection into a structured layout (e.g., for upload, distribution, or storage backends that cap entries per directory or bytes per file).
---

# Dataset Resharding

Procedure for splitting a flat directory of files into a balanced tree of shards while respecting two constraints: (a) a maximum number of entries per directory, and (b) a maximum size per shard file. The result is reversible via a manifest.

## When to use

- Source data is a flat directory of many files (no nested structure, or you want to flatten it).
- You need to redistribute it under constraints imposed by a downstream system: e.g. filesystem limits, object-store key counts per prefix, or upload size caps.
- You need a lossless, reversible roundtrip (the original directory tree must be reconstructible exactly).

## Procedure

### 1. Collect files

Recursively walk the source directory. For each file, record its **relative path** (relative to the source root) and **size**. Build an in-memory list of `[(rel_path, size, bytes)]` entries. Preserve the relative path verbatim — it is the reconstruction key.

### 2. Pack into shards (first-fit bin packing)

Pack files into a sequence of shards using a first-fit-decreasing approach:

- Sort entries by size descending. This reduces fragmentation.
- For each entry, place it into the first shard that has enough remaining capacity under the size limit.
- If the file is **larger than the size limit**, split it: emit multiple chunks of `size_limit` plus a final remainder chunk, each placed in a consecutive shard (in order). Record each chunk with a chunk index so the manifest can reassemble it.
- Shard 0 is reserved for the manifest itself (it will grow; reserve a reasonable amount of space, e.g. `size_limit`, and let the packer fill the rest normally).

Pseudocode:

```python
shards = [[]]  # list of shard contents (list of (rel_path, offset, length, chunk_idx))
shard_free = [size_limit]  # remaining bytes per shard

for rel_path, size, data in sorted(entries, key=lambda e: -e[1]):
    if size <= size_limit:
        placed = False
        for i in range(len(shards)):
            if shard_free[i] >= size:
                offset = size_limit - shard_free[i]
                shards[i].append((rel_path, offset, size, None))
                shard_free[i] -= size
                placed = True
                break
        if not placed:
            offset = 0
            shards.append([(rel_path, offset, size, None)])
            shard_free.append(size_limit - size)
    else:
        # split into chunks across consecutive shards
        chunk_idx = 0
        remaining = size
        while remaining > 0:
            take = min(remaining, size_limit)
            placed = False
            for i in range(len(shards)):
                if shard_free[i] >= take:
                    offset = size_limit - shard_free[i]
                    shards[i].append((rel_path, offset, take, chunk_idx))
                    shard_free[i] -= take
                    chunk_idx += 1
                    remaining -= take
                    placed = True
                    break
            if not placed:
                shards.append([(rel_path, 0, take, chunk_idx)])
                shard_free.append(size_limit - take)
                chunk_idx += 1
                remaining -= take
```

### 3. Assign shards to directory tiers (mixed-radix encoding)

The shard list (index 0 = manifest, 1..N = data) must be placed under a tree where each directory holds at most `entry_limit` entries. Use mixed-radix naming:

- **Root directory**: base = `entry_limit`. Encode shard indices as base-`entry_limit` numbers; each digit becomes a directory name (zero-padded).
- **Subdirectories**: base = `entry_limit - 1` to reserve one slot per subdirectory for the manifest entries pointing into it.

Example with `entry_limit = 100`:
- Root base = 100 → indices 0..99 become `00/`, `01/`, ..., `99/`.
- Subdirectory base = 99 → within each, indices 0..98 become `00`, `01`, ..., `98`.
- Manifest lives at the root and references shards by their full tree path.

This guarantees a balanced, predictable layout and leaves headroom in each directory for the manifest's per-directory entry.

### 4. Write the manifest

Write a `manifest.json` (placed as shard 0 at the root) containing, for each original file:

- `rel_path` — the original relative path (reconstruction key)
- `chunks` — ordered list of `{shard_index, offset, length}` tuples (one tuple for unsplit files, multiple for split files)

The manifest must be written **before** data shards, so decompression can locate it. After writing, verify it parses as valid JSON.

### 5. Write data shards

For each shard, concatenate all entries at their assigned offsets (with padding zeros if necessary to align offsets) and write to the assigned directory path. Filenames within a shard directory are arbitrary (e.g. a numeric id); the manifest is the source of truth.

### 6. Verify roundtrip integrity

After writing, always verify a random subset of files (e.g. 10 or 10%, whichever is larger) by:
- Reading the manifest
- Extracting the byte ranges from the indicated shards
- Computing a checksum (e.g. SHA-256) of the reconstructed bytes
- Comparing against the source file's checksum

Fail loudly if any mismatch.

### 7. Decompression (reverse operation)

To restore the original flat directory:

1. Read `manifest.json` from shard 0.
2. For each entry, collect its chunks in order and concatenate the byte ranges.
3. Write the result to `rel_path` under a chosen output root.
4. After all files are reconstructed and verified, delete all shard files and the manifest.

## Pitfalls

- **Reserved slot for the manifest**: forgetting to reserve a slot per subdirectory causes the tree to overflow when the manifest's own entries are counted.
- **Split-file ordering**: chunks must be placed in **consecutive** shards and in chunk order, otherwise reassembly produces scrambled bytes.
- **First-fit vs. best-fit**: first-fit is faster and adequate here; best-fit can reduce shard count but is more expensive.
- **Manifest size**: for very large file sets the manifest itself can exceed the size limit. Either raise the limit for shard 0 or split the manifest across multiple shards.
- **Offset padding**: leave offsets fixed per shard (e.g. always starting at 0 and growing upward) so reconstruction is unambiguous; do not let entries overlap.

## Helper script

A reference implementation in Python lives in `scripts/reshard.py` (see companion file). It implements the full pack → assign → write → verify loop and the reverse decompression loop.