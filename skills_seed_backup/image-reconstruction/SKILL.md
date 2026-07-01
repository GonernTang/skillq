---
name: image-reconstruction
description: Reverse-engineer a programmatically generated image (gradient, checkerboard, path-traced scene) by sampling colors at key coordinates, detecting the underlying pattern, and synthesizing a compact program that reproduces the pixels without reading the original file. Use when asked to reconstruct an image whose generation procedure must be inferred from the pixels alone, or when a task says "reproduce this image" but reading the source is forbidden.
---

# Image Reconstruction from Pixel Samples

When a task asks you to reproduce a programmatically rendered image without access to the original source, you must INFER the rendering function from the pixel data. Every clue comes from sampling. Do not guess a model class (gradient vs path-trace vs tile) before you have evidence.

## Procedure

1. **Sample the canvas at a probe grid.** Minimum set: 4 corners, 4 edge midpoints, the center, and the center of each quadrant. Record (x, y, R, G, B) at each. Use the image's actual dimensions, not assumed ones.
2. **Classify the pattern from the samples.**
   - All probes (near-)identical across all channels → flat fill.
   - R/G/B vary linearly with x or y → linear gradient. Fit slope + intercept per channel.
   - R/G/B depend on (x² + y²) or radius → radial gradient. Fit center + falloff.
   - Periodic palette along a row or column → checkerboard, stripes, or tile. Measure period first, verify it tiles the whole dimension.
   - Smooth bright region (specular) + smooth dark region (shadow) with soft falloff → path-traced scene. Identify the light position, ground plane, and hotspot before modeling.
3. **Formulate the closed-form model.** Express each pixel as `color(x, y) = f(x, y)`. Prefer: `base + slope_x*x + slope_y*y` for gradients, `f(distance(x, y, light))` for radial, piecewise for tiled.
4. **Encode in a small program** (C or Python) that emits PPM/PNG. Respect any size cap (commonly <2 KB) — drop comments, shorten names, use integer math.
5. **Compare to the target** at the original probe points. If a visual diff tool exists, use it; otherwise check each probe RGB against tolerance.

## Diagnostic checklist

Run these BEFORE committing to a model class. The wrong assumption wastes a full iteration.

1. **Uniformity probe:** sample 9 evenly spaced points across the image. If every channel is within ±2 of every other across all 9, the image is a flat fill (or extremely low-frequency gradient) — do not assume a complex pattern.
2. **Gradient direction probe:** compute `diff_h = color(W-1, H/2) - color(0, H/2)` and `diff_v = color(W/2, H-1) - color(W/2, 0)`. Large `diff_h` + small `diff_v` → horizontal gradient. Both large with opposite sign → diagonal. Both small but corners differ from center → radial. Both near zero → not a linear gradient.
3. **Periodicity probe:** sample along the top row at every pixel for the first 32 pixels. If a small RGB block repeats, measure the period and verify it tiles the full width. A non-repeating row rules out a tile/stripe model.
4. **Path-trace tell-tales:** look for one smooth bright region (specular highlight) and one smooth dark region (cast shadow) with a soft falloff between them. Linear and radial models cannot reproduce this — switch to a directional-light + surface-normal model with a single light vector.

## Stop signal

If you have written **2 candidate models and BOTH fail the diagnostic checklist** (e.g., the gradient probe says horizontal but your model is vertical; or the periodicity probe finds no period but you assumed a checkerboard), **stop writing code and re-sample the image at 3× density** (27+ probes, including the suspect region) before writing a third model. The original sampling was too sparse — you missed a feature (a stripe, a hotspot, a boundary, a second gradient). Do NOT iterate on the model architecture; iterate on the data you collect.

If the image is path-traced and your reproduction is within ~5% perceptual error at the probe points but not exact, the model class is correct — refine coefficients (light position, falloff exponent, surface normal) rather than switching to a different model class. Switching model classes after coefficient tuning has already converged is the most common spiral.