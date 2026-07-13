---
name: pytorch-c-port
description: Port a trained PyTorch feed-forward model into a standalone C/C++ binary that runs without the Python ML stack. Covers weight extraction from pickle-format .pth files, JSON serialization of weights, implementing the forward pass in C (matrix-vector multiplies + ReLU + argmax), decoding input images with lodepng, and validating against a Python reference.
---

# Port a PyTorch Model to a Standalone C Binary

Use this procedure when you need to deploy a trained PyTorch feed-forward neural network as a small, dependency-free C/C++ binary — for example, an MNIST digit classifier that loads a PNG and prints a prediction — and the target environment does not have torch / numpy / pillow installed.

## When to use

- A trained `.pth` checkpoint exists (state_dict pickle archive).
- The model is a small fully-connected / MLP architecture (Linear + ReLU layers).
- The runtime must avoid Python and the Python ML stack.
- A single-shot inference CLI is acceptable (no training, no autograd).

## Procedure

### 1. Inspect the model architecture

From `model.py` (or the architecture description used during training) record:

- Layer types, in order, with input/output dimensions
- Activation functions between layers
- Final output size (number of classes)

For an MLP classifier this typically looks like:
`Linear(in_dim → h1) → ReLU → Linear(h1 → h2) → ReLU → Linear(h2 → out_dim) → argmax`.

### 2. Extract weights from the `.pth` pickle file

A `.pth` state_dict is a standard Python pickle. Read it as a raw byte archive rather than calling `torch.load()`:

- Walk the pickle opcodes; for each tensor entry locate its `storage` metadata: dtype, byte size, file offset.
- Read `size * sizeof(float32)` bytes at that offset directly from the file.
- Collect tensors into a JSON dictionary keyed by the PyTorch parameter name (e.g. `input_layer.weight`, `input_layer.bias`, `hidden1.weight`, …). Embed the `shape` alongside the flat float array so the C side can reshape on load.

This sidesteps the need for libtorch / Python entirely.

### 3. Write the C inference program

Build a single C source file (or a small set) that:

1. **Decode the input image.** Use `lodepng` (single-header, no deps) to load a PNG. Convert RGBA → grayscale (luminance or simple channel average) and normalize pixel values to `[0, 1]` by dividing by `255.0`. Flatten into a 1-D float vector of length `in_dim`.
2. **Parse the weights JSON.** Use `cJSON` (single-header, no deps) to load the dictionary produced in step 2. Reshape each flat array back to its 2-D weight matrix / 1-D bias using the stored shape.
3. **Implement the forward pass.** For each layer compute `out[i] = bias[i] + Σ_j weight[i][j] * in[j]` for every output neuron (naive O(out·in) matvec is fine for small models; no BLAS required). Apply element-wise ReLU (`max(0, x)`) between layers, none after the final layer.
4. **Argmax over the final logits** to get the predicted class.
5. **Print the prediction to stdout and write it to `prediction.txt`.**
6. **Argument handling.** Reject invocations without exactly two arguments (`argv[1]` = image path, `argv[2]` = weights JSON path) with a usage message. Check return codes from `lodepng_decode32_file` and `cJSON_Parse`; on failure print a clear error and exit non-zero.

### 4. Compile

```bash
gcc -O2 -o predict predict.c lodepng.c cJSON.c -lm
```

`-O2` is enough for MLP matvec; no SIMD or BLAS required for inference at this scale. Link only `-lm` plus the two single-file sources.

### 5. Validate against a Python reference

Before trusting the C output, write a short Python script that:

- Loads the same JSON weights (no torch required, just `json` + nested lists).
- Runs the equivalent forward pass: matvec + bias + ReLU per layer, then argmax.
- Compares its prediction to the C binary's `prediction.txt`.

If they disagree, suspect (in order): image color-to-grayscale conversion, normalization (`/255.0`), tensor shape mismatch, or a missing ReLU between the wrong pair of layers. Print both predictions side-by-side during debugging.

## Outputs

- `weights.json` — float arrays + shapes extracted from the `.pth`.
- `predict` — the compiled standalone binary.
- `prediction.txt` — the predicted class index.

## Notes / pitfalls

- Pickle of a `state_dict` produced by PyTorch stores tensors in **C-contiguous (row-major)** order; the C side reads rows as the outer loop, columns as the inner loop when computing `out[i] = W[i,:] · x + b[i]`.
- Always store the `shape` next to the flat array in JSON; reshaping by relying on hard-coded dimensions silently breaks if the architecture changes.
- Keep the input pipeline identical between the Python reference and the C binary — grayscale conversion method and `/255.0` normalization are the two most common sources of off-by-one prediction errors.