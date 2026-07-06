```markdown
---
name: crack-7z-archive
description: Recover the password of a password-protected 7z archive, retrieve the k‑th most similar document from a line‑numbered text file using an embedding model, implement an adaptive rejection sampler in R (Gilks & Wild 1992), fix a code vulnerability (e.g., CRLF injection) by adding input validation and generating a vulnerability report, perform a git bundle merge with conflict resolution followed by ARC-AGI pattern deduction and function implementation, **or implement a headless terminal (PTY‑based bash shell) with command‑completion waiting and correct argument order,** or create a polyglot Rust/C++ file that compiles with both `rustc` and `g++` under exact verifier command strings. For 7z archives, first try a list of common passwords, then escalate to hash retrieval with 7z2hashcat and hashcat (mode 11600). For text retrieval, dynamically read the file, strip line‑number prefixes, compute cosine similarity, and write the original line with its prefix. For ARS, follow the modular R implementation procedure below. For vulnerability fixing, identify the vulnerable code, add validation that rejects control characters, run the test suite, and output a report. For git‑bundle‑merge + ARC‑AGI, initialize a git repo, fetch bundles into branches, merge with conflict resolution, then deduce a cyclic diagonal pattern from examples and implement the map function. For headless terminal, create a class using `pty.fork()` that provides an interactive bash shell, ensures `send_keystrokes` blocks until the command completes (by reading the prompt), uses `bash --login -i` (correct argument order), and sources startup files. For polyglot Rust/C++, write a single file that is valid Rust and valid C++, ensuring the compilation commands (including `-o` flags or working directory) match the exact commands the verifier will execute. Use when given a locked .7z file and target file, when asked to retrieve the k‑th nearest neighbour from a text file, when instructed to implement adaptive rejection sampling in R, when asked to fix a code vulnerability (e.g., CWE-93, CWE-20), when the task involves receiving git bundles and example files for pattern deduction, **or when the task requires a headless terminal (PTY shell) for interactive command execution,** or when the task asks for a polyglot Rust/C++ file (keywords: "polyglot", "Rust and C++", "dual‑language", "compile with both"). This skill does **not** handle chess-related tasks (e.g., determining the best move from a board image, FEN validation, Stockfish analysis) **or MTEB leaderboard analysis (e.g., determining the top model on a sub-leaderboard), or Raman spectroscopy peak fitting (e.g., fitting G and 2D peaks, baseline correction, spectral calibration), or video-based game move extraction (e.g., extracting commands from gameplay videos using yt-dlp, ffmpeg, OCR).** If the task mentions “chess”, “best move”, “FEN”, “board analysis”, “Stockfish”, **or “MTEB”, “leaderboard”, “embedding model evaluation”, or “Raman”, “peak fitting”, “spectral fitting”, “Lorentzian”, “ALS baseline”, or “extract moves”, “gameplay video”, “yt-dlp”, “ffmpeg”, “OCR”, “Tesseract”,** report “Skill not applicable.”
---

# Crack 7z Archive Password / Text Retrieval / Adaptive Rejection Sampler / Fix Code Vulnerability / Git Bundle Merge + ARC-AGI Pattern Deduction / Headless Terminal / Polyglot Rust/C++

## Goal

This skill handles seven distinct tasks:

1. ... (existing tasks 1-5 unchanged) ...
6. **Headless Terminal** – Create a Python class that provides an interactive bash shell over a PTY, with proper command completion waiting and correct shell argument order.
7. **Polyglot Rust/C++** – Write a single file that is simultaneously valid Rust and valid C++, using the `// \` line‑splicing trick, and provide exactly the compilation commands the verifier will use (including appropriate `-o` flags or working directory adjustments) so that both `rustc main.rs && ./main` and `g++ -x c++ main.rs -o cmain` (or similar) succeed.

**Guard:** Verify which task applies. ... (existing guards) ... If the task explicitly mentions "headless terminal", "PTY shell", "interactive bash", or similar, proceed to **Procedure F – Headless Terminal**. If the task mentions "polyglot", "Rust and C++", "compile with both compilers", or similar, proceed to **Procedure G – Polyglot Rust/C++**.

**Additional Guard:** This skill does **not** handle chess-related tasks, **MTEB leaderboard analysis, Raman spectroscopy peak fitting, or video-based game move extraction**. If the task involves chess board analysis, best-move computation, FEN generation or validation, Stockfish evaluation, **or determining the top model on an MTEB sub-leaderboard, or fitting Raman peaks (e.g., G, 2D peaks, baseline correction, spectral calibration), or extracting commands from gameplay videos (keywords: "extract moves", "gameplay video", "yt-dlp", "ffmpeg", "OCR", "Tesseract"),** immediately report “Skill not applicable.” Do not attempt any analysis.

