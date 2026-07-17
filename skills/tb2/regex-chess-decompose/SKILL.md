---
name: regex-chess-decompose
description: When generating all legal chess moves via regex transformations on a FEN string, decompose the problem by piece type and special move BEFORE attempting to write any patterns. Avoid trying to write one monolithic regex.
---

# Regex Chess Decomposition

When tasked with generating all legal chess moves through regex transformations over a FEN board string, the failure mode is attempting to write the entire move set in a single pass without decomposition. Chess has six piece types plus four special-move categories; treating them as one problem produces combinatorial explosions, missing edge cases (promotion, en passant, castling through check), and regexes that fight each other.

## Diagnostic Checklist

Before writing any pattern, verify:

1. **Piece-type decomposition** — Have you enumerated each of the six piece types (pawn, knight, bishop, rook, queen, king) as a separate sub-problem, with its own target-square constraints per source square?
2. **Special-move handling** — Are castling (king + rook move, rights update, through-check legality), en passant (target = empty, capture = adjacent pawn), and promotion (four piece choices, last-rank only) each represented as distinct pattern classes rather than folded into general move logic?
3. **State-update coverage** — Does every pattern rewrite not just the board, but also side-to-move, castling rights, and en-passant-target fields of the FEN? A pattern that only updates the board is incomplete and silently wrong.
4. **Bounded pattern budget** — Is the aggregated pattern set below your target size (e.g. <100k entries)? If the count is unbounded or already exceeds the cap at planning time, the enumeration strategy itself is wrong — stop and re-decompose.

## Stop Signal

Stop and re-decompose when any of these is true:

- You find yourself trying to express a "move" as a single regex that simultaneously handles multiple piece types.
- The pattern list grows without an evident upper bound as you enumerate (e.g. unconstrained combinatorics over squares × pieces).
- A test on a known FEN (initial position, "8/8/8/4P3/8/8/8/k6K w - - 0 1", or any standard endgame) returns more or fewer moves than the known legal-move count.
- A pattern fails to update one of: side-to-move, castling rights, or en-passant square — these are silently wrong, not just incomplete.

**Reset action:** Return to the decomposition. Split the failing piece type or special move into its own sub-pattern class. Re-enumerate source-target pairs explicitly, applying board-edge and capture-square constraints before translating each pair to regex. Only after every sub-class is bounded and tested in isolation should patterns be aggregated.