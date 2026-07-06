---
name: fusion-protein-gblock
description: Design and assemble multi-component fusion protein gBlock sequences for synthetic biology. Use when the task requires combining protein domains (e.g., fluorescent proteins, binding proteins, antibody targets) into a single coding sequence joined by GS linkers, including FRET pair selection by excitation/emission wavelengths, SMILES-based ligand-binding protein lookup, and PDB sequence retrieval.
---

# Fusion Protein gBlock Design

When asked to design a fusion protein gBlock, follow this procedure. The recurring failure mode is jumping into PDB fetches without first deciding which components are needed and why — the agent then stalls on the wrong protein or assembles an order that breaks the intended function.

## Step 1 — Decompose the spec into components

Before fetching anything, list every required protein component explicitly:
- FRET donor and/or acceptor (specified by excitation λ and emission λ in nm)
- Small-molecule binding protein (specified by SMILES or drug name)
- Antibody-binding partner (specified by antibody name → antigen target)
- Any scaffold, signal peptide, or purification tag

For each, write down the **selection criterion** (e.g., "emission ≥ 600 nm", "binds atorvastatin"). Without a criterion, you cannot tell whether a candidate PDB entry is correct.

## Step 2 — Resolve each component to a sequence

For every component, use the criterion from Step 1 to pick one and only one PDB / UniProt entry. For FRET pairs, the emission of the donor must overlap the excitation of the acceptor — verify overlap, not just absolute wavelengths. For SMILES queries, search a ligand database (ChEMBL, PubChem, BindingDB) for known protein binders, then map the best hit to a PDB structure. For antibody targets, look up the canonical antigen (e.g., for anti-HER2 → HER2/ERBB2).

Fetch the **amino acid sequence** (not just the PDB ID) and store it with its source. Coding DNA optimization comes later.

## Step 3 — Decide component order

Order matters for function. Document the reasoning for the chosen N-to-C order:
- FRET: donor first, then short linker, then acceptor (energy transfer direction)
- Binding protein before reporter: ligand binds first, then signal is generated
- Antibody epitope must remain accessible — usually placed at the C-terminus

## Step 4 — Connect with GS linkers

Use (GGGGS)n flexible linkers (typical n = 2–4). Insert a unique, in-frame GS linker between every pair of adjacent domains. Keep a written list of every junction so you can verify the final assembly.

## Step 5 — Reverse-translate and verify

Reverse-translate the full protein to a DNA sequence (use an E. coli codon table unless told otherwise). Before writing the final gBlock:
- Length must be in the 500–3000 bp gBlock range (split or trim if outside)
- No internal stop codons, no rare codons clustered in one domain
- Reading frame is continuous across every junction
- Start codon (ATG) and stop codon (TAA/TAG/TGA) flank the construct

## Diagnostic checklist (run BEFORE assembling the final gBlock)

1. **Component inventory complete?** Every component from the spec has a chosen PDB/UniProt entry AND a selection criterion written next to it. If any row is blank, stop and resolve it.
2. **FRET overlap confirmed?** If a FRET pair is involved, compute the spectral overlap integral (donor emission × acceptor excitation) and confirm it is non-zero. Non-overlapping spectra → no FRET.
3. **Linker junctions enumerated?** Count junctions = N_components − 1. Every junction has an explicit (GGGGS)n with the exact n value. Total GS amino acid count recorded.
4. **Reading frame sanity check?** Translate the assembled DNA in silico across every junction; the result must equal the concatenation of the individual protein sequences with linkers inserted, with no frameshifts or premature stops.

## Stop signal

If the diagnostic checklist fails on items 1, 2, or 4 after **two attempts** to fix it (e.g., swapping PDB entries, changing FRET pairs, re-choosing the antibody target), **abandon the current component selections and re-do Step 1 from the spec**. Do not iterate on the assembly while a wrong component is locked in. After 2 failed assembly passes with the same architecture, escalate to the user with the conflicting constraints instead of producing a third variant.

If only item 3 (linker enumeration) fails, fix the linkers and re-run the checklist — do not re-select components.