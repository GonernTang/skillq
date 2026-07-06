---
name: polyglot-numeric-overflow
description: Guard rail for cross-language polyglot files (e.g., C/Python, C/Ruby) that compute numeric results — prevent silent integer overflow in the compiled language from causing output divergence from the scripting language. Use whenever a single source file must be valid in two languages AND both languages must produce identical numeric output.
---

# Polyglot Numeric Overflow Guard

When a polyglot file must yield identical numeric results under two interpreters/compilers, the two runtimes almost always have different native integer widths. Python (arbitrary precision), Ruby (Bignum), and JavaScript (Number→float64) all silently promote beyond 64 bits; C and C++ do **not**. This asymmetry produces a silent divergence: small inputs match, large inputs do not.

## Diagnostic checklist

Run ALL of these BEFORE shipping the polyglot. A polyglot that fails any one of them is not safe.

1. **Inventory the integer widths.** List the maximum native integer type available in each language involved (e.g., C `long long` = 64-bit signed ≈ 9.22e18; C `__int128` = 128-bit; Python int = unbounded; JS Number = float64 ≈ 2^53 exact). Write the limits next to each language in a comment.
2. **Compute the worst-case magnitude.** For the numeric function involved, analytically compute or empirically run the *scripting* language's version at the largest input the spec allows, and capture the expected output magnitude. Compare that magnitude to the compiled language's native limit. If worst-case |value| > compiled-language max-int, the C side WILL overflow.
3. **Cross-language parity probe at extremes.** Run BOTH interpreters on a small set of probe inputs that bracket the danger zone — typically N=0, N=1, the last safe N (e.g., N=92 for Fibonacci in 64-bit), the first unsafe N (N=93, N=94, N=100), and any input the spec specifies as a max. Confirm both interpreters return byte-identical output for every probe. If any probe disagrees, the polyglot is unsafe at scale.
4. **Decide and document the overflow policy.** Choose ONE of:
   - (a) Bump the compiled-language type to `unsigned __int128` (GCC/Clang) or wire in GMP/`__int128` arithmetic for unbounded behavior;
   - (b) Clamp N at the spec/runner level so the worst case stays inside the compiled-language limit (e.g., reject N>93 for Fibonacci with `long long`);
   - (c) Have the compiled language degrade to a string/bigint representation matching the scripting side.
   State the choice in a code comment so the next reader does not re-litigate it.

## Procedure

1. After drafting the polyglot, do NOT optimize or golf it. First run the diagnostic checklist above and write the results into a scratch file or the polyglot's header comment.
2. If the compiled-language side overflows on a probe, fix it BEFORE running the full test suite. Do not paper over with `#ifdef DEBUG` or `assert`-only guards — the overflow will trigger under the real judge harness.
3. Re-run the parity probes after every change. If a probe still fails after two fix attempts, the architecture is wrong (e.g., you are trying to keep C `long long` for an unbounded sequence) — switch to `__int128`, GMP, or clamp N.
4. Once all probes pass, run the polyglot through the actual test harness on at least three inputs spanning the safe range, the boundary, and one past it (where the policy should kick in).

## Stop signal

If you have rewritten the C (or other compiled) numeric path **three times** and the cross-language parity probes still disagree at the same overflow boundary (e.g., always fails at N=94), STOP iterating on the same integer type. The architecture is wrong. Reset by:

- Switching the compiled side to `__int128` (if available) or to a bignum library (GMP, libtommath), OR
- Clamping the input domain at the runner/spec level so N never reaches the overflow point, OR
- Dropping the polyglot requirement and shipping two separate files.

Do NOT keep patching with ad-hoc casts, manual carries, or `unsigned` wrappers beyond a third attempt — that is the spiral this guard rail exists to prevent.

## Common pitfalls

- **Trusting the scripting side as the spec.** Python's `int` will never overflow, so a Python-only test pass feels complete and masks the C bug.
- **Assuming `unsigned long long` doubles the safe range.** It caps signed magnitude at the same Fibonacci ceiling; the carry still wraps.
- **Skipping the boundary probe.** Testing only N=0 and N=10 hides everything past ~N=80.
- **Golfing before validating.** Stripping whitespace or merging branches before confirming parity probes pass will move bugs into the polyglot trick itself, where they are harder to find.