---
name: antibody-antigen-verify
description: When designing a construct (fusion protein, tagged bait, capture reagent) that must be recognized by a specific antibody whose heavy/light chain sequences are given, FIRST identify the antigen via sequence alignment of the antibody variable regions against a protein database, then include the canonical antigen sequence as the binding domain. Do not assume a generic epitope tag (FLAG, HA, Myc, His, GFP, etc.) unless the antibody is verified to be an anti-tag reagent.
---

# antibody-antigen-verify

## When to apply

Any task where the input provides antibody sequences (heavy chain, light chain, variable regions, CDR, or full-length) and the output must include a region that the antibody binds. This includes fusion proteins, chimeric constructs, capture baits, display scaffolds, and tagged antigens.

## Diagnostic checklist (run BEFORE choosing any epitope or binding domain)

1. **Sequence-to-antigen lookup.** Align the provided antibody variable-region sequences (VH and VL) against a curated protein database (UniProt, NCBI nr, IMGT reference sets). Capture the top hit(s) and the organism / protein identity. If the input gives only CDR or framework fragments, align what is provided and note the reduced sensitivity.
2. **Epitope tag vs. native antigen test.** Ask: is there any explicit evidence in the prompt that the antibody is anti-tag (anti-FLAG, anti-HA, anti-Myc, anti-His, anti-GFP, anti-mCherry, anti-Strep, anti-V5)? The default must be the native antigen, not a tag. Absence of anti-tag evidence is itself evidence against a tag.
3. **Canonical isoform retrieval.** Once an antigen candidate is identified, retrieve its canonical (most-common, reference) sequence rather than a tissue-specific isoform, a splice variant, or a partial fragment, unless the prompt constrains the variant. Document the accession ID used.
4. **Bidirectional consistency check.** Confirm that the antibody's reported target (from prompt, paper, vendor catalog, or inferred from sequence) matches the chosen antigen's identity. If the antibody is described as raised against protein X, the construct must include protein X — not a homolog, not a family member, not a tag.

## Stop signal

**Stop and reset** if any of these occur:

- You are about to insert FLAG, HA, Myc, His, V5, GFP, Strep, biotin, or any other generic epitope tag as the antibody-binding domain without explicit prompt evidence that the antibody is anti-tag. **Reset action:** re-run steps 1-4 of the diagnostic checklist before committing to a binding domain.
- Sequence alignment returns no significant hit (E-value / identity below the chosen threshold, or only matches to unrelated species). **Reset action:** state the failure in the output, narrow the search to immune repertoire or nanobody databases, or surface the ambiguity to the user — do not silently fall back to a tag.
- The chosen antigen isoform differs from what the antibody was raised against (different organism, different isoform, truncated/mutant form). **Reset action:** use the antibody's known antigen isoform; if unknown, prefer the human / canonical reference sequence and note the assumption.
- You have already committed the binding-domain choice to the construct and only then realize the antibody identity is unknown. **Reset action:** roll back the binding-domain choice, perform the alignment first, and rebuild the relevant region.

## Rationale

A fusion protein that the supplied antibody does not actually recognize fails end-to-end regardless of how clean the rest of the design is. Generic epitope tags are a frequent, untested assumption that silently invalidates downstream verification (binding assays, IP, ELISA, imaging). Identifying the true antigen from the antibody's own sequence and validating it against the antibody's provenance prevents this class of failure.