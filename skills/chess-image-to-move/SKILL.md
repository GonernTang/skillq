---
name: chess-image-to-move
description: Guard rail for chess "best move from image" tasks. Enforces a strict pipeline (image → FEN → engine query → formatted output) and prevents the common failures of skipping board extraction, omitting the side-to-move field, misreading the required notation (UCI vs SAN), or outputting only one move when multiple are requested.
---

# Chess Best-Move From Image — Guard Rail

When the task is "given a chess board image, output the best move(s)", follow this pipeline in order. Do not skip steps, do not guess the FEN, and do not invert the notation.

## 1. Read the requirements first

Before touching the image, lock down:

- **Output notation**: UCI (`e2e4`, `g1f3`) vs SAN (`e4`, `Nf3`). These are not interchangeable — graders typically check for exactly one.
- **Output count**: exactly one move, top N moves, or all "best" moves within some eval tolerance.
- **Output destination**: a specific file path, stdout, or a JSON blob. Write to that exact location.
- **Side to move**: implied by the task, not by you. Look for phrases like "White to move" or infer from whose turn it appears to be.

State these constraints in a comment/header before producing output.

## 2. Extract the board to FEN

Build the Forsyth–Edwards Notation string from the image. Do not skip this — never feed pixel data directly to an engine.

- Detect squares (8×8 grid, consistent cell size).
- Classify pieces by **color** and **type** using color segmentation and thresholding; light vs dark squares differ in tone, so normalize per-cell before sampling.
- Output exactly six space-separated fields: `piece-placement side castling en-passant halfmove fullmove`.
  - For "find the best move" tasks, side is typically `w` (White) unless the task states otherwise.
  - Castling rights default to `-` unless rooks/king are clearly unmoved.
  - En-passant target defaults to `-` unless a pawn just advanced two squares.
- Verify the resulting FEN is legal (no pawns on rank 1/8, both kings present, no side in check from the opposite color's own move).

## 3. Query the engine

Use a programmatic chess library (`python-chess` is the standard). Do not try to "reason" about chess moves in natural language.

- Load the FEN: `board = chess.Board(fen)`.
- Confirm `board.turn` matches the expected side to move.
- Compute candidates — pick one:
  - `board.legal_moves` filtered by simple heuristics (captures/checks first) for a quick answer, OR
  - a shallow search with `chess.engine.SimpleEngine` if Stockfish is available, OR
  - iterate `legal_moves`, play each, evaluate via material/positional heuristic, sort.
- Sanity-check: if the top move leaves the side-to-move's own king in check, discard it.

## 4. Format the output

Format **after** selecting the move, not before.

- If UCI was requested: `move.uci()` → lowercase, no spaces, source-square then target-square (e.g. `e2e4`, `e7e8q` for promotions).
- If SAN was requested: `board.san(move)` from the *original* board position (calling `san` on a mutated board gives wrong notation).
- One move per line, no commentary, no `bestmove:` prefix unless the task spec demands it.
- For multiple-move tasks, output them in descending strength order, one per line.

## 5. Verify before writing

- Re-parse the FEN and confirm the chosen move is in `legal_moves`.
- Confirm the file written matches what a grader would read (path, encoding, trailing newline).
- Print (to stderr/log) the FEN used and the engine's eval so failures are debuggable.

## Common failure modes to avoid

- Outputting SAN when UCI was required (or vice versa) — string-comparison graders fail silently.
- Forgetting the FEN's side-to-move field — engine computes the move for the *opposite* side.
- Omitting the en-passant target when relevant — silently changes legality of certain pawn moves.
- Only producing one move when the task asked for top-N.
- Guessing moves without an engine because "the position looks obvious" — looks-obvious positions often have tactical solutions a heuristic misses.
- Treating the image's perspective (White at bottom vs top) as fixed; confirm before flipping ranks.

## Minimal pipeline sketch

```python
import chess
# 1. image -> FEN (via your detector)
fen = "<extracted-fen>"
# 2. load
board = chess.Board(fen)
assert board.turn == chess.WHITE  # or BLACK, per task
# 3. pick best legal move (heuristic or engine)
best = max(board.legal_moves, key=lambda m: evaluate(board, m))
# 4. format
print(best.uci())   # or board.san(best) for SAN
```