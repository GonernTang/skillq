---
name: video-takeoff-landing
description: Step-by-step procedure for detecting takeoff and landing frames of a moving subject (e.g., hurdler, jumper) in monocular stationary-camera video using background subtraction, blob tracking, and vertical position profiling. Use when the task is "find frame X where athlete leaves ground" or "segment jump phase from a fixed-camera clip", or when reusable_knowledge mentions background subtraction + vertical trajectory + occlusion handling.
---

# Detecting Takeoff / Landing Frames in Stationary-Camera Video

When a single fixed camera watches one subject perform a clear vertical motion (hurdle jump, vertical leap, drop), the reliable pipeline is **background model → motion mask → blob centroid → vertical-trajectory profile → event tagging**. Do NOT try to learn a detector, do NOT rely on per-frame classifiers, and do NOT trust optical flow alone — flow is too noisy on small/occluded subjects.

## Procedure

1. **Build a clean background model.**
   - Take the first N frames (typically 15–60, depending on fps) where the subject is *not yet in frame*. If no such frames exist, use a temporal median over a window where the subject occupies <20% of pixels.
   - The background must be a still RGB image. Save it as `bg.png` and verify visually before proceeding.

2. **Compute a per-frame motion mask.**
   - For each frame `f`: `diff = |f - bg|` (use grayscale or per-channel max), threshold to binary (start at 25/255, tune on a held-out clip), morphological open (3×3) then close (5×5) to remove salt-and-pepper and fill the body silhouette.
   - Sanity-check: the mask should be near-empty for background-only frames and show one connected blob during the subject's flight.

3. **Track the subject's vertical centroid over time.**
   - Find contours on the motion mask, keep the largest contour above a minimum area (e.g., 500 px²). Compute its centroid `(cx_t, cy_t)`.
   - Smooth `cy_t` with a 5-frame moving average. The smoothed curve is your **vertical trajectory**.

4. **Tag takeoff as the end of upward motion.**
   - Compute `vy_t = cy_{t+1} - cy_{t-1}`. Takeoff is the first frame where `vy` flips from consistently negative (going up) to non-negative *after* the subject has risen at least H/8 from its lowest point.
   - Do NOT tag takeoff at the first motion — that's the entry frame, not the launch frame.

5. **Tag landing as reappearance after a flight gap.**
   - During flight, the mask may shrink or vanish (occlusion by hurdle, blur, motion > camera-shake tolerance). The landing frame is the first frame after takeoff where:
     (a) motion energy (mask pixel count) jumps above a threshold (e.g., 2× the in-flight average), AND
     (b) the centroid's vertical position is below the hurdle/bar height, AND
     (c) the centroid has stabilized for ≥2 frames (|vy| small).
   - If the subject never leaves the mask cleanly, fall back to the local minimum of `cy_t` after the apex — that is the touchdown frame.

6. **Validate the output.**
   - Required assertions before reporting: `0 ≤ takeoff < landing ≤ total_frames`; `landing - takeoff` lies in a plausible range for the sport (hurdle: 0.3–1.0 s; vertical jump: 0.2–0.6 s); the apex height exceeds the takeoff/landing height by a margin consistent with the sport.
   - If any assertion fails, do not return the result — re-examine steps 1–5.

## Diagnostic checklist

Run these BEFORE scaling to the full video:

1. **Background purity test.** Render `bg.png` and confirm the subject is absent (no ghost limbs, no trail). If a trail is visible, the first-N-frames assumption is wrong — widen the window or use temporal median.
2. **Mask coverage test.** On 3 hand-picked frames (entry, apex, landing), render the motion mask overlay and confirm it covers the subject's torso + visible limbs. If the mask is fragmented at apex, raise the threshold; if it bleeds onto the background, lower it.
3. **Trajectory shape test.** Plot `cy_t` vs `t`. You should see a clear U-shape or inverted-U with one apex between takeoff and landing. If the curve is monotonic or has multiple local extrema, your smoothing or threshold is wrong.
4. **Order-of-events test.** Confirm `takeoff < landing` and that both lie inside `[0, total_frames)`. If takeoff ≥ landing, you have a takeoff/landing swap — re-read step 4 vs step 5.

## Stop signal

If after **2 full passes** through the pipeline (steps 1–6) the trajectory shape test or order-of-events test still fails, **stop tweaking parameters on the same architecture**. The most common cause at this point is a wrong background (subject is in the warm-up window) or a non-stationary camera (the whole pipeline assumes a fixed camera — verify by checking that a static landmark in the frame does not drift across frames). Switch to one of these alternatives:
- If the camera moves: re-estimate a per-frame homography against the first frame and warp before background subtraction.
- If the subject never leaves a clean mask: drop the mask step and track using a correlation tracker (CSRT/KCF) initialized on the entry frame, then read `cy_t` directly from the bounding box.

Do not write a third version of the same script — the architecture is not the problem once diagnostics 1–3 pass.