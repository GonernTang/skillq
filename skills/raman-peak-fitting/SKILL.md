---
name: raman-peak-fitting
description: Fit Lorentzian peaks to Raman spectroscopy data with physically motivated initial guesses, baseline handling, and sanity checks against known peak positions. Use when fitting Raman spectra containing G and 2D peaks (or similar) of carbon materials.
---

# Raman Peak Fitting

When fitting Raman spectroscopy data with one or more Lorentzian peaks, follow this procedure to avoid common pitfalls: wrong model form, bad initial guesses, no baseline subtraction, and unvalidated results.

## Diagnostic checklist

Before committing to a fit, run these checks:

1. **Verify data format and column orientation.** Confirm the x-axis is Raman shift in cm⁻¹ (typical range 1000–3000) and y-axis is intensity. Detect decimal separators (comma vs. point) and delimiters (tab vs. comma) by inspecting the raw file. Sort by ascending Raman shift before fitting.
2. **Confirm peak model before fitting.** Use a Lorentzian: `A * (γ² / ((x − x₀)² + γ²)) + offset`. Do not default to a Gaussian — Raman peaks of carbon materials are Lorentzian by physical convention.
3. **Anchor initial guesses to physics.** For 532 nm excitation on graphene: G peak x₀ ≈ 1585 cm⁻¹ (γ ≈ 30), 2D peak x₀ ≈ 2700 cm⁻¹ (γ ≈ 40). Use amplitude ≈ max intensity in the relevant window (1500–1700 for G, 2600–2800 for 2D). Initial offset ≈ median of edge regions. Random or zero initial guesses cause divergence or local minima.
4. **Subtract a baseline.** Fit only the residual after a linear or spline baseline estimated from peak-free regions (e.g., < 1500 and > 2800 cm⁻¹). Skipping this step biases amplitude and offset.

## Fitting procedure

- Fit peaks individually or simultaneously; a simultaneous multi-peak fit is preferred when peaks overlap.
- Use `scipy.optimize.curve_fit` (or equivalent) with bounds to keep `γ > 0` and `A > 0`.
- After fitting, compute residuals and compare fit parameters to physically expected ranges:
  - G peak: x₀ ∈ [1580, 1600] cm⁻¹
  - 2D peak: x₀ ∈ [2650, 2750] cm⁻¹ (for 532 nm)
- Persist results as JSON keyed by peak name (e.g., `'G'`, `'2D'`), each containing `x0`, `gamma`, `amplitude`, `offset`.

## Stop signal

If fitted `x₀` falls outside the expected window for the peak (e.g., G peak outside 1580–1600 cm⁻¹), **stop and reset**: re-check the initial guess, baseline subtraction, and data orientation before re-fitting. Do not accept the fit as "good enough" — an out-of-window center indicates a wrong model or bad guess, not noise tolerance.