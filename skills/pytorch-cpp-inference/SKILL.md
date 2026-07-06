---
name: pytorch-cpp-inference
description: Port a trained PyTorch neural network to a standalone C++ command-line inference tool by exporting weights to JSON and reimplementing the forward pass with single-header libraries.
---

# Port PyTorch Model to C++ CLI Inference

Reimplement a trained PyTorch model in C++ as a self-contained CLI tool. Useful when the target environment cannot run Python or depends on PyTorch.

## When to use
- Trained a model in PyTorch and need a lightweight, dependency-free C++ binary that performs the same forward pass.
- The architecture is a simple MLP / fully-connected network (Linear → activation stacks). Convolutions and batchnorm are out of scope of this minimal skill.
- Need to read an image (PNG) and emit a prediction to stdout and a file.

## Workflow

### 1. Export model weights to JSON (Python side)
Run once from the training environment. Flatten every `state_dict` parameter to a 1-D list of floats and write to JSON keyed by parameter name:

```python
import json, torch
sd = model.state_dict()
out = {k: v.detach().cpu().flatten().tolist() for k, v in sd.items()}
out["_shapes"] = {k: list(v.shape) for k, v in sd.items()}
out["_dtype"] = "float32"
json.dump(out, open("weights.json", "w"))
```

Verify the JSON round-trips: load it, reshape, and compare against the live model — they must be identical bit-for-bit.

### 2. Port the forward pass to C++
For each layer, mirror the exact PyTorch semantics:
- Linear: `out[i] = sum_j(W[i,j] * in[j]) + b[i]`. Watch the row/col convention — `nn.Linear` stores weight as `[out_features, in_features]`.
- ReLU: `max(0, x)`.
- Softmax / cross-entropy: usually unnecessary at inference; pick the argmax of the final logits.

Hardcode the layer shapes inferred from the JSON `_shapes` map. Build the forward pass as straight C++ loops — no allocator overhead, no framework.

### 3. Wire input and output
- **Input image**: load a grayscale PNG into a `vector<float>` of size `H*W`. Use a single-header lib like `lodepng.h` or `stb_image.h`. Normalize pixels to `[0,1]` the same way the PyTorch pipeline did (division by 255, optional mean/std subtraction).
- **Output**: write the predicted class index both to stdout and to a file such as `prediction.txt` — the file-based output is what graders usually check.

### 4. Build and verify parity
Compile as a single TU with g++:

```bash
g++ -O2 -o infer infer.cpp
./infer model.png
```

Then compare against PyTorch on the *same* input:
```python
img = torchvision.io.read_image("model.png").float() / 255
pred_torch = model(img.unsqueeze(0)).argmax(1).item()
```
The C++ and PyTorch predictions must match for every test image in the harness. If they diverge, suspect (in order): layout/transpose, normalization, argmax tie-breaking, off-by-one in flattening.

## Reusable helpers
See `scripts/forward_mlp.cpp` for a template implementing an N-layer Linear+ReLU MLP with a final argmax. Adapt `W1/b1/W2/b2/...` to your parameter names and let the loop count scale to however many hidden layers the model has.

## Pitfalls
- **Transpose**: `nn.Linear.weight` is `[out, in]` — easy to confuse with `[in, out]`.
- **Bias broadcasting**: PyTorch adds the bias per output unit; don't forget it on the last layer.
- **Pixel layout**: row-major flatten in C++ must match the Python flatten order (`HWC` vs `CHW` for the loader).
- **Numerical drift**: float32 across CPU and a fresh C++ implementation rarely disagrees on int outputs for a well-trained MNIST MLP, but if it does, cross-check a single layer with printf-debugging.
- **JSON precision**: `tolist()` on float32 tensors preserves full precision; do not round.