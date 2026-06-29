---
name: chess-best-move
description: Given an image of a chessboard, detect the board orientation, extract the FEN, and compute the best move using Stockfish. This skill pre-checks required dependencies and provides a robust pipeline.
---

# Chess Best Move from Image

Produce the best move (in UCI notation, e.g., `e2e4`) given a chessboard image file. The pipeline:
1. Read the image and detect board orientation (standard: a8 top-left, white at bottom).
2. Identify pieces by color and position.
3. Generate a FEN string.
4. Feed the FEN to a chess engine (Stockfish) to evaluate and return the best move.

## Dependency Check (guard against missing packages)

Before any processing, verify the following Python packages are installed:

- `opencv-python` (or `cv2`)
- `python-chess`
- `numpy`
- `Pillow`

If any is missing, **print a clear error message** listing the missing package and exit. Do not attempt to install automatically; the user must install them manually.

Example:
```python
import importlib
import sys

required = ["cv2", "chess", "numpy", "PIL"]
missing = [pkg for pkg in required if importlib.util.find_spec(pkg) is None]
if missing:
    print(f"Missing required packages: {', '.join(missing)}. Install with: pip install opencv-python python-chess numpy Pillow")
    sys.exit(1)
```

## Procedure

1. **Load the image** (e.g., `chess_board.png`) using OpenCV (`cv2.imread`). Ensure it is a standard 640×640 or similar square image.
2. **Detect board orientation**: assume the image has a8 in the top-left corner (standard view).
3. **Extract cells**: use grid lines or corner detection to isolate the 8×8 squares.
4. **Classify each square**: determine piece type and color using color thresholding and shape analysis (or a pre-trained classifier). For simplicity, use the known piece colors (white pieces: light, black pieces: dark) and identify piece types based on contours.
5. **Build FEN string**: place pieces in standard FEN order (rank 8 to rank 1, rows from top to bottom). Use `KQBNRP` for white, `kqbnrp` for black. Empty squares are digits.
   - Example output: `r1b1q1r1/1p3pp1/p1n1p3/3nPkb1/8/P1N5/1P3P2/R1B1K3 w - - 0 1`
6. **Validate FEN** using `chess.Board()` from `python-chess`. If invalid, report error.
7. **Compute best move**: run Stockfish (assumed installed and available as `stockfish`) with the FEN. Use depth ≈ 20. Capture the best move from the output.
8. **Output the move** in UCI format (e.g., `c3e2`). Write to a file `/app/move.txt`.

## Output shape

A single line in `/app/move.txt` containing the best move in UCI notation.

## Implementation tips

- Use `subprocess.run` to invoke Stockfish: `stockfish -fen "FEN" -depth 20 --uci` or use the `python-chess` engine wrapper if installed.
- If Stockfish is not available, fall back to a simple checkmate/check evaluation, but prefer to error out if missing.

## When NOT to use this skill

- The input is not an image of a chessboard (e.g., FEN string, PGN file) → use a different skill.
- The chess engine (Stockfish) is not installed → install Stockfish first.

## Reference pipeline (pseudocode)

```python
import cv2, chess, numpy as np
# Dependency check omitted for brevity (must be present)
board_img = cv2.imread("chess_board.png")
# ... processing to extract FEN ...
fen = "r1b1q1r1/1p3pp1/p1n1p3/3nPkb1/8/P1N5/1P3P2/R1B1K3 w - - 0 1"
board = chess.Board(fen)
# Compute best move via Stockfish
import subprocess
result = subprocess.run(["stockfish", "-fen", fen, "-depth", "20", "--uci"], capture_output=True, text=True)
best_move = result.stdout.strip().split("\n")[-1]  # last line is bestmove
with open("/app/move.txt", "w") as f:
    f.write(best_move)
```