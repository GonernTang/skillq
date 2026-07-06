---
name: debug-release-crash
description: Step-by-step procedure for diagnosing program crashes that occur only in release mode (with optimizations enabled, e.g. -O2 -DNDEBUG) but not in debug mode (-O0 -g). Use when a binary passes all debug-mode tests yet SIGSEGV/SIGABRT in optimized/release builds, especially with custom memory allocators or standard-library replacements.
---

# Debug a Release-Mode-Only Crash

When a program crashes only in release mode (optimizations enabled, `NDEBUG` defined) but works fine in debug mode, follow this procedure. The divergence is almost always caused by undefined behavior (UB) or memory errors that the debug build masks — debug builds often zero-initialize, skip inlining, or insert red-zone padding that hides the bug.

## 1. Reproduce in both modes with minimal flags

Build two binaries from the same source:

- **Debug**: `-O0 -g` (no `NDEBUG`)
- **Release**: `-O2 -DNDEBUG` (or `-O3`)

Run both against the failing input. If release crashes and debug does not, the bug is real and present in both binaries — debug is just hiding it. Note the exact signal (SIGSEGV vs SIGABRT), exit code, and any output before the crash.

## 2. Capture a precise stack trace

Get the failing function and line from the release binary. Pick whichever applies:

- Run under `gdb --args ./release_binary <args>` → `r` → `bt full`.
- If a coredump is produced: `gdb ./release_binary core` → `bt`.
- On Linux, enable coredumps first: `ulimit -c unlimited`.

Record the top frames and the crashing instruction/address. This is your anchor for every later check.

## 3. Run Valgrind on the release binary

```
valgrind --leak-check=full --track-origins=yes ./release_binary <args>
```

Valgrind instruments memory accesses and reports the original code location. Look specifically for:

- Use-after-free (invalid reads/writes)
- Heap buffer overflow / underflow
- Uninitialized value reads (Memcheck's "Conditional jump or move depends on uninitialised value(s)")
- Invalid free / double free

Valgrind runs ~20–50× slower but catches issues regardless of optimization level. If the crash is non-deterministic, run under Valgrind to make it deterministic.

## 4. Hunt for undefined behavior

Optimizers assume the C/C++ abstract machine has no UB and will reorder, elide, or invent code when UB is present — the release crash is often a delayed consequence. Common offenders:

- **Uninitialized variables**: a debug build's `0x00` padding becomes garbage in release. Compile with `-Wuninitialized -Wall -Wextra` and scan warnings.
- **Signed integer overflow**: silent wrap in release; `-ftrapv` or UBSan catches it.
- **Strict aliasing violation**: accessing an object through the wrong-type pointer/lvalue. Compile with `-fstrict-aliasing -Wstrict-aliasing=3` to surface warnings.
- **Out-of-bounds array access** not on the heap.
- **Stack buffer overflow** (debug builds often grow stacks or pad frames).
- **Order-of-evaluation** changes between `-O0` and `-O2`.
- **Lifetime issues**: returning pointers/references to locals, dangling temporaries.

Search the source for patterns near the crash site: casts, `memcpy`, type-punning through unions, pointer arithmetic past array bounds.

## 5. Compare any custom standard-library / allocator builds

If the project ships its own `malloc`/`free`, `new`/`delete`, vector/string, or runtime headers (look for `lib/`, `third_party/`, vendored STL, custom `Allocator` template), compare the release vs debug builds of *that library*:

- Are asserts / bounds checks compiled out under `NDEBUG`?
- Do destructors or deallocators behave differently (e.g., an uninitialized member that debug zeroed)?
- Did a header redefine `assert`, `operator new`, or container internals based on `NDEBUG`?
- Is there a release-only fast path (e.g., `if (NDEBUG) { ... }` block) that bypasses a safety check?

Diff the preprocessed output of a suspicious header under both `-O0 -g` and `-O2 -DNDEBUG` (`cpp -O2 -DNDEBUG file.h | diff - <(cpp -O0 file.h)`) to surface any macro-gated code paths.

## 6. Rebuild with sanitizers to localize the bug fast

Sanitizers add checks the optimizer normally elides, and they pin the violation to a source line. Pick whichever fits the symptom:

- **Memory error (crash address, suspicious pointer)**:
  `-fsanitize=address -fsanitize=undefined -g -O1`
  (Use `-O1` so optimizer still runs but ASan/UBSan stay accurate.)
- **Suspected thread race or happens-before bug**:
  `-fsanitize=thread -g`
- **Suspected leak rather than crash**:
  `-fsanitize=leak`
- **Suspected signed-overflow or alignment**:
  `-fsanitize=undefined -fno-sanitize-recover=all`

Rerun; sanitizer reports typically name the file, line, and exact access. If only the sanitized build catches it, the bug is real; commit the sanitizer output alongside the stack trace.

## 7. Form and verify the hypothesis

Before editing source, state a one-sentence hypothesis ("the release-mode `HashMap::resize` writes one past the bucket array when `size == capacity`, which debug-mode red-zones catch"). Then prove it by:

- Adding a targeted assert (compiled in both modes) that fires *before* the bad access.
- Writing a minimal reproducer that isolates the suspect function.
- Bisecting: temporarily disable optimizations on the suspect translation unit (`-O0` for just `foo.cpp`) and confirm the crash goes away — this narrows the trigger to optimizer behavior on that file.
- Checking the assembly (`objdump -d` / `gdb disas`) of the release binary for the crashing function and comparing against the debug version.

Only after the hypothesis reproduces consistently should you write the fix.

## 8. Document the fix

In the commit message, record:

- The original symptom (release-only crash, signal, reproducer).
- Root cause (which UB or memory error).
- The sanitizer or Valgrind report that confirmed it.
- Why debug mode hid it (e.g., "red zone between stack frames", "uninitialized member was zero in debug heap", "fast-path branch gated on `NDEBUG`").

This prevents future regressions and helps anyone bisecting the same symptom later.

## Quick checklist

- [ ] Reproduce in `-O0 -g` and `-O2 -DNDEBUG`
- [ ] Capture stack trace from release build (gdb / coredump)
- [ ] Run Valgrind on release binary
- [ ] Audit crash site for UB (uninit read, signed overflow, aliasing, OOB)
- [ ] Diff any custom lib/runtime headers under both `NDEBUG` states
- [ ] Rebuild with `-fsanitize=address,undefined` (and `-fsanitize=thread` if concurrent)
- [ ] State and verify a hypothesis before patching
- [ ] Record root cause in the commit message