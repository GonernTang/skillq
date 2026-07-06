---
name: raman-peak-fitting
description: Fit Lorentzian (or Voigt) peaks to Raman spectra (G peak ~1580 cm⁻¹, 2D peak ~2700 cm⁻¹) and emit per-peak parameters (x0, gamma, amplitude, offset) as JSON. Use when the task involves Raman spectroscopy peak fitting, curve_fit on spectroscopic data, or extraction of peak center/width/intensity from comma-decimal formatted text files.
---

# Raman peak fitting (G, 2D) → JSON

## When this skill applies

The task asks you to fit characteristic Raman peaks — typically the **G band (~1580 cm⁻¹)** and the **2D band (~2700 cm⁻¹)** — from a spectrum read from a text file, and to write the fitted parameters to a JSON file. Files may use **comma as the decimal separator** (European format) rather than the more common period.

## Procedure

1. **Load with locale awareness.**
   - Try `numpy.loadtxt` / `numpy.genfromtxt` with `delimiter=','` first if the file looks comma-separated.
   - If values parse as NaN or the file uses `;` separators with `,` decimals, fall back to reading as text and replacing `,` with `.` before `float()` conversion. Do not assume period decimals.

2. **Detect rough peak positions.**
   - Smooth lightly (Savitzky-Golay or moving average) if the signal is noisy.
   - Use `scipy.signal.find_peaks` with a prominence threshold, or simply locate the maxima of the smoothed signal.
   - Confirm expected bands are present near ~1580 and ~2700 cm⁻¹. If only one is present, fit only the present peak(s); do not invent a second.

3. **Choose the model.**
   - Start with **Lorentzian**:
     `L(x) = offset + amplitude * gamma**2 / ((x - x0)**2 + gamma**2)`
     Parameters: `x0` (center), `gamma` (HWHM), `amplitude` (peak height above offset), `offset` (baseline).
   - Upgrade to **Voigt** (pseudo-Voigt is fine and faster) only if residual RMS clearly indicates Gaussian broadening.

4. **Build initial guesses.**
   - `x0` ≈ the detected peak position.
   - `offset` ≈ a low-percentile value of the spectrum (e.g. 10th percentile) or the mean of regions far from the peak.
   - `amplitude` ≈ (peak maximum − offset), positive.
   - `gamma` ≈ 5–20 cm⁻¹ for G, 20–60 cm⁻¹ for 2D (graphene). Use the FWHM/2 of the detected peak as a fallback.

5. **Set bounds sensibly.**
   - Constrain `x0` to ±30 cm⁻¹ of the guess.
   - Constrain `amplitude > 0`, `gamma > 0.5`, `offset` near the baseline.
   - Use `scipy.optimize.curve_fit(..., p0=p0, bounds=(lo, hi))`.

6. **Validate the fit.**
   - Check `popt` is finite (no NaN/Inf).
   - Compare residual std-dev to noise floor — if residuals dominate the signal, the model or guesses are wrong.
   - Confirm `x0` landed near the expected band within ~5 cm⁻¹.

7. **Write JSON output.**
   - Emit one object per fitted peak with keys exactly as required by the task, typically:
     `{"x0": ..., "gamma": ..., "amplitude": ..., "offset": ...}`
   - Round to a reasonable precision (e.g. 4–6 decimals) unless the spec says otherwise.
   - Ensure the JSON file is valid before declaring done.

## Diagnostic checklist (run BEFORE scaling up)

1. **Decimal-separator probe** — print the first non-empty line of the file; confirm whether it uses `,` or `.` as decimal, and whether the delimiter is `,` `;` or whitespace. Choose the reader accordingly.
2. **Empty/baseline fit on offset-only model** — fit a constant to the lowest-intensity 10% of the spectrum; the recovered `offset` should be within an order of magnitude of the file minimum. If not, the spectrum is not yet understood.
3. **Single-peak sanity fit** — fit the G peak alone with Lorentzian using only the guess recipe above; the recovered `x0` must land within ~5 cm⁻¹ of the expected band. If not, switch to a different peak detector or a broader smoothing window.
4. **Residual-vs-noise check** — compare the std-dev of `data − model` to the std-dev of a flat region; the ratio should be < 0.2 for a good fit, otherwise re-tune `gamma`/`offset` before adding the 2D peak.

## Stop signal

If after **3 different initial-guess strategies** (e.g. varying smoothing, detector, or `gamma` starting values) the G peak still fails to converge within ~5 cm⁻¹ of 1580 cm⁻¹, **abandon the Lorentzian-on-raw-signal approach** and try one of: (a) baseline subtraction first (asymmetric least squares), (b) pseudo-Voigt model, or (c) fitting in log-scale intensity. Do not iterate further on the same pipeline.

## Common pitfalls

- Parsing European-decimal files with `loadtxt` defaults → silently NaN-laden arrays.
- Using a global linear/polynomial baseline that drowns out the Lorentzian offset.
- Setting `p0=[1, 1, 1, 0]` constants — these rarely converge to Raman values; always seed from detected peaks.
- Forgetting that `scipy.optimize.curve_fit` returns the **covariance** matrix as a second value; inspect `pcov` for absurdly large values which signal over-parameterization or bad data.
- Writing JSON with the wrong key names or in scientific notation when the grader expects floats.

## Reference snippet (Lorentzian + curve_fit)

```python
import numpy as np
from scipy.optimize import curve_fit

def lorentzian(x, x0, amplitude, gamma, offset):
    return offset + amplitude * gamma**2 / ((x - x0)**2 + gamma**2)

x, y = np.loadtxt("spectrum.csv", delimiter=",", unpack=True)  # adjust for locale
p0 = [1580.0, y.max() - y.min(), 10.0, np.percentile(y, 10)]
bounds = ([1550, 0, 0.5, -np.inf], [1610, np.inf, 100, np.inf])
popt, pcov = curve_fit(lorentzian, x, y, p0=p0, bounds=bounds)
# popt -> [x0, amplitude, gamma, offset]
```