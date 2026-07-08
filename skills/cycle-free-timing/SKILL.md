---
name: cycle-free-timing
description: Build, debug, and verify combinational+sequential logic-gate circuits in a cycle-free simulator where every signal must stabilize by the end of a fixed step count. Use when outputs must appear at specific simulator steps (e.g., last-N signals, fixed horizon) rather than asynchronously.
---

When implementing a compound computation (e.g., fib(isqrt(N))) as a gate-level
circuit in a cycle-free, step-driven simulator, the failure mode is **NOT** a
logic bug — it is **timing**: the right value exists internally but is not
latched into the verifier's expected output window by step S.

This skill encodes that lesson as a pre-commit guard-rail.

## Diagnostic checklist (run BEFORE committing to a circuit topology)

1. **Decompose into combinational vs sequential blocks.** Identify a pure
   combinational kernel (e.g., unrolled restoring square root) and a sequential
   FSM (e.g., matrix-exponentiation Fibonacci with a step counter). Mix the two
   intentionally — never blur which wires are level-sensitive vs edge-triggered.
2. **Allocate signal indices in a stable order:** inputs (identity gates) →
   combinational intermediates → sequential registers → final output tap.
   Re-deriving indices during debugging produces off-by-one wiring bugs that
   look like logic errors.
3. **Verify intermediate values at the sim horizon.** Build a trace program
   that prints specific internal signals at every step. Confirm the final
   answer lands on the verifier-expected output wires (typically the last
   signals) at the **exact** last step, not one step early/late.
4. **Confirm total signal count and step count both meet the contract**
   (e.g., ≤ signal-limit signals; sim runs to the specified step count).
   A circuit that is correct at step T but where T < required horizon is
   unverifiable no matter how clean the logic.

## Stop signal

- If the simulator's final-step output wires do not contain the expected
  answer when run for the *exact* required number of steps → **STOP**.
  Do not patch the algebra. Walk back the FSM: count how many cycles the
  sequential part needs from reset to "result-ready", and verify that
  `cycles_needed ≤ steps - combinatorial_latency`.
- If a manual spot-test passes but the verifier rejects it, the discrepancy
  is almost always a step-count mismatch. Reset the simulation to run for the
  full required horizon and inspect the last-step output window before
  touching the gate graph.

## Reset action

1. Re-derive the FSM cycle budget from the algorithm's recurrence depth
   (e.g., bit-length of exponent, or number of squarings for matrix exp).
2. Pick `steps = combinatorial_latency + cycles_needed + output_latch_delay`.
3. Rebuild the output tap so the result is wired to the *trailing* signals
   the verifier reads.
4. Re-run the trace at the new horizon; only then re-submit.