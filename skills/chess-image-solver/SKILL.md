---
name: chess-image-solver
description: Solve chess best-move problems from a board image by detecting pieces, building a FEN, and using python-chess to find the best move.
---

# Chess Best-Move from Board Image

Given a chess board image and asked for the best move(s), follow this pipeline:

## 1. Load the image and determine orientation
- Load with Pillow (`PIL.Image.open`).
- Assume standard orientation: **a8 = top-left, h1 = bottom-right**. If the image shows coordinates, confirm; otherwise this is the default.
- Trim any margin/padding so the 8×8 grid fills the working area. If the image is square (e.g., 640×640), each square is `size / 8` pixels.

## 2. Sample the 8×8 grid
- For each square `(file, rank)` where file ∈ {a..h}, rank ∈ {1..8}:
  - Compute pixel bounds: `(x0, y0, x1, y1)`.
  - Map file → column index left→right, rank 8 → row 0 (top), rank 1 → row 7 (bottom).

## 3. Detect piece presence
- For each square, compare pixel colors against the expected background:
  - Light squares: ~ `(240, 217, 181)` (or similar cream).
  - Dark squares: ~ `(181, 136, 99)` (or similar brown).
- A square is empty if pixels are close to the background color.
- A square has a piece if it deviates significantly (e.g., piece silhouette has noticeably different color/brightness).

## 4. Classify piece type
Use heuristics on the piece pixels within the square:
- **Vertical profile (height)**: kings are tallest, pawns shortest. Compute the bounding-box height of non-background pixels.
- **Asymmetry**: knights have high left/right asymmetry (head shape). Bishops are tall and narrow. Rooks are blocky. Queens combine height and width. Kings are tallest with a cross on top.
- **Width profile**: rooks are wide; bishops narrow; pawns narrow at base.
- Use a small lookup table mapping (height_bin, width_bin, asymmetry_bin) → piece symbol.
- Calibrate thresholds against a few known squares if uncertain.

## 5. Identify piece color
- Sample brightness near the square center.
- White pieces: very bright pixels (>200 average).
- Black pieces: dark pixels (<80 average).
- Choose the dominant color in the piece region.

## 6. Construct a FEN string
- For each rank from 8 down to 1, walk files a..h:
  - Emit piece letter (uppercase = white, lowercase = black) or count empty squares.
  - Append `/` between ranks.
- Append board-state fields: ` w - - 0 1` (side to move, castling, en passant, halfmove, fullmove). Adjust side-to-move based on context (default to white to move unless problem says otherwise).

## 7. Verify with python-chess
- Use `chess.Board(fen)` to parse.
- Iterate `board.legal_moves` to confirm the position is consistent. If many "illegal" squares are detected, revisit detection — especially side-to-move and king counts (each side must have exactly one king).

## 8. Evaluate moves
For each legal move, evaluate in this priority order:
1. **Checkmate** — `board.is_checkmate()` after the move. Collect all mating moves.
2. **Check** — moves that give check (`board.is_check()`).
3. **Captures** — moves that capture opponent pieces, weighted by victim value (P=1, N/B=3, R=5, Q=9).
4. **Material balance** — net gain from the move.

If any checkmate exists, output all of them. Otherwise, output the single best move (or top few by evaluation).

## 9. Write the output
- Format each move as `[src][dst]` in algebraic notation (e.g., `e2e4`, `g1f3`).
- Write one move per line to the specified output file.
- If multiple winning moves exist, list all of them.

## Implementation tips
- Use `python-chess` for legality, SAN conversion, and move generation — do not roll your own.
- Use Pillow (`Image.open`, `.getpixel`, `.crop`) for image work; no need for OpenCV.
- When in doubt about piece identity, prefer to mark the square as containing the most common piece for its color/silhouette rather than empty — an extra piece is easier to debug than a missing one, and `Board(fen)` will reject obvious illegalities (e.g., two kings of same color).
- Print intermediate FEN to stderr for debugging.

## Dependencies
- Python 3
- `Pillow`
- `python-chess`