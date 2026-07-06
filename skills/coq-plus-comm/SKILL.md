---
name: coq-plus-comm
description: Complete the Coq proof of commutativity of addition (forall n m, n + m = m + n) on natural numbers using induction, plus_n_O, and plus_n_Sm. Use when asked to prove plus_comm in Coq/CoqIDE or when a proof goal involves n + m = m + n over nat.
---

# Proving `plus_comm` in Coq

The canonical proof that `n + m = m + n` for natural numbers uses
**simple induction** on the first variable plus two lemmas from the
standard library.

## Prerequisites

Always start the file with:

```coq
Require Import Arith.
```

This brings the relevant lemmas (`plus_n_O`, `plus_n_Sm`, `mult_*`,
etc.) into scope. Without it, `apply` will fail with "unable to find
an instance" errors even though the proof script is correct.

## Proof skeleton

```coq
Theorem plus_comm : forall n m : nat, n + m = m + n.
Proof.
  intros m n.            (* bring both variables into context *)
  induction n as [| n' IHn'].
  - (* base case: n = 0 *)
    simpl.
    rewrite <- plus_n_O.   (* turns m into m + 0 *)
    reflexivity.
  - (* inductive case: n = S n' *)
    simpl.
    rewrite <- plus_n_Sm.  (* turns m + S n' into S (m + n') *)
    rewrite IHn'.          (* replaces n' + m with m + n' *)
    reflexivity.
Qed.
```

## Step-by-step reasoning

1. **Introduce the variables.** `intros m n` (the order does not
   matter; you may also `intros` them one at a time).
2. **Induct on the first variable.** `induction n as [| n' IHn']`.
   This produces two subgoals:
   - base case where `n = 0`
   - inductive case where `n = S n'` with induction hypothesis
     `IHn' : n' + m = m + n'`.

### Base case (`n = 0`)

- After `simpl`, the goal becomes `m = m + 0`.
- **Do not** try `reflexivity` directly — Coq's built-in
  reflexivity does not rewrite `m` to `m + 0`.
- Apply `rewrite <- plus_n_O`. The reverse arrow (`<-`) rewrites
  `m + 0` into `m`, closing the goal at `reflexivity`.

### Inductive case (`n = S n'`)

- After `simpl`, the goal is `S (n' + m) = m + S n'`.
- First, rewrite the **right-hand side** so both sides share a
  constructor: `rewrite <- plus_n_Sm`. This turns
  `m + S n'` into `S (m + n')`.
- Next, apply the induction hypothesis on the left:
  `rewrite IHn'`. This replaces `n' + m` with `m + n'`.
- Both sides are now `S (m + n')`; finish with `reflexivity`.

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `Error: Cannot find a physical path bound to logical path Arith.` | Missing import | Add `Require Import Arith.` at the top |
| `reflexivity` fails on `m = m + 0` | `plus_n_O` not applied | Insert `rewrite <- plus_n_O` |
| Goal stalls at `S (n' + m) = S (m + S n')` | Forgot to flip the RHS | Add `rewrite <- plus_n_Sm` before applying `IHn'` |
| `apply` not finding `IHn'` | Didn't `intros` after `induction` | `induction n` already brings `n'` and `IHn'` into the context; just `rewrite IHn'` |

## Tacticals you can swap in

- `destruct n` works in place of `induction n` only for the base
  case; you still need the full `induction` to obtain `IHn'`.
- `ring` or `omega` solve this goal automatically once `Arith` is
  imported, but the explicit rewrite proof is what the question
  usually asks for.