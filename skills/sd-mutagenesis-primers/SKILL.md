---
name: sd-mutagenesis-primers
description: Guide for site-directed mutagenesis primer design (Q5 / NEB-style). Use when designing primers for an insertion, deletion, or substitution into a plasmid or linear DNA. Covers identifying sequence differences (with circular-topology awareness), designing forward and reverse primers with 15–45 nt annealing flanks, computing Tm via primer3's `oligotm` with the NEB-Q5 flags (`-tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500`), enforcing Tm 58–72 °C with ≤5 °C intra-pair spread, grouping the minimum number of primer pairs, and emitting the result as FASTA with forward listed before reverse.
metadata:
  domain: molecular-biology
  tool: primer3 oligotm
  output: primers.fasta
---

# Site-Directed Mutagenesis Primer Design

Use this skill whenever the task is "given a wild-type DNA sequence and a target mutant sequence (or a description of the desired change), output primer sequences suitable for a NEB Q5 / Q5-site-directed-mutagenesis-style workflow." The failure mode this skill prevents is skipping the workflow and emitting ad-hoc primers without verifying Tm, pair orientation, or minimum-pair coverage.

## Workflow

1. **Identify every difference between the input and desired output sequences.**
   - If the molecule is circular, compare the output sequence against itself rotated so the mutation site is canonical; do not stop at the first mismatch in a linear walk-through.
   - Classify each difference: insertion, deletion, or substitution. Group contiguous differences into a single *mutation cluster*.
2. **For each cluster, design a forward primer:**
   - Length: 15–45 nt annealing on each side of the mutation (Q5 guidance). Aim for the lower end (~18–25 nt) when GC-rich, longer (up to 45 nt) for AT-rich or low-complexity flanks.
   - For insertions, the forward primer carries the inserted bases inline. For deletions, the primer spans the gap as if it were already removed.
   - For substitutions, replace only the differing bases.
3. **Design the reverse primer for the same cluster:**
   - It is the reverse complement of the forward primer's 5' overhang — i.e. its 3' end matches the wild-type sequence immediately *opposite* the forward primer's annealing region, and its 5' tail is the reverse complement of the forward primer's 5' tail (which carries the mutation).
   - Length should match the forward primer's annealing length so Tm can be balanced.
4. **Compute Tm for every primer** with primer3's `oligotm` using the **NEB Q5 / Q5-SDM flag set**:

   ```
   oligotm -tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500 <primer.fasta
   ```

   Flags: `-tp 1` SantaLucia thermodynamic parameters, `-sc 1` salt correction (SantaLucia), `-mv 50` Mg²⁺ 50 mM equivalent (Q5 buffer), `-dv 2` dNTP 2 mM equivalent, `-n 0.8` Tm formula = SantaLucia nearest-neighbour, `-d 500` DNA concentration 500 nM.
5. **Enforce Tm constraints** before emitting anything:
   - Each primer: 58 ≤ Tm ≤ 72 °C.
   - Within a pair: ΔTm ≤ 5 °C.
   - If a primer fails, extend the 3' annealing region in 2–4 nt increments and re-run `oligotm`. Do not relax the Tm window.
6. **Group primers into pairs.** Write each pair as two consecutive FASTA records: forward first, reverse second. Use clear headers such as `>cluster1_forward`, `>cluster1_reverse`.
7. **Minimize the number of pairs.** One pair per mutation cluster; one pair total if the change is a single contiguous insertion/deletion/substitution. Do not split a single cluster into multiple pairs.
8. **Write the output to `primers.fasta`** in the working directory. Verify the file exists and contains all primer records before reporting success.

## Diagnostic checklist

Before emitting `primers.fasta`, confirm **all** of the following:

1. **Every input↔output difference is accounted for.** Re-run a full diff (allowing for circular rotation) and verify each cluster has a primer pair.
2. **Tm within window.** Each primer's `oligotm` output is between 58 °C and 72 °C inclusive, using the exact flag set `-tp 1 -sc 1 -mv 50 -dv 2 -n 0.8 -d 500`.
3. **Pair ΔTm ≤ 5 °C.** Compute |Tm_forward − Tm_reverse| for every pair; every value ≤ 5.
4. **Pair order and minimum count.** Forward record precedes the reverse record in each pair; the number of pairs equals the number of mutation clusters (no over-splitting, no missing clusters).

## Stop signal

If after **two** passes of Tm adjustment a primer still falls outside 58–72 °C, or any pair still has ΔTm > 5 °C, **stop iterating on primer length**. Recheck whether the mutation was correctly identified at all (circular vs linear, cluster boundaries). If that does not resolve it, abort the run and surface the unresolved cluster — do not ship primers that violate the Tm window. Do not exceed three primer-design passes per cluster.

## Common pitfalls

- Using `oligotm` with the default flag set instead of the NEB Q5 flag set above (Tm will be wrong by several degrees).
- Treating the molecule as linear when it is circular (mutations near the origin get missed).
- Designing the reverse primer as the reverse complement of the *entire* forward primer instead of just the 5' overhang plus the wild-type anneal.
- Emitting the reverse primer before the forward primer in the FASTA pair.
- Splitting one contiguous change into multiple primer pairs.
- Relaxing the Tm window to avoid re-designing.