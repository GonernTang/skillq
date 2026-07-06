---
name: feal-linear-cryptanalysis
description: Step-by-step guide for performing linear cryptanalysis on a FEAL-like 4-round Feistel cipher with a small per-round key seed. Covers constructing a linear approximation table for the G function, finding high-bias linear expressions across rounds, and recovering round subkeys one at a time by counting bias over known plaintext-ciphertext pairs with partial last-round decryption.
---

# Linear Cryptanalysis of a 4-Round FEAL-Like Cipher

Use this procedure when attacking a FEAL-style Feistel cipher with:
- 4 rounds
- A small per-round subkey seed (e.g. 20 bits)
- A G function defined as `g(a, b, x) = ROL2((a + b + x) mod 256)`
- Known plaintext/ciphertext pairs available in volume

## 1. Model the Round Function

For each round `i`:
- Split the 32-bit half-state into four bytes: `L0, L1, L2, L3`
- Compute the new right half as `R' = L XOR (g(L0, L1, K_i) || g(L1, L2, K_i) || g(L2, L3, K_i) || g(L3, L0, K_i))`
- Apply the standard Feistel swap for the next round

Confirm the encryption is given (or recoverable) so you can derive the inverse for partial decryption of the last round.

## 2. Build the Linear Approximation Table (LAT) for G

For the G function `g(a, b, x) = ROL2((a + b + x) mod 256)`:
- For every mask pair `(input_mask, output_mask)` on the 8-bit input/output, compute the correlation `(2 * count_true - 2^bits) / 2^bits` over all `(a, b, x)` triples
- Identify masks with the largest absolute bias — these are the building blocks of high-bias linear trails across rounds
- Store the bias `ε(input_mask -> output_mask)` keyed by `(input_mask, output_mask)`

Useful approximations to look for first: linear relations tying one output bit of one G call to specific input bits — for example, expressions where a single output byte bit depends on only a few input bits with strong bias.

## 3. Compose a Linear Expression Across 4 Rounds

Chain G-function approximations through the Feistel structure so that internal state variables cancel. The goal is an expression of the form:

`⟨mask_p, P⟩ XOR ⟨mask_c, C⟩ = constant · K_0 ... K_3 (mod 2)`

where P is the plaintext, C is the ciphertext, and the right side depends on round keys. The combined bias follows the piling-up lemma: `ε_total ≈ 2^(n-1) · Π ε_i` over `n` active S-boxes.

Aim for `|ε_total| > 1/√N` where N is the number of available known pairs.

## 4. Recover the Last-Round Subkey (K_3)

For each candidate subkey group (e.g. one byte at a time, keeping the rest fixed):
1. Partially decrypt one round backwards from the ciphertext, using the candidate subkey, to recover the penultimate-round state.
2. Evaluate the linear expression for every known pair using this partially decrypted state.
3. Count how often the expression equals 0 versus 1.
4. Compute the bias `|count_0 - count_1| / N`.
5. The correct subkey (or byte group) yields a bias close to the theoretical `|ε_total|`; wrong keys produce bias near zero.
6. Pick the candidate with the largest absolute bias.

If the key space per round is too large for brute force (e.g. 20 bits = ~1M candidates), exploit byte-wise independence: recover one byte of K_3 at a time by choosing linear expressions that isolate that byte.

## 5. Peel Back to K_2, K_1, K_0

With K_3 known, repeat the same procedure targeting the linear expression's dependence on K_2:
- Partially decrypt two rounds from the ciphertext using K_3.
- Score K_2 candidates (or byte groups) by recomputing the linear expression bias.

Repeat for K_1 (three rounds of partial decryption) and finally K_0 (full decryption back to plaintext). At each step, the number of partial-decryption rounds grows by one and the bias should sharpen against the known `ε_total`.

## 6. Verify and Decrypt

Once all four round subkeys (four 20-bit seeds) are recovered:
1. Reconstruct the full key schedule.
2. Decrypt every ciphertext using the standard Feistel decryption.
3. Spot-check a few pairs against the known plaintexts to confirm correctness.
4. A successful attack shows decrypted ciphertexts whose statistical profile (byte distribution, repetition patterns) matches the expected plaintext domain.

## Practical Notes

- 20-bit key search per byte group is feasible; full 80-bit per-round brute force is not — always work byte-wise.
- Use at least `1/ε_total²` known pairs; a few thousand pairs are usually enough for FEAL-4 since the combined bias is large.
- Implement the LAT once and reuse it for every key-recovery pass.
- When biases are noisy, plot `count_0 - count_1` per candidate and pick the clearest outlier rather than relying on a single max.