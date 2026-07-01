---
name: feal-differential-attack
description: Perform a chosen-plaintext differential cryptanalysis attack on a FEAL-like Feistel cipher where round keys are derived from low-entropy (e.g. 16-bit) seeds. Use when given an unknown key, a black-box encrypt oracle, and a Feistel structure whose F-function has a known high-probability (ideally probability-1) differential. The procedure uses the differential to force a predictable ciphertext difference after a small number of rounds, then brute-forces the last round key by partial decryption, requiring only a handful of chosen plaintexts.
---

# FEAL Differential Cryptanalysis — Last Round Key Recovery

## When to apply
- Cipher is a Feistel network with an F-function for which you know (or can derive) a high-probability input/output differential.
- Round keys are derived from low-entropy seeds (e.g. a 16-bit integer expanded into a full round key by a known multiplier/expansion), so brute-forcing the seed space is feasible (~2^16).
- You have a chosen-plaintext encryption oracle under an unknown fixed key.
- Target: recover the seed (and therefore the round key) for the *last* round.

## Procedure

### 1. Pin down the F-function differential
- Confirm analytically (or empirically over many random inputs) that for your F-function:
  `f(x) XOR f(x XOR Δ_in) = Δ_out`
  holds with probability 1 (or extremely close), where `Δ_in = 0x80808080` and `Δ_out = 0x02000002` is the canonical FEAL F-function differential.
- If a different pair `(Δ_in, Δ_out)` is available, substitute it; the rest of the procedure is unchanged.

### 2. Choose plaintext differences
- Pick a plaintext difference that propagates through the first ~half of rounds without being "mixed away" — for FEAL, use:
  `ΔP = (0x80808080, 0x80808080)` (both halves equal, both equal to Δ_in).
- Generate 2 (or a small handful of) chosen-plaintext pairs `(P_i, P_i XOR ΔP)` and record both ciphertexts `(C_i, C_i')`.

### 3. Track the differential through the rounds
- By the Feistel structure, after enough rounds the difference collapses to a known value independent of intermediate round keys.
- For FEAL with 6 rounds, the left half of the ciphertext difference after round 3 is fixed:
  `ΔL = 0x02000002`
  This does **not** depend on the first five round keys — only the last round key (whose seed you will brute-force) affects whether the differential you observe at the output is consistent.

### 4. Brute-force the last round key seed
- Enumerate every possible seed (e.g. `seed in 0..65535`).
- For each candidate seed:
  1. Derive the candidate round key `rk_last` via the known expansion/multiplier.
  2. Partial-decrypt each ciphertext pair **one round** (i.e. undo the last Feistel round using `rk_last`).
  3. Compute the resulting difference at the input of the last round for both pairs.
  4. Check whether the difference equals `ΔL = 0x02000002` (or the equivalent expected intermediate difference for the cipher at hand).

### 5. Identify the correct key
- A wrong seed matches the expected difference only by chance (roughly `1/2^n` per pair for an n-bit difference), so the true seed is the one that satisfies the check for **all** of your chosen-plaintext pairs.
- 2 well-chosen pairs is typically enough to uniquely identify the correct seed; if multiple candidates remain, add a third pair and require agreement across all three.

## Key principles / guardrails
- **Verify the differential is probability-1** before relying on it — sample ~10^4 random inputs and confirm `f(x) ^ f(x ^ 0x80808080) == 0x02000002` always.
- **The brute force is on the seed, not the full round key** — leverage the key-schedule weakness; iterating over 2^16 seeds is fast, iterating over the full 2^32 round key would not be.
- **Use ≥2 pairs** to disambiguate; with only 1 pair there will be ~1 false candidate per `2^n` of difference bits.
- **The expected intermediate difference must be independent of the keys you are NOT brute-forcing** — re-derive this on paper before trusting the attack, otherwise you'll brute-force the wrong key.
- Once `rk_last` is known, the same technique (or the now-known key) often recovers earlier round keys round-by-round.