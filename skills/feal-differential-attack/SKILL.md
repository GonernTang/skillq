```markdown
---
name: feal-differential-attack
description: Differential cryptanalysis attack on a FEAL-like Feistel cipher to recover a specific round key (e.g., key[5]). Use when the task specifies breaking FEAL (or a FEAL variant) via chosen-plaintext differential cryptanalysis and recovering a round key under a tight time budget (e.g., under 30 seconds).
---

# Differential Cryptanalysis Attack on FEAL

## When to use
- Target is a FEAL-like block cipher (Feistel network, F-function based on rotations, XOR, and an S-box-like construction).
- Task provides an encryption function `E(P, key_schedule)` and asks for one specific round key (e.g., `key[5]`).
- Round keys are derived from a short seed (e.g., 16-bit), so once the last round key is known, brute-forcing the seed is feasible.
- Time budget is tight (cryptanalytic attacks must finish in seconds).
- **This skill is not applicable to operating system installation, VM configuration, or system administration tasks.** (If the task is about setting up a legacy OS or VM, do not use this skill.)
- **This skill is not applicable to DNA sequence manipulation, primer design, or insertion tasks.** (If the task is about DNA insertion or primer design, do not use this skill.)
- **This skill is not applicable to adaptive rejection sampling or any general-purpose statistical sampling algorithm.** (If the task is about implementing a statistical sampler, do not use this skill.)
- **This skill is not applicable to password recovery or deleted file recovery tasks.** (If the task is about recovering a deleted file or reconstructing a password, do not use this skill.)
- **This skill is not applicable to fixing code vulnerabilities (e.g., CWE-502, CWE-93, CWE-94) in a codebase.** (If the task is about patching deserialization, header injection, or eval-based code injection vulnerabilities, do not use this skill.)
- **This skill is not applicable to SQLite WAL recovery or any database recovery tasks.** (If the task is about recovering data from a SQLite Write-Ahead Log, do not use this skill.)
- **This skill is not applicable to git secret recovery, git leak recovery, or any git repository sanitization or history rewrite tasks.** (If the task involves recovering a secret from a Git repository, purging secrets from history, or sanitizing a Git repo, do not use this skill.)
- **This skill is not applicable to building or compiling software from source code (including legacy software builds, package compilation, or installation from source).** (If the task is about building or compiling software from source, do not use this skill.)
- **This skill is not applicable to SAM-based cell segmentation or any image segmentation tasks.** (If the task is about segmenting cells in an image using SAM or any other method, do not use this skill.)
- **This skill is not applicable to Raman spectrum fitting or peak analysis tasks.** (If the task is about fitting Raman peaks (G and 2D) from a spectrum file, do not use this skill.)
- **This skill is not applicable to MTEB leaderboard tasks, embedding model comparison, or benchmark retrieval.** (If the task is about finding the best embedding model on an MTEB leaderboard, do not use this skill.)
- **This skill is not applicable to gRPC server setup, starting background processes, or network service deployment tasks.** (If the task is about deploying a gRPC service or running a server in the background, do not use this skill.)

## Procedure

### 1. Study the F-function and find a high-probability differential
- FEAL's F-function takes a 32-bit half-block plus a round subkey, splits it into bytes, applies byte rotations and `g()` rotations on parts of the input, then XORs halves.
- Search for input differences `ΔX` such that `F(X) ⊕ F(X ⊕ ΔX)` is constant (probability 1) or nearly constant. A known FEAL property: input difference `0x80800000` (and a few related patterns) yields output difference `0x00000000`.
- Prove the differential by enumerating all 32-bit inputs XOR `ΔX` and confirming `F(X) ⊕ F(X ⊕ ΔX) = 0` for every `X` (or with overwhelming probability).
- The differential should be cheap to construct (few bit positions set) and the zero or fixed output difference should be easy to test.

### 2. Set up chosen-plaintext queries
- Pick a plaintext `P` and a paired plaintext `P' = P ⊕ ΔX` so that the difference between the two Feistel halves entering the final round is `ΔX`.
- Encrypt both under the target cipher using the public `encrypt` API to obtain `C` and `C'`.
- Collect several such ciphertext pairs (a small handful suffices when the differential has probability 1).

