---
name: pytorch-inference-cli
description: Build a command-line inference tool that loads a PyTorch model and runs forward passes on a sample image, then packages it as a standalone binary. Use when the task hands you a .pth weight file, a model architecture (model.py), a sample image, and expects a CLI that outputs a prediction (e.g. digit, class label) from exactly two positional arguments (weights path, image path) printing only the result to stdout.
---

# PyTorch Inference CLI

## When to use

Task signature: a model file (e.g. `model.py` defining `nn.Module`), a `.pth` weight file, and a sample image. Deliverable: an executable that takes two CLI args (weights, image), prints the prediction to stdout, and nothing else.

## Procedure

1. **Read model architecture first** — open `model.py` and record input size, hidden dims, output classes, and activation. Do not guess from the image dimensions alone; the file is authoritative.
2. **Inspect the weights file format** — `torch.save` produces a zip archive. Open it with `zipfile` (Python) or `unzip -l` (shell) and confirm the tensor names match the `state_dict` keys expected by the model class.
3. **Decode the image** — read PNG bytes with Pillow (`PIL.Image.open`), convert to grayscale, resize to the model's expected HxW, normalise to `[0,1]`, and flatten if the model expects a 1-D input vector.
4. **Run the forward pass** — instantiate the model class, call `load_state_dict`, set `eval()`, disable grad, and pass the tensor through. Return `argmax` (classification) or the appropriate head.
5. **Choose packaging**:
   - **Python + PyInstaller** — fastest path if PyTorch is installable; bundles into a single binary.
   - **Pure C/C++ with libtorch** — required if no Python runtime is available. Load weights from JSON, decode PNG with `lodepng`, hand-roll matmul/ReLU.
6. **Pin stdout contract** — the tool must print *only* the prediction (e.g. `"7"`) followed by a newline. No logs, no debug output, no tracebacks on stdout. Errors go to stderr with non-zero exit code.
7. **Verify the exact arg count** — the harness usually invokes the binary with exactly two positional args. Reject and exit non-zero on any other count.

## Diagnostic checklist

Before declaring the binary done, run all of these:

1. **Argument count test** — invoke with 0, 1, 2, and 3 args; confirm the binary accepts only 2 and exits non-zero otherwise.
2. **Empty / corrupt image test** — feed a 0-byte file and a valid PNG of wrong dimensions; confirm graceful stderr error, zero stdout, non-zero exit.
3. **Forward pass smoke test** — load the model in a Python REPL with the actual weights and image, print the predicted class, and confirm it matches expected. This isolates "is the model right?" from "is the binary right?".
4. **End-to-end binary test** — run the compiled binary on the provided sample image and diff its stdout (byte-for-byte) against the Python reference prediction. They must match.

## Stop signal

If you have rewritten the loader/forward-pass code **twice** and the binary still produces wrong output, **do not** iterate a third time on the same architecture. Instead:

- Re-read `model.py` to confirm input shape, normalisation, and class count — most "wrong digit" failures are shape/normalisation mismatches, not weight-loading bugs.
- If the model is correct in Python but wrong in the binary, the bug is in packaging (PyInstaller hidden imports, libtorch link order, or symbol stripping) — switch packaging strategy rather than tweaking inference code.
- If you cannot install PyTorch in the sandbox, commit to the pure-C path immediately; do not spend a fourth attempt trying to make PyInstaller work in a constrained environment.

## Common pitfalls

- **Image not flattened** — a CNN-style model expects (C, H, W); an MLP expects (H*W,). Mismatch silently produces garbage argmax.
- **Normalisation skipped** — if training used mean/std normalisation, `[0,1]` alone is wrong.
- **Weights not loaded into the right module** — `load_state_dict(strict=False)` hides key mismatches; always run with `strict=True` the first time.
- **Stdout polluted by prints** — the grader often `diff`s stdout. A stray `print("loading...")` fails the task.
- **Trailing newline missing** — some graders require `\n`; some strip it. Default to printing with `end="\n"`.