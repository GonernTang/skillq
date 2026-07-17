---
name: coq-plus-comm
description: Prove addition commutativity on natural numbers (forall n m : nat, n + m = m + n) in Coq using induction, plus_n_O, and plus_n_Sm.
---

# Proving `n + m = m + n` in Coq

## Goal

Prove commutativity of addition on `nat`:

```coq
Theorem plus_comm : forall n m : nat, n + m = m + n.
```

## Proof script

```coq
Proof.
  intros n m.
  induction n as [|n' IHn'].
  - simpl. apply plus_n_O.
  - simpl. rewrite IHn'. apply plus_n_Sm.
Qed.
```

## Step-by-step reasoning

1. **Introduce variables.** `intros n m.` brings both quantifiers into the context, leaving goal `n + m = m + n`.

2. **Induct on the first argument.**
   `induction n as [|n' IHn'].` produces two subgoals:
   - Base: `0 + m = m + 0`
   - Step: `S n' + m = m + S n'` with hypothesis `IHn' : n' + m = m + n'`

3. **Base case.** `simpl.` reduces `0 + m` (by Coq's definitional equality on `plus`) to `m`, leaving `m = m + 0`. `apply plus_n_O.` closes the goal — the standard library lemma `plus_n_O : forall n : nat, n = n + 0` matches directly.

4. **Inductive case.** `simpl.` unfolds the left side, turning `S n' + m` into `S (n' + m)`. Now the goal is `S (n' + m) = m + S n'`. Use `rewrite IHn'.` to replace `n' + m` with `m + n'`, yielding `S (m + n') = m + S n'`. Finally `apply plus_n_Sm.` — the lemma `plus_n_Sm : forall n m : nat, S (n + m) = n + S m` — closes the goal.

## Compile and verify

Save the proof in a `.v` file alongside any needed imports (e.g., from the standard library or `Software Foundations`), then compile:

```bash
coqc plus_comm.v
```

## Common pitfalls

- **Wrong lemma orientation.** If `apply plus_n_O` or `apply plus_n_Sm` fails to unify, check the lemma's statement with `Check plus_n_O.` / `Check plus_n_Sm.` You may need `symmetry` or `apply ... with ...` rather than a different lemma.
- **Forgetting to `simpl` first.** The base case `m = m + 0` is only visible after reduction; without `simpl` the goal still shows `0 + m = m + 0`.
- **Inducting on the wrong variable.** Inducting on `m` works but requires a different lemma set (`plus_O_n` instead of `plus_n_O`). Stick with the first argument unless told otherwise.
- **`rewrite` direction.** `rewrite IHn'` rewrites left-to-right matching the induction hypothesis exactly. If `IHn'` were stated the other way you'd need `rewrite <- IHn'`.