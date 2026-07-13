---
name: adaptive-video-thresholds
description: When detecting motion, events, or state changes from video frames (takeoff/landing, falls, gestures, activity transitions), use adaptive/data-driven thresholds (Otsu, percentile-based, learned) instead of hardcoded magic numbers tied to one sample clip.
---

# Adaptive Video Thresholds

Hardcoding thresholds (pixel-difference cutoffs, foreground-pixel counts, velocity cutoffs, smoothing windows) to one example video is the most common cause of fragile video pipelines. Lighting, athlete/actor clothing colors, camera gain, frame rate, resolution, and sensor noise all shift the absolute pixel distributions, so a magic number that "works" on the demo clip silently breaks on the next one.

## Diagnostic checklist (run BEFORE committing to a threshold)

1. **Per-frame distribution inspection**: Plot/print the histogram or summary stats of the raw metric you intend to threshold (frame-difference sum, foreground-pixel count, centroid Y, velocity) across the FIRST 10-30% of frames. If the distribution shape or range is not yet characterized, you do not have a defensible threshold — go back to adaptive methods.
2. **Robust statistic choice**: Prefer order statistics (median, MAD, percentiles) over mean over absolute thresholds. Prefer per-sequence normalization (z-score, robust z-score via MAD) over absolute pixel/velocity values. If your metric requires absolute units, justify the units (px/frame at known FPS) rather than empirical magic numbers.
3. **Adaptive threshold method present**: Confirm the pipeline includes at least one of Otsu's method, percentile-based cutoff (e.g., 95th/99th), background-modeling (MOG2/KNN/subspace), or learned/expert-annotated calibration. A pure constant-threshold gate is a red flag.
4. **Cross-clip generalization probe**: Hold out at least one clip with different lighting, subject color, or camera angle, and verify the same thresholds detect events. If you only have one clip, explicitly state that generalization has NOT been validated — do not present results as robust.

## Stop signal

STOP and reset when ANY of these is true:

- Any threshold is a bare integer/float (e.g., `> 30`, `< -12`, `count > 200`) introduced without a derivation from the data distribution or an adaptive method.
- The same hardcoded value is reused across more than one video source without re-calibration evidence.
- Apex / event detection relies on an arbitrary Y-percentile or velocity-window heuristic instead of the subject's centroid trajectory plus a model-based criterion (parabolic fit, optical-flow consistency, template match of a known landmark).

When you stop, replace the hardcoded gate with one of: (a) Otsu/percentile threshold derived per-clip from the metric distribution, (b) a robust statistic (median ± k·MAD) computed from a non-event baseline window, (c) template matching / optical-flow based detection of a known object or motion signature, or (d) a calibrated parameter set from annotated examples. Then re-run the diagnostic checklist from the top before reporting results.