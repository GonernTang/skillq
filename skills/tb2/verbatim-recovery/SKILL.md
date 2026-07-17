---
name: verbatim-recovery
description: When extracting content from disk images, archives, or corrupted sources, recover the verbatim original bytes rather than reconstructing from partial clues or constraints. Use when forensic recovery, archive extraction, or file carving yields corrupted/partial output and the constraints alone seem to suggest a plausible answer.
---

# Verbatim Recovery

When the obvious extraction path returns corrupted, truncated, or partial content, do NOT reconstruct the missing pieces by hand from whatever constraints you have. The ground truth still exists somewhere on the underlying medium (raw disk image, unallocated space, archive member, original source) and finding it verbatim is almost always faster and more reliable than guessing.

## Diagnostic Checklist

Run these BEFORE committing to any reconstruction approach:

1. **Verify the recovered artifact is actually complete.** Compute a checksum (md5/sha256) and compare against any expected hash. If no hash is provided, compare the recovered content's structure (length, header magic, footer marker) against the expected format. If the checksum fails or the structure is truncated, the artifact is corrupted — do not proceed with it as-is.

2. **Test the alternate extraction paths in parallel, not sequentially.** If the first tool fails, do not patch its output — run the other tools (different carving tool, different archive extractor, raw `strings` / `grep -a` on the underlying medium, alternative mount options) at the same time and compare results. The fastest path is often not the obvious one.

3. **Search the raw underlying medium for the missing content.** Use `strings | grep` or `grep -aob` on the disk image, archive, or full file system to locate the exact byte offset of a known fragment. The complete original content usually still exists somewhere on the medium even if the extracted copy is corrupted.

4. **Verify every byte of the recovered content against the source before declaring success.** Partial matches at the beginning and end of a file are not proof of correctness — corruption often hides in the middle. Re-extract and re-check the full file end-to-end.

## Stop Signal

**Stop and reset when:**
- You find yourself "filling in" or "guessing" any portion of the recovered content based on constraints (length, format, surrounding context) instead of extracting it from the source medium.
- Two consecutive extraction attempts produce different bytes for the same offset.
- The recovered file's checksum does not match an expected hash, OR (when no hash exists) any byte in the recovered file cannot be located verbatim on the underlying medium.

**Reset action:** Drop the current recovered artifact entirely. Run a fresh verbatim search on the raw underlying medium using `strings`, `grep -a`, or a different carving tool. Only accept output that you can locate byte-for-byte on the source.

## Anti-Pattern

The failure mode to avoid: extracting a corrupted copy, seeing that it "mostly matches" the expected constraints (length, prefix, suffix, format), and submitting the corrupted content with hand-fixed middle bytes. Corruption is rarely cosmetic — if the extracted copy doesn't match byte-for-byte, treat it as wrong and search the raw medium for the real version.