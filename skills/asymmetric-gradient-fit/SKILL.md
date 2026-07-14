---
name: asymmetric-gradient-fit
description: When reconstructing images with gradually-varying channels (gradients, color ramps, smooth fields), detect asymmetry before fitting and avoid assuming symmetric functions. Triggers when reconstructing raster images, fitting color gradients, or reverse-engineering visual data.
---

# Reconstructing Asymmetric Gradient Images

When a task involves reconstructing a raster image with smoothly-varying
channel values (e.g., a vertical or horizontal gradient with red/green/blue
that changes slowly across rows or columns), the naive approach assumes
symmetry about the center and fits a single symmetric formula. This is
often wrong: the gradient may not be symmetric, and forcing symmetry
introduces systematic error.

## Diagnostic checklist

Run these checks BEFORE committing to a symmetric-fit strategy:

1. **Sample both ends at multiple positions.** Read pixel values from the
   first row AND the last row (and first/last columns for horizontal
   gradients). If `top[0] != bottom[-1]` (or first-column != last-column),
   the gradient is NOT symmetric about the center.
2. **Sample interior points for monotonicity.** Read values at 25%, 50%,
   and 75% along the gradient axis. Confirm whether the channel increases
   (or decreases) monotonically — this tells you whether to fit a single
   monotonic function or split into halves.
3. **Compute asymmetry ratio.** `|top[0] - bottom[-1]| / range`. If
   greater than ~5%, assume asymmetry and prepare to fit halves
   separately.
4. **Identify the gradient direction.** Vertical vs horizontal determines
   which axis to vary the fit over.

## Fitting strategy

- **If symmetric** (asymmetry ratio < ~5%): fit a single function
  centered on the midpoint (e.g., `f(t) = a + b*(t - mid)^n`).
- **If asymmetric:** split the axis at the midpoint and fit SEPARATE
  one-dimensional functions for the top half and bottom half (e.g.,
  independent polynomials or power laws). Each half can have its own
  coefficients.
- Use **integer rounding with `(int)(value + 0.5)`** to minimize
  quantization error when emitting integer channel values.

## Validation (mandatory before finalizing)

Compute the true **normalized L2 distance** on a held-out subset (or full
image):

  `L2 = sqrt(sum((predicted - original)^2)) / sqrt(sum(original^2))`

Acceptance threshold: ensure the result meets whatever the task specifies
(e.g., L2 < 0.05). If it does not, refine the fit — try a different
polynomial degree, add a power-law term, or split further (quarters
instead of halves).

## Stop signal

- **Threshold:** Normalized L2 distance > the task's required maximum
  on the validation subset.
- **Reset action:** STOP. Do not finalize the image. Instead:
  1. Re-sample edges to confirm asymmetry was detected correctly.
  2. If still asymmetric, refit halves separately (or quarters).
  3. If a symmetric fit still fails, consider non-polynomial forms
     (exponential, logarithmic, piecewise).
  4. Only finalize when validation passes the threshold.

## Avoid these mistakes

- Assuming `f(mid - x) == f(mid + x)` without sampling both edges.
- Using `(int)value` or `Math.round` carelessly — both can bias
  quantize; the explicit `(int)(value + 0.5)` is the safest pattern.
- Skipping validation because "the fit looks right" — always compute
  the metric on a subset.
- Using a single high-degree polynomial to compensate for asymmetry —
  split the fit domain first, then choose the degree.