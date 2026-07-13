---
name: fusion-protein-verification
description: Guard-rail for fusion-protein assembly tasks. Prevents failure modes where an arbitrary epitope tag replaces a real antibody-antigen match, where a binder protein is picked without confirming it recognizes the given small-molecule ligand, or where sequences are encoded from memory instead of a validated source (PDB/UniProt). Use whenever the task involves designing, reviewing, or assembling a fusion/labeled protein that must bind a specified antibody or small molecule, or that must support a downstream assay (FRET, pull-down, imaging).
---

# Fusion Protein Verification

## Diagnostic Checklist

Before committing to any fusion construct, run ALL of the following checks:

1. **Antibody → antigen mapping.** If the construct must bind a named antibody, have you identified the antibody's actual target antigen by analyzing its heavy and light chain sequences (e.g., BLAST against antibody-antigen databases, CDR analysis, or a lookup against the antibody's published reference)? If you cannot name the antigen, do NOT substitute an arbitrary epitope tag (FLAG, HA, Myc, His, etc.) unless the task explicitly specifies that tag.

2. **Small-molecule → binder verification.** If the construct must capture or detect a given SMILES / small-molecule substrate, have you confirmed the chosen binder protein (e.g., SNAP-tag for O6-benzylguanine derivatives, HaloTag for chloroalkane ligands, DHFR for methotrexate analogs, AviTag for biotin) actually recognizes that specific chemistry? Match ligand class to binder family before encoding.

3. **Sequence provenance.** Is every protein domain in the construct sourced from a validated repository (PDB ID, UniProt accession) with the exact sequence/mutations documented? Reject any domain written from memory or guessed; re-fetch from the primary source.

4. **Assay compatibility.** If the fusion is for a specific assay (FRET, pull-down, fluorescence imaging, etc.), have you verified spectral overlap / linker length / orientation / folding independence so that the fusion does not abolish binding or signal? Flag any donor-acceptor pair whose spectra do not overlap, or any linker shorter than ~10–15 flexible residues between structured domains.

## Stop Signal

STOP and return to the diagnostic checklist if ANY of the following is true:

- The antibody target antigen is unknown or has been replaced by a generic tag.
- The small-molecule binder was selected by name recognition rather than verified substrate match.
- Any sequence was written without a PDB/UniProt citation.
- A FRET or spectral pair was chosen without checking donor emission / acceptor excitation overlap.

**Reset action:** Discard the current construct. Re-query sequence/databases for the real antibody-antigen or ligand-binder relationship, fetch all domain sequences from PDB/UniProt, and rebuild the fusion with a flexible (GGGGS)x or equivalent linker. Only re-attempt assembly once all four checklist items are answered with a primary-source citation.