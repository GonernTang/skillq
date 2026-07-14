---
name: video-command-ocr
description: Guard-rail workflow for extracting typed commands from gameplay, terminal, or prompt-based videos using OCR rather than ad hoc visual review.
---

Use this skill when a task asks for a sequence of player, terminal, shell, chat, or prompt commands visible in a video. Do not rely on manual watching alone: compression artifacts, repeated frames, and fast prompt updates make command extraction easy to misread.

## Diagnostic checklist

Before committing to the main extraction approach, run these checks:

1. **Source quality check:** confirm you are using the highest-legibility source available, preferring the largest resolution and least-compressed download/stream frame over a preview or thumbnail capture.
2. **Prompt-region check:** sample several frames and identify the stable screen region where typed commands appear; crop OCR input to that region instead of processing the whole frame.
3. **Sampling-rate check:** extract a small test set at a rate high enough to catch quick command updates, then verify adjacent samples show no skipped prompt changes.
4. **OCR-confidence check:** run OCR on the cropped samples with a layout mode suited to blocks of prompt text, inspect confidence scores, and tune crop/contrast before processing the full video.

## Extraction procedure

Extract frames from the selected source at a cadence that is faster than the expected command-change rate. Crop every frame to the prompt or input area, optionally enlarging and increasing contrast if characters are small or blurred. Run OCR on the cropped frames, retaining only high-confidence text unless a low-confidence frame is needed to bridge a gap. Normalize whitespace and common OCR confusions, then parse only lines that look like commands for the game or interface: short directions, verb-object phrases, or other known command grammar for the domain. De-duplicate identical consecutive commands because a single entered command may remain visible across multiple frames.

After automated aggregation, manually verify the first few and last few accepted commands against the video timeline. If reference timestamps, walkthroughs, logs, or transcripts exist, use them only as verification anchors, not as a substitute for extracting from the video.

## Stop signal

Stop and reset if, in a ten-frame validation sample from the prompt region, more than two frames either have unreadable command text, OCR confidence below the chosen acceptance threshold, or produce commands that contradict manual inspection. Reset by returning to source selection and crop tuning: obtain a cleaner source if possible, increase crop scale/contrast, adjust sampling rate, rerun the diagnostic checklist, and only then resume full-video extraction.