---
name: pytorch-layer-retuning
description: Recover a PyTorch model from a state dict, then retune a single layer via closed-form least squares and re-export to TorchScript.
---

# Recover a PyTorch model and retune one layer

Use this when you have a `state_dict.pt` (and possibly a paired `dataset.pt`)
but no model class. You need to rebuild the architecture, load the weights,
retune just one layer so the model better fits the dataset, then export the
final model to TorchScript.

## Procedure

1. **Load artifacts safely.**
   ```python
   sd = torch.load("weights.pt", weights_only=True)
   data = torch.load("dataset.pt", weights_only=True)
   ```
   Iterate `sd.items()` and print `(key, tuple(shape), dtype)` for every
   tensor. This is the only reliable way to reverse-engineer the architecture.

2. **Infer the architecture from key/shape patterns.**
   - `embedding.weight` (V × d) → token/numerical embedding.
   - `pos_encoder.pe` (1 × max_len × d) → sinusoidal positional buffer.
   - `transformer.encoder.layers.<i>.self_attn.in_proj_weight` shape
     `(3*d, d)` and `out_proj.weight` `(d, d)` → `nn.TransformerEncoder`
     with `d_model=d`, `nhead` such that `d % nhead == 0`, custom
     `batch_first=False`, `dim_feedforward` from the two `linear1`/`linear2`
     shapes.
   - `decoder.weight` (out_dim × d) → final `nn.Linear(d, out_dim, bias=False)`
     (or with bias if a sibling `decoder.bias` exists).

3. **Define a custom `nn.Module`** whose parameter names exactly match the
   state-dict keys. For a Transformer-based regressor:
   ```python
   class MyModel(nn.Module):
       def __init__(self, vocab, d_model, nhead, dim_ff, max_len, out_dim):
           super().__init__()
           self.embedding = nn.Embedding(vocab, d_model)
           self.pos_encoder = nn.Parameter(torch.zeros(1, max_len, d_model))
           enc_layer = nn.TransformerEncoderLayer(
               d_model=d_model, nhead=nhead,
               dim_feedforward=dim_ff, batch_first=False)
           self.transformer = nn.TransformerEncoder(enc_layer, num_layers=...)
           self.decoder = nn.Linear(d_model, out_dim, bias=False)
   ```
   Run `model.load_state_dict(sd)` and assert
   `missing == unexpected == []`. Always put the model in `eval()` mode
   before any closed-form solve — `TransformerEncoder` behaves differently
   in train mode.

4. **Baseline metric.** Run a forward pass over the dataset and compute
   MSE between predictions and targets. This is the bar the retuned layer
   must beat.

5. **Extract pre-target activations.** Hook the input of the target
   layer so you capture `X` (features going into it) and `Y` (targets).
   For the final `nn.Linear`, register a forward hook:
   ```python
   feats = []
   def hook(_, inp, __): feats.append(inp[0].detach())
   h = model.decoder.register_forward_pre_hook(hook)
   _ = model(batch)           # run all examples
   h.remove()
   X = torch.cat(feats)       # shape (N, d_model)
   Y = <targets>              # shape (N, out_dim)
   ```
   Reshape `X`/`Y` consistently (e.g. flatten the seq/batch dims together).

6. **Solve closed-form least squares for the target layer.**
   For a linear layer `y = X W^T + b` with `N` samples:
   - With bias: augment `X_aug = [X | 1]`, solve
     `W_aug = (X_aug^T X_aug + λI)^{-1} X_aug^T Y` (use `torch.linalg.lstsq`
     or a small ridge term for stability).
   - Without bias: solve `W = (X^T X + λI)^{-1} X^T Y` directly.
   Pick a tiny ridge (e.g. `λ = 1e-4 * trace(X^T X)/d`) when `X^T X` is
   near-singular (common with deep Transformer features).

7. **Apply the solution and freeze everything else.**
   ```python
   with torch.no_grad():
       model.decoder.weight.copy_(W)
       if model.decoder.bias is not None:
           model.decoder.bias.copy_(b)
   for p in model.parameters():
       p.requires_grad_(False)
   model.decoder.weight.requires_grad_(True)   # only this one
   ```
   Verify invariants: hash every non-target parameter against the original
   state dict — they must be identical. Then re-run MSE; it must drop.

8. **Export to TorchScript.**
   ```python
   scripted = torch.jit.trace(model, example_input, check_trace=False)
   scripted.save("model.pt")
   ```
   For Transformer models always pass `check_trace=False`: the trace
   checker is fooled by PyTorch's internal module naming
   (`TransformerEncoderLayer` instances get suffixed `_0`, `_1`, …) and
   reports spurious mismatches even when outputs are correct.

9. **Validate the saved artifact.** Load it back, run inference on the
   dataset, recompute MSE, and confirm (a) it matches the in-memory
   model's MSE and (b) it is strictly lower than the baseline from step 4.

## Failure modes to watch for

- **Shape mismatch on `load_state_dict`.** Usually a wrong
  `nhead`/`dim_feedforward` or missing `batch_first` setting. Re-derive
  from the linear layer shapes before debugging anything else.
- **Hook captures the wrong tensor.** A `forward_pre_hook` on a
  `nn.Linear` receives `(input,)`; `input[0]` is the activations, not the
  weights. A `forward_hook` would receive `(input, output)` — pick the
  variant that matches whether you want pre- or post-activation features.
- **MSE doesn't drop after the closed-form solve.** Means you hooked the
  wrong layer, solved against the wrong targets, or `model.eval()` was
  not set when features were captured (dropout/attn-mask nondeterminism).
- **Trace check fails.** Use `check_trace=False`; verify outputs
  numerically instead.