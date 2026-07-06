---
name: recover-pytorch-model
description: Reconstruct a PyTorch model from a saved state_dict and an input/output dataset, then re-fit only the final output layer and save the result as a TorchScript artifact. Use when you have only `state_dict` weights plus an `(X, y)` dataset and need to recover an executable `nn.Module` whose predictions match the data.
---

# Recover a PyTorch Model from a State Dict + Dataset

Given only a `state_dict` and a dataset of input/output pairs, rebuild the
matching `nn.Module`, fine-tune the output head, and export a TorchScript file
that still loads the original weights for every other layer.

## When to use

- You have a `.pt`/`.pth` with weights but no model class.
- You have `(X, y)` pairs that the model should approximate.
- You need a deployable artifact (TorchScript) that behaves like the original,
  except that the output head has been re-fit to your data.

## Procedure

1. **Inspect the state dict.** Print `sd.keys()` and per-key `.shape`. Use
   the shapes to deduce:
   - input feature dimension (first Linear's `weight.shape[1]`)
   - hidden layer widths and count (intermediate Linear shapes)
   - output dimension (last Linear's `weight.shape[0]`)
   - activation/structure hints (e.g. `bn`/`norm` keys → BatchNorm;
     `conv` keys → Conv layers)

2. **Define the `nn.Module`.** Build a class whose layers, in order and with
   matching dimensions, reproduce the key layout you observed. Use
   conventional names (`fc1`, `fc2`, …, `output_layer`) so the load in step 3
   works without `strict=False`.

3. **Initialize then load.** Construct the model, then call
   `model.load_state_dict(sd)`. If shapes mismatch, revise the architecture
   definition — do not silently drop keys.

4. **Baseline the loss.** Run `model(X)` (no grad) and compute
   `MSELoss()(y_pred, y)` (or the appropriate regression/classification loss).
   Record the baseline number; re-fit is only worthwhile if the loss is
   non-trivial.

5. **Identify the output head.** It is conventionally named `output_layer` or
   is the *last* `nn.Linear` in `model`. Locate it by name, not by index, so
   the procedure survives layer reordering.

6. **Freeze everything except the head.** For every parameter, set
   `p.requires_grad = False`. Then re-enable grads only on the head's
   parameters. Build an optimizer (e.g. `Adam`) over **only** the head
   parameters (`filter(lambda p: p.requires_grad, model.parameters())`).

7. **Fine-tune the head.** Train for a moderate number of epochs (start with
   a few dozen; stop when loss plateaus). Verify the post-fit loss is
   meaningfully lower than the baseline from step 4.

8. **Export to TorchScript.** Prefer `torch.jit.script(model)` when the model
   uses only scriptable ops; fall back to `torch.jit.trace(model, X[:1])`
   when scripting fails. Save with `torch.jit.save(scripted, path)`.

9. **Verify the round-trip.** Load the saved artifact and run it on `X`;
   confirm the output matches the in-memory tuned model. Confirm that
   `scripted.state_dict()` agrees with the original `sd` for every
   non-output key.

## Guardrails

- Always reload the saved TorchScript and compare numerical outputs before
  declaring success.
- Do not save a model whose head weights have *not* improved over the
  baseline; investigate shape or label mismatch first.
- Keep the architecture definition small and explicit — hidden guesses
  (e.g. unknown activation) should be flagged rather than guessed silently.

## Common pitfalls

- `load_state_dict` mismatch → architecture inference was wrong; revisit
  step 1 before training.
- Loss unchanged after tuning → head may not actually be receiving
  gradients (check `requires_grad` on the right parameters).
- Tracing captures data-dependent control flow badly → switch from
  `jit.trace` to `jit.script`, or refactor the offending block.