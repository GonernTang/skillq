---
name: video-game-move-extraction
description: Extract player commands/moves from gameplay videos of text-based games (Zork, Adventure, Colossal Cave, Inform 7 titles, MUD clients, BBS door games) when given a video URL or file. Covers yt-dlp download, subtitle probing, frame-sampling OCR with Tesseract, prompt-line filtering, and verb-validation. Use when asked to "extract moves from video", "transcribe a Zork playthrough", "get player commands from gameplay", "dump commands from a text-adventure recording", or any task that must turn pixel-time into a flat list of typed commands.
---

# Video Game Move Extraction

Text-based game videos are mostly screen + small text window. Pixel noise (video codec, scaling, fonts, subtitle burn-in) is the dominant failure mode — not the OCR engine itself. Pin down the prompt character and the verb vocabulary before scaling OCR to the full video.

## Diagnostic checklist (run BEFORE committing to the OCR pipeline)

1. **Probe for subtitles first.** Run `yt-dlp --list-subs <url>` (or equivalent) before any OCR. If `.vtt`/`.srt`/`.ttml` tracks exist, download them — they are 100% accurate and make OCR unnecessary. Record in your notes whether subtitles existed; this is your fallback plan if OCR misfires later.
2. **Sample 3 frames at different timestamps** (start, middle, end) and OCR each *before* scaling to the full video. Confirm the prompt character (e.g., `>`, `>`, `*`, `-->`) is consistently detected. If it is not, your prompt regex is the bug, not the OCR.
3. **Validate the verb vocabulary.** Inspect ~10 candidate commands and check against the game's known verb list (Zork: `north`, `south`, `east`, `west`, `up`, `down`, `get`, `drop`, `inventory`, `open`, `close`, `read`, `look`, `examine`, `put`, `insert`, `unlock`, `light`, `attack`, `kill`, `wait`, `score`, `save`, `restore`, `quit`). If <50% of candidates are known verbs, you are extracting narration, not commands.
4. **Spot-check timestamp alignment.** Pick one turn you can recognise from the video (first move, a title card moment, an obvious room-change). Confirm the extracted command appears in frames near that timestamp. If not, your frame-sampling rate is wrong — too coarse misses inputs, too dense yields duplicates.

## Procedure

1. **Download** the video:
   ```
   yt-dlp -f "bv*+ba/b" --merge-output-format mp4 -o video.mp4 <url>
   ```
   If subtitles were detected in step 1, also run `yt-dlp --write-auto-subs --convert-subs srt --skip-download -o subs <url>` and stop here if subs are dense enough.
2. **Extract text**:
   - From subtitles: parse `.srt` and concatenate text blocks in time order.
   - From video: sample frames at ~1 fps (`ffmpeg -i video.mp4 -vf fps=1 frame_%04d.png`) and run `tesseract frame_*.png stdout --psm 6` for each frame. Concatenate per-frame text in timestamp order.
3. **Parse for commands**:
   - Identify the prompt character dynamically from the first OCR pass — do not hardcode. Normalise visual variants (`>`, `>`, `>`, fullwidth `＞`).
   - For each prompt occurrence, take the text immediately following it on the same line as one player command.
   - Discard narration lines (no leading prompt) and status lines (blank-score, room descriptions).
4. **Deduplicate and filter**: Adjacent frames will repeat the same command. Keep the first occurrence per burst; collapse consecutive identical lines. Drop anything that does not start with a known verb (allow common prefixes like `again` or `g`).
5. **Write the output**: one command per line, in chronological order, no timestamps unless the user asked for them.
6. **Verify**: spot-check the first 10 and last 10 commands. Compute the fraction matching known verbs. If <70%, revisit the prompt regex and sampling rate before declaring done.

## Guard rails

- **Subtitles beat OCR.** Always check for subtitles first. OCR is a fallback, not the default.
- **The prompt character is your anchor.** Every command in a text adventure is preceded by a prompt. If your extractor produces narration, the prompt regex is wrong, not the OCR engine.
- **Frame sampling rate matters.** ~1 fps is a good starting point for text adventures. Going denser (e.g., 5 fps) produces heavy duplicates without catching more inputs.
- **Varying video quality is normal.** Low resolution, retro fonts, scanlines, and burn-in subtitles all degrade OCR. Pre-process: upscale 2x (`ffmpeg -vf scale=iw*2:ih*2`) before `tesseract`, use `--psm 6` (uniform block), and consider `--oem 1` (LSTM) for clean monospace.
- **Prompt formats vary by game.** Zork uses `>`; many MUDs use `*` or a colored prompt that OCR drops entirely; some BBS door games use `-->` or a custom symbol. Detect once, then reuse — do not re-discover per frame.
- **Burn-in subtitles are a noise source.** If the video has burned-in commentary subtitles, filter them out (they typically appear in the lower third and use a different font from the game text).
- **Multi-window layouts exist.** Some playthroughs record the terminal plus a chat window, browser, or facecam. Crop or threshold to the terminal region before OCR — full-frame OCR will mix chat with commands.

## Stop signal

If after **two full OCR passes** with different `--psm` settings and frame-sampling rates the verb-match rate is still below 50%, **stop tuning Tesseract.** The video almost certainly has subtitles you missed (re-run `yt-dlp --list-subs` with `--all-subs` and check manual subs), or the prompt character is being eaten by the codec/font. Do not iterate a third time. Switch to one of:

- Manual anchor extraction: pick 10–20 frames at obvious turn boundaries (room descriptions, inventory changes, score changes), OCR only those, and infer the intervening commands from the room/state log.
- Report partial results with an explicit caveat and a sample of the noise (so the user can decide whether to retry).
- Ask the user for a better source (e.g., a transcript, the original save file, or a higher-resolution recording).