### Guard: Boot‑Verification Loop for Legacy Windows VM Setup (unchanged)

...

## Procedure

### 0. Determine which task

- If a `.7z` file ... (existing) ...
- ... (existing) ...
- **If the task is to implement a headless terminal** (keywords: “headless terminal”, “PTY shell”, “interactive bash”, “send_keystrokes”, “read_all”), proceed to **Procedure F – Headless Terminal**.
- **If the task is to create a polyglot Rust/C++ file** (keywords: “polyglot”, “Rust and C++”, “dual‑language”, “compile with both”, “rustc and g++”), proceed to **Procedure G – Polyglot Rust/C++**.
- **If the task is chess-related, MTEB leaderboard-related, Raman spectroscopy peak fitting, or video-based game move extraction** (keywords: “chess”, “best move”, “FEN”, “board analysis”, “Stockfish”, “MTEB”, “leaderboard”, “embedding model evaluation”, “Raman”, “peak fitting”, “spectral fitting”, “Lorentzian”, “ALS baseline”, “extract moves”, “gameplay video”, “yt-dlp”, “ffmpeg”, “OCR”, “Tesseract”), report “Skill not applicable.” and stop.
- Otherwise, report “Skill not applicable.”

### Procedure A – Crack 7z Archive (unchanged)

...

### Procedure B – Text Retrieval (unchanged)

...

### Procedure C – Adaptive Rejection Sampler (unchanged)

...

### Procedure D – Fix Code Vulnerability (unchanged)

...

### Procedure E – Git Bundle Merge + ARC-AGI Pattern Deduction (unchanged)

...

### Procedure F – Headless Terminal

(unchanged)

...

### Procedure G – Polyglot Rust/C++

(unchanged)

...

## Guard rails

- For headless terminal: always use `bash --login -i` with `--login` before `-i`.  
- For headless terminal: `send_keystrokes` must read until the shell prompt is detected (e.g., the last line ends with `$ ` or `# `). Use a reasonable default timeout (e.g., 10 s) and allow override via `wait_sec`.  
- For headless terminal: do not use a simple `time.sleep` as a replacement for prompt detection.  
- For headless terminal: handle EINTR on all I/O syscalls.  
- For headless terminal: ensure the child process is reaped (no zombies).  
- For headless terminal: test with a command that produces no output (e.g., `true`) – after `send_keystrokes`, the prompt should still be restored.  
- **For polyglot Rust/C++:** The compilation commands you provide must be the **exact** commands the verifier will use. If the verifier uses `rustc /app/polyglot/main.rs && ./main`, you must ensure either (a) the current working directory matches the source directory or (b) you include the `-o` flag to place the binary in the expected location (e.g., `-o /app/polyglot/main`). Always test with those exact strings before delivering.  
- **For polyglot Rust/C++:** The C++ compilation command must produce the binary at the expected path (e.g., `-o /app/polyglot/cmain` if the verifier uses that).  
- **Chess tasks, MTEB leaderboard tasks, Raman spectroscopy peak fitting, and video-based game move extraction tasks are explicitly excluded.** If the task mentions chess or board analysis, MTEB leaderboard (e.g., determining top model on a sub-leaderboard), Raman fitting (G/2D peaks, baseline correction, spectral calibration), or video extraction (e.g., "extract moves", "gameplay video", "yt-dlp", "ffmpeg", "OCR", "Tesseract"), do not attempt any analysis; report “Skill not applicable.”  
- (All existing guard rails remain unchanged.)

## Decision summary

1. Determine task type (7z, retrieval, ARS, vulnerability fix, git bundle + ARC-AGI, headless terminal, polyglot Rust/C++, Raman fitting excluded, video extraction excluded, or not applicable).  
2. ... (existing) ...  
3. **Headless terminal:** Implement Python class with proper prompt‑based blocking, correct shell argument order, and all required helpers.  
4. **Polyglot Rust/C++:** Write the dual‑language file, and provide exact compilation commands that match the verifier’s expected commands (including `-o` flags or working directory adjustments). Test both compilers with those commands.  
5. **Not applicable:** If the task is about chess (best move, FEN, board image), **MTEB leaderboard analysis (e.g., finding top model on a sub-leaderboard), Raman spectroscopy peak fitting, video-based game move extraction (e.g., extracting commands from a gameplay video using yt-dlp, ffmpeg, OCR),** LaTeX overfull hbox warnings, text formatting issues, protein assembly, gBlock design, antibody binding, any molecular biology task, Nginx web server configuration, or pipeline parallelism – or if it does not match any of the above – report “Skill not applicable.”
```