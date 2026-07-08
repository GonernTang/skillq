---
name: primer3-tm-calculation
description: Use the primer3 oligotm tool for melting temperature computation in DNA assembly and primer design tasks, instead of custom formulas. Triggered when designing primers, computing Tm, or verifying primer pairs for PCR, Gibson, or Golden Gate assembly.
---

# Use primer3 oligotm for Tm calculation

When designing primers for DNA assembly (PCR, Gibson, Golden Gate, MoClo), never compute Tm with a custom wall-rule formula (e.g. `4*(G+C) + 2*(A+T)`). These formulas ignore salt conditions, dNTP concentration, DMSO, and nearest-neighbor thermodynamics, and they silently mis-rank primers. Always compute Tm with the primer3 `oligotm` binary.

## Diagnostic checklist (run BEFORE designing or accepting primers)

1. **Verify primer3 is installed**: run `which oligotm` (or `oligotm --help`). If missing, install via `apt-get install primer3` or `conda install -c bioconda primer3` and re-verify before continuing. Do not proceed with a hand-rolled Tm.
2. **Sanity-check oligotm on a known short sequence**: run `oligotm -tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500 ACGTACGTACGTACGTACGT` and confirm it returns a finite numeric Tm. If it errors, fix the install — do not fall back to a custom formula.
3. **Use the assembly-primer flag set consistently**: `-tp 1` (Tm calculation), `-sc 1` (SantaLucia 1998 parameters), `-mv 50` (mM monovalent cations), `-dv 2` (mM divalent cations), `-n 0.8` (mM dNTPs), `-d 500` (nM DNA template). Hard-code or template this invocation; do not let flags drift between primers.
4. **Compute Tm on the annealing region only**: overhangs (Golden Gate sticky ends, restriction sites, homology arms) MUST be stripped before passing the sequence to `oligotm`. Compute Tm on the binding region, then re-append the 5' tail for ordering.
5. **Pair primers by Tm, not by length**: after computing Tm for every candidate, verify that forward/reverse pairs have Tm difference ≤5°C before accepting the pair.

## Stop signal

- **Threshold**: STOP if any primer's Tm was NOT produced by `oligotm`, OR if the paired primer Tm difference exceeds **5°C**, OR if the final in-silico assembled sequence does not match the target.
- **Reset action**: reinstall primer3, rerun checklist items 1–2 on a test sequence, recompute every Tm with `oligotm` using the flag set above on the annealing region only, redesign or trim primers until Tm difference ≤5°C, then re-verify the assembled sequence end-to-end.

## Why custom formulas fail here

Hand-rolled Tm formulas underweight G/C content at high salt, ignore dNTP and Mg²⁺ competition, and do not model nearest-neighbor stacking energy. For multi-fragment assembly with mismatched primer pairs, this routinely produces Tm values 5–15°C off, which causes uneven primer annealing, dropped fragments, and silent junction mismatches.