### 3. Peel the last round to recover its subkey
- Express the final round's output in terms of the ciphertext halves and the unknown last-round subkey `K[last]`.
- For each guessed value of the relevant bits of `K[last]` (which is often small — sometimes just 16 bits rather than 32):
  - Reverse the final F-function call to get a candidate for the input difference to the last round.
  - Check whether the candidate equals the expected differential (`0x80800000` or whatever the chosen input difference was).
- Keep every subkey candidate that is consistent with all collected ciphertext pairs; intersect across pairs until only one remains, or a tiny set remains.

### 4. Brute-force the key-schedule seed
- The round keys are generated from a short seed (commonly 16 bits). For each seed candidate, regenerate the key schedule and compare the recovered last-round subkey against the candidate list.
- The unique matching seed yields the correct key schedule; the requested key (e.g., `key[5]`) is read directly from that schedule.

### 5. Implement efficiently to meet the time budget
- Represent differences as Python integers; use bitwise ops (XOR, mask, rotate) instead of object overhead.
- Parallelize the per-pair candidate filtering and the seed brute-force with `multiprocessing.Pool` so the attack completes well under the time budget.
- Final sanity check: encrypt two random plaintexts with the recovered key schedule and confirm the ciphertexts match the oracle.

## Verification
- Run the recovered `key[i]` through the cipher's reverse key schedule check (if exposed) or through `decrypt` on a known pair.
- Confirm the attack completes in the required time, and that no other plausible seed produces the same round key.

## Shape-Aware Batching for Static-Graph LLM Inference
- Group requests by their aligned prompt length and generation length; use adaptive thresholds that tighten as generation length increases to control cubic decode cost.
- Merge batches that share the same aligned prompt length (S_max) and have close generation lengths (G diff ≤ 12) to reduce latency while minimally increasing cost.
- Cap the number of distinct shapes by selecting evenly spaced representative aligned prompt lengths and assigning each request to the smallest representative ≥ its own aligned length.
- Validate against cost, pad ratio, p95 latency, and sequential timecost metrics.

## ReLU Network Weight Extraction
To extract the weight matrix A1 from a black-box ReLU network f(x) = A2 * ReLU(A1 * x + b1) + b2 with unknown architecture: (1) Use central differences (typical h=1e-5) to estimate the gradient ∇f(x) at many points. (2) Pick a random unit direction u, sweep x(t)=x0+t*u with small step δ=1e-2, and compute the difference Δ = ∇f(x+δu) - ∇f(x). Each ReLU boundary crossing yields Δ ∝ A1[i,:] (scaled by ±A2[i]). (3) Repeat 10,000-80,000 times across many random x0 and u to collect candidate jump vectors. (4) Normalize each candidate to unit length. (5) Cluster normalized vectors by absolute cosine similarity (e.g., threshold 0.99). (6) Sort clusters by size and take the top N clusters where N is the known number of hidden neurons; if unknown, use a frequency drop (e.g., clusters with >50 hits vs ≤3 hits) to identify the signal. (7) Return a matrix whose rows are the centroids of these clusters. The method recovers rows up to permutation, sign, and scaling (since each jump vector absorbs the unknown A2[i] factor). Important safeguards: use a very small δ to avoid crossing multiple boundaries simultaneously; ignore candidate vectors with near-zero norm; deduplicate near-duplicate directions; and if the true number of neurons is unknown, use the frequency gap between signal and noise to estimate it.

## Robust Foot‑Ground Contact Detection for Hurdle Jump Analysis
When the task requires detecting takeoff and landing frames from a video of a hurdle jumper, the following approach replaces brittle single‑frame differencing with a more robust pipeline:

### 1. Preprocessing and motion magnitude
- Compute per‑frame **absolute pixel‑wise difference** (frame‑differencing) but do **not** use a fixed threshold. Instead, calculate the motion **magnitude** for all pixels (or use a simple per‑pixel absolute difference).
- For each frame, compute the mean and standard deviation of the non‑zero motion magnitudes across all pixels of the difference frame. Set an **adaptive threshold** per video as `mean + k
```