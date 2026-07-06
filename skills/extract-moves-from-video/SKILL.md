---
name: extract-moves-from-video
description: Extract discrete game moves or commands from a gameplay video. Triggers when the task is to transcribe gameplay commands from a YouTube/video source (e.g., Zork, MUDs, interactive fiction, terminal-style games), or when the task requires converting visual game input into a structured command list. Provides a multi-stage pipeline: download, frame extraction, multi-modal capture (OCR + ASR), deduplication, and validation against the game's canonical verb-noun vocabulary.
---

# extract-moves-from-video

## When to use

Use this skill when a task asks you to extract a sequence of player
commands (moves, inputs) from a video of someone playing a game —
particularly text/parser games like Zork, MUDs, or interactive
fiction where commands follow a `VERB NOUN` (or `VERB PREPOSITION NOUN`)
pattern. Do NOT use this for action games where the "move" is a
pixel trajectory or button mash — that requires a different
extraction strategy.

## Failure pattern to avoid

OCR on video frames alone is unreliable for command extraction. The
known failure mode: agents run Tesseract / EasyOCR over hundreds of
video frames and emit whatever text appears, producing:

- Duplicated commands (same frame's text captured at adjacent timestamps).
- Misread characters (e.g., `east` → `easf`, `take lamp` → `taKe larrp`).
- Hallucinated lines from in-game narration, subtitles, or HUD elements
  that are not player commands.
- Numbered prefixes (e.g., `1. north`) when the expected format is
  bare commands, one per line.

Do not ship an OCR-only output as the final answer.

## Procedure

1. **Download** the video at the lowest resolution that still keeps
   the command line legible (often 480p is enough; 1080p wastes OCR
   time). Prefer direct URLs over scraping; if only a YouTube link
   exists, use `yt-dlp -f "worst[height<=480]" -o video.mp4 URL`.

2. **Sample frames sparsely**. A command is held on screen for
   ~2–5 seconds in most gameplay recordings. Extract one frame per
   ~1.5s, NOT per video frame, to bound OCR work. Use
   `ffmpeg -vf fps=1/1.5 frame_%04d.png`.

3. **Multi-modal capture (mandatory)**: run BOTH:
   - OCR on the sampled frames (Tesseract or EasyOCR).
   - Speech-to-text on the audio track (`whisper video.mp4`).
     Players often speak or type-aloud commands; ASR catches what
     OCR misses when the command line is small or rendered with
     anti-aliasing.

4. **Normalize & merge** the two streams:
   - Lowercase, strip whitespace and punctuation except hyphens.
   - Drop empty lines, narration ("you are standing in…"), and lines
     that look like game responses rather than inputs.
   - Deduplicate consecutive identical lines (same command held on
     screen counts once).

5. **Validate against canonical command vocabulary** for the game.
   For Zork/MUDs this is roughly `north|south|east|west|up|down|look|
   inventory|take <obj>|drop <obj>|open|close|read|examine|use|put|
   attack|kill|wait|save|restore|quit|...`. Flag any extracted line
   that contains no recognizable verb, OR a verb not in the
   vocabulary — these are OCR/ASR artifacts and must be reviewed
   before inclusion.

6. **Format output** exactly as requested: typically one command per
   line, no numbering, no surrounding markdown, no commentary.

## Diagnostic checklist

Before declaring the extraction done, run these checks:

1. **Spot-check 3 known commands**: from the video (or game docs),
     pick 3 commands you know should appear (e.g., the first move,
     a distinctive mid-game move, the final move). Verify all 3
     are present and spelled correctly in the output.
2. **Count check**: the number of extracted commands should be within
     ±20% of the expected count for the video length (rough heuristic:
     video_seconds / average_seconds_per_move, typically 10–30s/move).
3. **Vocabulary scan**: every line in the output must contain at
     least one token from the canonical verb list. Lines that fail
     this check are noise — review and either fix or remove.
4. **No duplicates / no numbering**: `sort | uniq -c` should show
     no count > 1 (commands are not auto-incremented); `grep -E '^[0-9]+[.)] '`
     must return nothing.

## Stop signal

If, after running the procedure once, fewer than 70% of extracted
lines pass the vocabulary scan OR fewer than 2 of the 3 spot-check
commands are present: do NOT iterate on the same OCR pipeline.
Switch strategy: re-run with a different frame-sampling rate (try
1/3s instead of 1/1.5s), swap OCR engine (EasyOCR → Tesseract LSTM
mode, or a vision LLM), or lean more heavily on the ASR stream and
treat OCR as confirmation. If two full strategy switches still
fail the spot-check, escalate — the video quality is likely too low
and you should report that rather than fabricate a command list.