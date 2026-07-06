---
name: coq-arithmetic-lemmas
description: Apply Coq standard-library arithmetic lemmas (plus_n_O, plus_n_Sm, mult_n_O, etc.) with correct rewrite direction. Use when proving arithmetic identities in Coq / Rocq and the goal does not close after a `simpl` / `intros` / `induction` sequence.
---

When a Coq proof stalls after `simpl`/`intros`/`induction` with a goal like
`m = m + 0`, `m + S n' = S (n' + m)`, or any identity involving `+`, `*`,
`S`, or `O`, the blocker is almost always a **direction mismatch** between
the goal and the standard lemma being applied. The standard library defines
its lemmas in one fixed direction; the goal often needs the reverse.

## Diagnostic checklist

Before invoking `apply L.` or `rewrite L` where `L` is a standard
arithmetic lemma, run these checks **on the printed goal and the lemma's
statement**:

1. **Print the goal** with `Show.` and the lemma's type with `Check L.`
   Write down both sides of each equality.
2. **Compare directions**: the LHS of the lemma's equality must match (or
   unify with, after the right substitution) the subterm you want to
   replace. If not, you need the reverse direction.
3. **Pick the right tactic for the direction**:
   - `plus_n_O : n + 0 = n` — proves `n + 0 = n`. To prove `m = m + 0`,
     use `rewrite <- plus_n_O` or `apply eq_sym, plus_n_O` or
     `replace (m + 0) with m by apply plus_n_O`.
   - `plus_n_Sm : S (n + m) = n + S m` — proves `S (n+m) = n + S m`. To
     prove `n' + S m = S (n' + m)` or `m + S n' = S (m + n')`, use
     `rewrite <- plus_n_Sm` with the right instantiation, then close with
     `apply IH` / `reflexivity`.
   - `mult_n_O : n * 0 = 0` and `mult_O_n : 0 * n = 0` — direction
     matters here too.
4. **After the rewrite, re-`Show.` the goal** and confirm the subterm
   actually changed. If it didn't, the direction or instantiation is
   wrong; do not stack more rewrites on top.
5. **Compile with `coqc` (or `CoqIDE`)** at the end and grep the output
   for `admitted`, `Admitted`, or unsolved goals. Do not declare the proof
   done until the file compiles with no remaining `admit`.

## Stop signal

If you have applied the same arithmetic lemma **twice** in different forms
(`apply`, `rewrite <-`, `rewrite ->`, `replace`) and the goal's subterm is
still unchanged, stop and re-read both `Check L.` and `Show.` verbatim.
Do not try a third variant. The fix is **never** "try the lemma harder" —
it is to switch to the alternative lemma (e.g. `plus_n_O` vs
`plus_O_n`), use `symmetry`, or restructure the induction (generalize a
variable before `induction` so the IH has the right shape). Three failed
attempts at the same goal with the same lemma family = wrong lemma.

## Common pitfall table

| Goal subterm             | Lemma              | Direction    | Tactic                       |
|--------------------------|--------------------|--------------|------------------------------|
| `m + 0` (LHS)            | `plus_n_O`         | `n+0 = n`    | `rewrite plus_n_O`           |
| `m` (want `m = m + 0`)   | `plus_n_O`         | reverse      | `rewrite <- plus_n_O`        |
| `n + S m` (LHS)          | `plus_n_Sm`        | `S(n+m)=n+Sm`| `rewrite plus_n_Sm`          |
| `S (n' + m)` (LHS)       | `plus_n_Sm`        | reverse      | `rewrite <- plus_n_Sm`       |
| `0 + n`                  | `plus_O_n`         | `0+n = n`    | `rewrite plus_O_n`           |

## Verification step

Before reporting the proof complete:
- Run `coqc` on the `.v` file and confirm zero output beyond the usual
  banner.
- Grep the file for `admit`, `Admitted`, `TODO` — none should remain.
- Re-read the final `Qed.` line's proof term to be sure no axiom was
  silently introduced.