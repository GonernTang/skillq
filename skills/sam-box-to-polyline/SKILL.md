---
name: sam-box-to-polyline
description: Convert rectangle (bounding-box) mask annotations into polyline masks using a SAM-family segmentation model (MobileSAM, SAM, SAM2). Use when an annotation CSV holds `type=rectangle` rows with either (xmin,ymin,xmax,ymax) columns or polygon-point columns that form a rectangle, and the task requires producing per-cell polylines that trace the actual object boundary. Triggers on histopathology / cell-segmentation pipelines, nuclear masks, or any "box -> contour" workflow that mixes SAM prompting with cv2 contour extraction.
---

# SAM Box-to-Polyline Conversion

When a segmentation dataset stores coarse `rectangle` annotations and you need
tight per-instance contours, run the box through a SAM-family model and trace
the predicted mask back to a polyline. This is the canonical pattern; do NOT
hand-roll a "convex hull of the box" or treat the rectangle's corners as the
final polyline — those are wrong and miss the cell boundary.

## Procedure

1. **Load the SAM variant once.** MobileSAM, SAM, and SAM2 all accept box
   prompts through `SamPredictor.predict`. Use the smallest variant that meets
   the latency budget; MobileSAM is the typical default for cell-scale work.
   Keep the predictor on GPU if available; precompute the image embedding
   **once per image** and reuse it across every box in that image.

2. **Parse the annotation table.** Rectangle rows may carry coordinates in two
   shapes:
   - Explicit `xmin, ymin, xmax, ymax` columns.
   - Polygon-point columns (`coords_x`, `coords_y`) that hold the 4 corners
     of the rectangle. Derive the box as `(min, min, max, max)` over the points.

   Skip rows whose type is already `polyline` or `polygon` — only convert
   what needs converting. Preserve row order so the output CSV lines up with
   the input.

3. **Prompt the model with the box.** Pass the box as a `np.array` of shape
   `(1, 4)` to `predictor.predict(point_coords=None, box=box)`. A common
   failure is to also pass point prompts derived from the box centre —
   that nudges the mask toward the centre and degrades boundary quality.
   Use **box only** unless you have an explicit reason for points.

4. **Extract the largest contour.** Take `masks[0]` (highest-score mask),
   threshold to binary if it is logits, then call
   `cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)`.
   Select the contour with the largest `cv2.contourArea`. Drop any
   sub-pixel / zero-area contour.

5. **Simplify and flatten.** Apply `cv2.approxPolyDP(contour, epsilon,
   True)` with `epsilon ≈ 0.001 * perimeter` — coarse values erase cell
   boundary detail. Flatten to `(x0,y0,x1,y1,...)` and store back into
   `coords_x` / `coords_y` as space- or comma-separated strings, matching
   the input CSV's encoding.

6. **Update the row.** Set `type` to `polyline`. If the schema has a
   `num_points` field, recompute it from the new polyline length so
   downstream consumers don't desync.

7. **Write the CSV.** Use the same delimiter / quoting as the input. Write
   a single self-contained script with `argparse` for `--input`, `--output`,
   `--weights`, and `--device`.

## Diagnostic checklist

Run these BEFORE committing to the full CSV conversion:

1. **Smoke-test on a single image.** Pick the row whose rectangle is largest,
   run it through steps 3–5, and overlay the resulting polyline on the image.
   Confirm the contour hugs the cell boundary, not the original rectangle.
2. **Verify encoding round-trip.** Read a converted row back, parse
   `coords_x`/`coords_y`, and confirm the polyline closes on itself and
   matches what you wrote. CSV escaping (quotes inside coordinates) is the
   most common silent breakage.
3. **Compare against the source box.** Compute IoU between the box and the
   filled polyline — expect ~0.6–0.95; values near 1.0 mean the model
   returned the box unchanged (likely a prompt-format bug); values near 0
   mean the mask detached from the box.
4. **Check empty masks.** Log every row where the predicted mask is empty
   or the largest contour has fewer than 4 points — these are the rows
   that will silently corrupt the output if skipped without logging.

## Stop signal

If 3 different boxes (small / medium / large) all produce contours that
visually trace the **rectangle itself** rather than the object boundary,
the model is not segmenting — it is echoing the prompt. Stop and audit:
- Did you pass `box` as a `(1,4)` float array, not a flat list of length 4?
- Did you call `predictor.set_image(image)` before `predict`?
- Is the image in RGB (SAM expects RGB; OpenCV gives BGR)?

If those are correct and the model still echoes the box, swap the SAM
weights or switch to `multimask_output=True` and pick the mask with the
highest stability score — do not iterate further on the same prompt
format.