---
name: chess-vision
description: Reconstruct a chess position from a board image and select the best legal move. Use when given a chess board photo/diagram (PNG/JPG) and asked for the optimal move. Covers 8x8 grid segmentation, piece color/type classification via pixel clustering and shape heuristics, and tactical scoring via defender-attacker counts. Prevents the failure mode where the agent commits to a move search on a *wrongly reconstructed* position — double-check piece types and legal-king status BEFORE picking a move.
---

# Chess Vision: Board Reconstruction and Best-Move Selection

This skill guards against the recurring failure: the agent reaches a move-search step while the underlying board reconstruction is still wrong (misidentified piece types, illegal king-in-check, wrong side-to-move). Always validate the position before searching.

## Procedure

### 1. Segment the board
- Compute `square = image_width / 8` (assume the board fills the frame; if not, locate the largest 8x8 grid of alternating squares first).
- Sample **interior** pixels per square, skipping a ~10% border to avoid grid lines and shadows.
- Confirm the two alternating board colors each appear on exactly 32 squares — a strong sanity check that segmentation worked.

### 2. Classify occupancy and piece color
- Cluster interior pixel colors by rounding to the nearest 10s.
- Empty square → dominated by one of the two board colors.
- Occupied square → look at the **outer ring** of pixels to determine piece color (light/white vs dark/black), not the inner shape.

### 3. Classify piece type with shape heuristics
- king: cross-like outline
- queen: crown-like top, broad
- rook: blocky, flat top
- bishop: pointed top, often with a slit
- knight: asymmetric L-shape
- pawn: small, low in the square

Cross-check with structural constraints:
- Pawns never appear on rank 1 or rank 8.
- Bishops stay on their starting square color throughout the game.
- Exactly one white king and one black king.

### 4. Validate the reconstructed position
- Total piece count ≤ 32, ≥ 2 (the two kings).
- Side-to-move is consistent (you can infer it from whose move it usually is, or from the prompt).
- If any king appears to be "in check", check whether the alleged checker could realistically give check from that square. If not, the board state is wrong — re-examine piece types and colors before proceeding.

### 5. Score candidate moves
For each pseudo-legal capture or check:
- Compute **defender-attacker delta** on the destination square: count friendly defenders minus enemy attackers.
- Prefer moves that capture material (attacker advantage on the destination).
- Tie-break with tactical motifs: fork (one move attacks ≥2 enemy pieces), pin, skewer, discovered attack.
- Reject any move that leaves your own king in check — re-verify after applying the move.

## Diagnostic checklist (run BEFORE committing to a move)

1. Render the reconstructed position as ASCII or a short FEN string; confirm both kings are present on legal squares.
2. List every occupied square and verify no pawns sit on rank 1 or 8, and exactly one king per side.
3. Pick one likely capture, manually count attackers and defenders for both sides, and confirm the tactical scoring function returns the same winner a human would pick.
4. Apply your chosen move and re-run king-safety for the side that just moved. The king must not be in check after the move.

## Stop signal

- If you have written **two** versions of the piece classifier and they disagree on ≥3 squares of the same board image, abandon pure pixel-clustering and switch to template matching or a small CNN — clustering alone cannot reliably distinguish visually similar pieces (e.g. white-bishop vs white-pawn).
- If your chosen move leaves the king in check, **do not** tweak the scoring function. The board reconstruction is wrong — return to step 2 and re-classify squares, not moves.
- If you find yourself writing a third move-ranker that contradicts the second, stop and validate the position instead of iterating on search.