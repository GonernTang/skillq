---
name: sdm-primer-verify
description: Verify Q5 site-directed mutagenesis primers before committing to output. Use when designing back-to-back primers that must amplify an entire circular plasmid while placing a mutation at a precise junction. Guards against reverse-primer complement errors, primer overlap/gap, and missing-amplicon failures.
---

When designing Q5 site-directed mutagenesis (SDM) primers, the most common
failure is not the primer sequence itself but the *mapping* of the two
primers onto the template: the reverse primer's annealing tail must
reverse-complement the template at the correct position, the two 5' ends
must sit back-to-back with no gap and no overlap, and the resulting
amplicon must span the entire circular plasmid.

Run this checklist BEFORE writing primers to a file.

## Diagnostic checklist

1. **Mutation localization.** Align input vs. output and record the exact
   coordinate(s) of insertion, deletion, or substitution. If the alignment
   is ambiguous, stop — re-derive the mutation site before designing.

2. **Forward primer geometry.** Verify the 3' annealing tail (15–45 nt)
   starts immediately downstream of the mutation site on the sense strand,
   and the 5' overhang carries the mutation. Reject if the tail crosses
   the mutation or starts >1 nt away from it.

3. **Reverse primer geometry.** Independently reverse-complement the
   expected annealing region of the template (upstream of the mutation on
   the opposite strand) and compare against the proposed reverse primer's
   3' tail. Reject if they do not match exactly — off-by-one or strand
   flips are the typical silent failure.

4. **Back-to-back junction.** On a linear map of the plasmid, the 5' end
   of the forward primer and the reverse-complement of the 5' end of the
   reverse primer must be adjacent: 0 nt gap, 0 nt overlap. A gap leaves
   the original sequence at the junction; an overlap causes a duplication.

5. **Full-plasmid amplicon.** Simulate PCR with the primer pair on the
   circular template and confirm the product length equals the full
   plasmid size. A shorter product means a primer is binding the wrong
   location or the wrong strand.

## Stop signal

If any check above fails, or if Tm (computed with the specified
oligotm flags) falls outside 58–72 °C, or the paired-primer Tm
difference exceeds 5 °C — STOP. Do not write `primers.fasta`. Adjust
the annealing length or primer position, then re-run the full
checklist from step 1. Only proceed to FASTA output once every
check passes AND Tm constraints are satisfied.