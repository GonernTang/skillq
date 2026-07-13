---
name: binary-reverse-oracle
description: Reverse-engineer compiled binaries via dynamic analysis and an input-output oracle rather than static string inspection or heuristic guessing.
---

# Binary Reverse Engineering with an Oracle

When the task is to recover the algorithm or behavior of a compiled
binary, treat the binary itself as the ground-truth oracle. Do **not**
read strings, symbol names, or guess from surface clues and commit to a
reimplementation. Static heuristics drift; the executable does not.

## Diagnostic checklist (run BEFORE committing to a reconstructed algorithm)

1. **Have I captured a dynamic trace, not just static clues?**
   Run `strace`, `ltrace`, or set a `gdb` breakpoint on the entry
   function and step through real inputs. Confirm at least one runtime
   observation backs every claim about control flow.

2. **Do I have an input-output oracle pair before writing code?**
   Feed the original binary a chosen input, capture its exact stdout
   (or whatever channel the task defines), and save it as the reference
   output. You must have this **before** you reconstruct — not after.

3. **Have I produced a real disassembly rather than guessing from strings?**
   Use `objdump -d`, `ghidra`, `r2`, or equivalent. If you cannot point
   to the disassembly of the function you are reimplementing, stop.

4. **For float-heavy code: have I matched precision, ordering, and rounding?**
   Identify the IEEE types (`float`, `double`, `long double`), confirm
   the order of operations, and verify rounding mode. A reimplementation
   in `double` that silently changes associativity will not match the
   oracle to the last bit.

## Stop signal

**If `diff` between the reconstructed implementation's output and the
original binary's output is non-zero on any oracle input, halt.** Do
not patch around the symptom. Reset by:

- Returning to the disassembly at the divergence point,
- Re-walking the control flow from there with the debugger, and
- Updating the reconstruction **only after** the new trace explains the
  diff.

Three consecutive failed iterations without a new dynamic observation
= wrong methodology, not wrong code. Switch approach (e.g., full
disassembly pass, or symbol resolution) before continuing to iterate.

## Why this matters

Heuristic guesses from strings compile, run, and look plausible — and
then diverge from the oracle on the first edge case. The binary is the
spec; the diff is the teacher.