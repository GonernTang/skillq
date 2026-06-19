---
name: use-domain-tools
description: Reach for specialized, domain-specific libraries and tools (OCR engines, chess engines, ML classifiers, parsers) before reinventing solutions from low-level primitives like pixel math, regex, or hand-rolled heuristics.
metadata:
  type: feedback
---

# Use Domain-Specific Tools First

## The failure pattern

When facing a task in a specialized domain (chess, OCR, audio, 3D, scientific computing, board games, document parsing, etc.), the model often tries to solve it from low-level primitives:

- Chess position recognition → manual pixel color thresholding on board squares
- OCR → hand-rolled template matching instead of Tesseract / EasyOCR / PaddleOCR
- Audio transcription → custom signal processing instead of Whisper
- PDF extraction → raw byte parsing instead of `pypdf` / `pdfplumber`
- Stockfish move calculation → hand-coded minimax instead of invoking the engine
- Table extraction → regex on whitespace instead of `camelot` / `tabula`

This fails because domain problems have decades of accumulated edge cases (artwork on pieces, varied lighting, fonts, formats, board orientations, en passant, promotions) that low-level approaches cannot capture reliably.

## Guard rail — before starting the task

1. **Identify the domain** of the input and the desired output. State it explicitly: "This is a chess-position-recognition problem" or "This is an OCR-on-rendered-text problem."
2. **Check for a canonical toolchain** in that domain. Common signals:
   - A named library with the domain in its name (`python-chess`, `chessboard`, `Pillow + chessboard`).
   - An industry-standard engine (`Stockfish`, `Tesseract`, `Whisper`, `Surya-OCR`).
   - A pretrained model or classifier for that exact modality.
3. **Pick the specialized tool first.** Only fall back to primitives if no specialized tool is available, or as a preprocessing step feeding into the specialized tool.

## Guard rail — during implementation

- **Do not "just check pixels"** for visual recognition. Even quick prototypes should use OpenCV / a classifier / a domain OCR library so the same code path scales.
- **Do not write a search algorithm from scratch** when an engine exists for the game or puzzle. Wrap the engine; don't replace it.
- **Compose, don't replace.** A typical pipeline is: specialized-recognizer → structured representation (e.g., FEN, JSON, AST) → specialized-processor (engine, parser, compiler).
- **Validate the structured intermediate.** If you produce a FEN, an AST, or a JSON schema, parse it back and assert validity before feeding it to the next stage. Silent garbage-in silently produces garbage-out.

## Decision checklist

Before committing to a low-level approach, answer:

- [ ] Is there a well-known library whose name contains the domain?
- [ ] Is there an engine / pretrained model that solves this exact subproblem?
- [ ] Have I checked PyPI / npm / crates.io for `<domain>` packages?
- [ ] If I must use primitives, am I at least feeding them into a specialized downstream tool?

If any answer is "yes, but I skipped it," stop and switch to the specialized tool.

## When primitives ARE appropriate

- The domain is genuinely novel and no library exists.
- The specialized tool is unavailable in the runtime (missing binary, no network, no install permission) — and even then, document the substitution.
- You are building a teaching example where the whole point is to expose the primitives.
- The specialized tool fails on your specific input and you have a justified, tested fallback.

## How to apply

When you read a task and start forming an approach, pause and ask: "What is the *domain*, and what is the canonical tool for it?" Make that question a habit before writing the first line of recognition or processing code. The specialized tool almost always beats the manual approach on correctness, edge cases, and total time spent.