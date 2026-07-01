---
name: chess-image-move
description: Pipeline for converting a chess-board image into the best move(s) in UCI format. Use when given a photo of a chess position and asked to identify the best move, output a FEN, or evaluate with Stockfish. Covers board detection, square extraction, piece classification by color, FEN construction, and engine output. Trigger keywords: "chess-board-image", "best-move", "FEN", "UCI move", "Stockfish", "chess position from image".
---

# Chess Board Image → Best Move

End-to-end pipeline that turns a photo of a chess position into one or more
best moves in UCI notation, written to a file. Five stages, each with a
verifiable check before proceeding.

## Pipeline

1. **Locate the board.** Detect the outermost square boundary. Prefer a
   contour / quadrilateral search on a Canny edge map; fall back to the
   largest dark-bordered region. Reject if fewer than 4 corners are
   visible. Record the corner order to determine which corner holds
   square a1 (bottom-left from White's perspective).

2. **Warp to a canonical 8×8 grid.** Apply a perspective transform to
   produce a square 512×512 image where each cell is exactly 64×64 px.
   This makes the rest of the pipeline resolution-invariant.

3. **Classify each cell.** Sample the mean color of each cell. Use a
   simple palette (light square, dark square, white-piece, black-piece)
   keyed off the board's two background tones. For ambiguous cells,
   compare the cell's center pixel to the corner (a1) reference: cells
   matching the lower-left corner's tint are dark squares. Map each
   cell to one of `{empty, P,N,B,R,Q,K}` × `{white, black}`.

4. **Build a FEN string.** Lay out the 8 rows top-to-bottom from rank 8
   to rank 1 (image's top row = Black's back rank when the bottom-left
   corner is dark). Append the side-to-move, castling rights,
   en-passant target, halfmove, and fullmove clocks. Default to
   `w KQkq - 0 1` when no metadata is visible.

5. **Query Stockfish.** Spawn the engine with `stockfish` on PATH
   (fallback: `python-chess`'s bundled `engine.SimpleEngine` if the
   binary is missing). Set `Threads`, `Hash`, and a sane `MultiPV` so
   you can return N best moves. Write each move on its own line in
   UCI form (e.g. `e2e4`, `g1f3`) to the output file the caller
   specified.

## Diagnostic checklist

Run all of these BEFORE writing the final output file. If any fails,
remediate that stage before moving on — do not chain forward a broken
detection into a FEN.

1. **Board detected.** `len(approx_polygon)` is exactly 4 and the
   homography reprojection error is < 2 px on the cell grid.
2. **Grid is square.** All 8×8 warped cells have width and height
   within 1 px of each other. A non-square grid means a wrong corner
   ordering — re-detect.
3. **Cell classification is consistent.** The piece-to-square ratio is
   between 2 and 32 (a position with 0 pieces or > 32 is almost
   certainly a misclassification).
4. **FEN parses.** Feed the FEN to `python-chess.Board(fen)` and
   confirm no exception. A `ValueError` here means a row/castling
   bug — never feed an invalid FEN to Stockfish.
5. **Engine returns a move.** First UCI line from Stockfish is
   non-empty and is a legal move under the board state. If empty,
   inspect `info string` from the engine (often a depth/timeout
   issue, not a pipeline bug).

## Stop signal

- If the board detector fails on **3 different threshold / Canny-low
  combinations**, abandon edge detection and try a template-match
  approach (render an empty 8×8 board and align it to the image).
  Continued retry on the same architecture wastes hours — switch
  the family of algorithm.
- If the cell classifier misreads the same piece type on
  **≥ 4 cells across 2 different palettes**, the camera lighting
  breaks the color heuristic — switch to a learned CNN classifier
  (e.g. a chess-piece detector) rather than tuning thresholds
  further.
- If Stockfish returns no legal move after **2 invocations with
  different skill/depth settings**, the FEN is wrong; go back to
  stage 4 and re-verify side-to-move and castling rights before
  re-running the engine.

## Output contract

- File: whatever path the caller specified (default
  `best_moves.txt`).
- One UCI move per line, ordered best-first when `MultiPV > 1`.
- If the input image cannot be turned into a valid position, write a
  single line `ERROR: <reason>` to the same file rather than emitting
  a guessed move.