---
name: sam-polyline-export
description: Convert per-object bounding boxes into refined binary masks and export each as a simplified closed polyline with bbox metadata. Use when converting detection rectangles into segmentation outlines using MobileSAM / SAM-style predictors, or when exporting GeoJSON-style CSVs with columns coords_x, coords_y, xmin, xmax, ymin, ymax.
metadata:
  type: reference
---

# SAM Polyline Export

Use this pattern whenever you must turn rectangular cell/instance prompts into closed-contour polylines and emit a verifier-strict CSV.

## Diagnostic checklist (run BEFORE committing to the implementation)

1. **One image embedding, many box prompts.** Load the lightweight SAM model (e.g. `vit_t`) and call `predictor.set_image(image)` exactly once. Never re-encode the image per cell.
2. **Use box-only prompts.** For each cell, call `predictor.predict(box=box_xyxy, multimask_output=False)` and keep only that single mask — do not request or merge multiple masks per cell.
3. **Resolve overlaps in confidence order.** Sort predictions by score (descending). For each cell, subtract the union of already-claimed pixels from its mask before further processing. This prevents double-counted boundaries where bboxes overlap.
4. **Largest connected component only.** After overlap subtraction, keep the single largest connected component (e.g. `cv2.connectedComponentsWithStats`) and discard the rest. A bounding-box prompt commonly produces stray satellite blobs that must not appear in the contour.
5. **Erode before contouring.** Apply a 1-pixel binary erosion before `findContours` so the extracted polyline sits inside the mask boundary rather than tracing its outer pixels.
6. **Simplify with RDP.** Ramer–Douglas–Peucker (e.g. `cv2.approxPolyDP` with a small epsilon ≈ 0.5–1.0 px) on a closed contour. Strip redundant trailing duplicate of the first vertex when emitting coordinates.
7. **Match the verifier's schema exactly.** Output CSV columns in this exact order: `coords_x, coords_y, xmin, xmax, ymin, ymax`. Each row = one vertex of one cell's polyline; `xmin/xmax/ymin/ymax` are repeated on every row for that cell. No extra columns, no extra whitespace, integer dtype for coords and bbox values, no trailing newline artifacts.

## Stop signal

If any of these is true, STOP and reset the pipeline rather than patching the output:

- You find yourself re-encoding the image inside the per-cell loop → reset: hoist `set_image` out of the loop.
- `multask_output=True` is being used (or masks are averaged/max-pooled per cell) → reset: switch to `multimask_output=False` and use the single returned mask.
- Overlap is handled by post-hoc IoU merging instead of per-mask pixel subtraction in confidence order → reset: re-implement as sorted subtract-then-keep-largest.
- The CSV has reordered columns, renamed columns, or whitespace-padded numeric cells → reset: regenerate with the exact 6-column schema and integer dtype before saving.

## Minimal reference shape

```python
predictor.set_image(image)                       # once
masks = []
for box in boxes:
    m, score, _ = predictor.predict(box=box, multimask_output=False)
    masks.append((score, m[0]))
masks.sort(key=lambda x: -x[0])                 # confidence order
claimed = np.zeros(image.shape[:2], bool)
final = []
for _, m in masks:
    m = m & ~claimed
    keep = largest_cc(m)
    final.append(keep)
    claimed |= keep
for m in final:
    m = cv2.erode(m.astype(np.uint8), np.ones((3,3), np.uint8), iterations=1)
    cnt = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0][0]
    poly = cv2.approxPolyDP(cnt, epsilon, True).reshape(-1, 2)
    xmin, ymin = poly.min(0); xmax, ymax = poly.max(0)
    for x, y in poly:
        rows.append((int(x), int(y), int(xmin), int(xmax), int(ymin), int(ymax)))
```

## Common failure modes this skill prevents

- Re-encoding the image per cell (10–100× slowdown and embedding drift).
- Duplicate boundary pixels from overlapping bboxes because subtraction happened after contouring instead of before.
- Stray satellite blobs shipped to the verifier because no connected-component filter was applied.
- Contours hugging the mask edge (1-pixel-thick mask) producing noisy polylines.
- CSV rejected because columns were reordered or coords came out as floats with trailing zeros.