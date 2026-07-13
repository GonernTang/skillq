---
name: archive-password-recovery
description: Recover passwords or deleted file contents from corrupted/partial archives by cross-validating with multiple independent tools and treating any single CRC/metadata signal as untrusted. Use when an archive appears damaged, a file inside is missing or overwritten, or a verifier expects a specific format (e.g., `KEY=...` line) rather than a bare password string.
---

When an archive's local-file-header CRC disagrees with the data on disk, or a "recovered" password only matches one tool's output, the single signal is almost certainly misleading. Damage, overwrites, and partial writes corrupt metadata independently from content. A skill here means treating recovery as multi-source and constraint-checked, not as one tool's verdict.

## Diagnostic checklist

Run these BEFORE trusting any single recovered value or committing to an approach:

- [ ] **Cross-validate with ≥2 independent tools.** Never accept a CRC, hash, or recovered value from one source. Use at least two of: `foremost`, `extundelete`/`testdisk`, `strings` on the raw disk image, `binwalk`, archive-specific recovery utilities. If only one tool finds it, treat it as unconfirmed.
- [ ] **Recover original metadata from filesystem journals, not just the archive header.** Size, timestamps, inode info, and allocation status from ext4/xfs journals or `$MFT` are independent of the archive's own (possibly overwritten) header. Compare them against what the archive claims.
- [ ] **Verify the candidate password/file against ALL stated constraints.** Length bounds, character-class set, prefix/suffix requirements, encoding — apply each one as an explicit check. A candidate that fails any constraint is rejected, even if it "almost" works.
- [ ] **Determine the verifier's expected format before submitting.** Read the verifier's wording carefully: it may expect a full line like `KEY=value` or `PASSWORD=value`, not a bare token. Submitting the wrong shape is the most common false-negative.

## Stop signal

**Threshold:** If two independent recovery tools do not agree on the candidate (password, file content, or metadata), STOP. Do not submit, do not iterate on a third tool hoping for confirmation — the disagreement means one of them is reading damaged bytes.

**Reset action:** Return to the raw disk/image, re-extract using a different carving strategy (different offset, different signature set, different tool), and re-run the constraint checklist. Only resume once ≥2 tools converge AND every constraint check passes.

## Common failure modes to avoid

- **Trusting one CRC.** The ZIP/RAR local-file-header CRC is computed at write time and is not re-validated by most readers; if the file was overwritten, the CRC lies.
- **Submitting the bare password when the verifier wants `KEY=password`.** Re-read the prompt's exact wording.
- **Treating "tool X found it" as proof.** Carvers produce false positives on partial signatures. Always require a second independent confirmation.
- **Ignoring filesystem metadata.** When the archive header is corrupt, the journal often still has the original size, timestamps, and allocation map — these constrain the search space and validate candidates.