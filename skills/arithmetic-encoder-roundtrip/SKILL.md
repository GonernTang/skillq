---
name: arithmetic-encoder-roundtrip
description: When building an encoder that must produce a bit stream decodable by a given arithmetic/range decoder, simulate the decoder's state forward and reverse-engineer the required fraction, verifying every step. Use before committing to constraint-propagation or simulation-based encoding for custom range/arithmetic codecs.
---

# Arithmetic Encoder Round-Trip Discipline

When implementing an encoder for a custom arithmetic/range decoder, the encoder must produce a bit stream that exactly drives the decoder to the desired symbols. Approximate or symbolic reasoning about the bit stream is unsafe — small mistakes in tracking the interval `(low, high)`, range, or context transitions silently produce bytes that decode to garbage. The cure is to treat the decoder as the spec and mirror it bit-for-bit.

## Diagnostic checklist

Run ALL of these BEFORE committing to the encoder's main loop:

1. **Decoder state is concrete.** List in code every state variable the decoder advances at each step (fraction, range, counts, cumulative signed sum `S`, context boundaries). If you cannot enumerate them explicitly, the encoder cannot mirror them.
2. **Bit order and context-transition order are pinned.** For each symbol class (literal, match flag, offset, length), write down the exact sequence of bits the decoder consumes and the order of context switches. Bit-order drift between encoder and decoder is the most common silent corruption.
3. **Split threshold computable per bit.** Given the current `(low, high, range, counts, S)`, derive the integer threshold that separates one symbol's interval from the next on paper for a single example. If you cannot compute it for one bit by hand, the encoder logic is wrong.
4. **Encoded byte lies inside the required interval.** After the last bit, verify the chosen encoded value's interval contains the decoder's final fraction for the intended symbol sequence. The value must not land outside `(low, high)` after renormalization.

## Stop signal

If, after implementing, you cannot reproduce the decoder's `(fraction, range)` state bit-for-bit on a hand-traced input of length ≤ 4 symbols, **STOP**. Do not add more symbols or scale the input — the propagation of `S` (or any cumulative tracker) across context boundaries is broken. Reset and re-derive `S` from scratch using single-step forward simulation; do not attempt to patch the propagation algebraically without first matching a 1-symbol round trip.

## Core discipline

- Implement forward simulation first: walk the decoder step by step, recording `(fraction, range, S, counts)` at each bit. Treat this record as ground truth — never reason about the encoder in isolation from the decoder.
- After any context transition (e.g. literal → match), re-derive `S` from the new state. Do not carry cumulative trackers across boundaries assuming continuity.
- Verify the final encoded byte by feeding it to the decoder and asserting the recovered symbols match the original input exactly, before considering the encoder correct.
- When using constraint propagation on `(low, high)`, explicitly compute the expected split threshold for each bit from current counts and range, and confirm the encoded byte fully determines a fraction inside the required interval at every step.