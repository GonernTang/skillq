---
name: regex-chess-edges
description: Build a regex-based chess move generator that handles all piece types, castling/en-passant/promotion, legality filters, and exact output format. Use when implementing FEN-to-legal-moves via regex or any regex move enumeration that must pass strict verifiers.
---

# regex-chess-edges

When the task is "given a FEN, emit all legal moves using regex" (or a regex-driven move enumeration with a strict format verifier), local tests almost never cover every edge case the verifier checks. Build defensively: enumerate edge cases first, then write the regex.

## Diagnostic checklist

Run these BEFORE committing to a regex structure:

1. **Piece coverage matrix.** Enumerate every piece type *separately* (P/p, N/n, B/b, R/r, Q/q, K/k) and confirm each has a distinct move subpattern. Pawns need both push and capture directions; knights need L-shapes; sliders need ray scans; king needs 8-neighborhood *plus* castling.
2. **Special-move coverage.** Confirm the regex handles: castling (with rights that survive only if neither king nor that rook has moved), en-passant (only when an adjacent enemy pawn exists — clear the target square otherwise), and promotion (only to queen, on the correct rank).
3. **Legality filter present?** After generating pseudo-legal moves, every move must be tested for "does my king remain in check?" A regex that omits this filter will over-emit and fail the verifier. Implement the filter even if the spec doesn't mention it.
4. **Output format match.** Verify the exact expected shape: side-to-move flipped to the opposite color, halfmove/fullmove counters as *placeholders* (e.g., `0 1`), move string format (UCI vs SAN vs custom). The verifier is byte-exact — diff against a reference sample.

## Stop signals

- **Threshold:** If pseudo-legal generation produces more than ~40 candidate moves from a midgame position, you have *not* applied the legality filter or are double-counting. Treat any count that exceeds the known legal-move total for that FEN as a hard failure.
- **Threshold:** If the regex uses `^`/`$` against a multi-line FEN board without the `(?m)` flag, or substitutes via `\g<0>` inside `re.sub` (Python expects `$0`), stop and fix the anchor/back-reference before testing more positions.
- **Reset action:** When any verifier-failing case is found, *do not* patch the failing piece in isolation. Re-walk the full edge-case matrix (start position, position with all 4 promotions available, kings-only endgame, castling-through-check, en-passant-when-no-adjacent-pawn, pinned piece). A one-piece fix usually breaks another.

## Implementation notes (avoid repeating these specific bugs)

- Pawn captures are *diagonal*; pawn pushes are *forward* — don't conflate them in one alternation.
- En-passant target square must be validated by checking the adjacent file for an enemy pawn, not just by parsing the FEN's ep field.
- Clear the en-passant field on every move that is not a 2-square pawn push; leaving stale ep fields breaks downstream FEN parsing.
- Promotion moves are four distinct legal moves (one per underpromotion piece) even if the task says "queen-only output" — generate all four, then filter.
- Castling legality requires: rights bit set, neither piece has moved, squares between king and rook empty, king not in check, king not passing through check, king not landing in check. A regex alone cannot compute the check conditions — pair the regex with a small follow-up validator.

**Why this skill exists:** An earlier agent shipped a regex-chess generator that passed the local starter tests but failed the verifier on positions with multiple promotions, complex check detection, exact counter placeholders, or stale en-passant squares. The pattern of failure was "local tests were too narrow" — this skill forces an edge-case sweep before the regex is written.