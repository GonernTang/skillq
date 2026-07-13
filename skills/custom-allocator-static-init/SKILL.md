---
name: custom-allocator-static-init
description: Diagnose and fix release-mode exit crashes caused by static destruction order issues with custom (bump/arena) allocators. Use when a program crashes only in release builds (not debug), uses a custom bump allocator, and the crash happens during exit / static destruction. Forces early initialization of library subsystems (e.g. libstdc++ facets, locale) so they allocate from the standard heap, not the custom allocator.
---

# Custom Allocator Static Destruction Crash

## Symptom

- Program runs fine in **debug** builds.
- Program crashes on **exit** in **release** builds (SIGSEGV / SIGABRT in static destructors).
- Project uses a custom **bump / arena / pool** allocator with backing memory that is released at a known lifecycle point (e.g. `user_init`, `main` returns).

## Root Cause

Library subsystems (notably libstdc++ iostream / locale / facet registration) use the **Meyers' singleton** pattern: their backing objects are constructed on first use and destroyed during program shutdown.

If those subsystems first run **after** the custom allocator is installed, their internal objects are carved out of the bump allocator's memory. When the bump allocator's backing memory is released (or its arena is torn down) before static destruction completes, the static destructor writes to freed memory → crash in release.

Debug builds often hide this because debug heap allocators and runtime checks tolerate the invalid write, or destruction order differs due to extra debug allocations.

## Diagnosis Checklist

1. Confirm crash is **release-only** and **on exit** (not during program logic).
2. Run under Valgrind in **release** mode:
   ```
   valgrind --error-exitcode=1 ./release_binary
   ```
   Expect to see `Invalid write` / `use after free` in `__run_exit_handlers`, `__cxxabiv1::__free_status`, `std::ios_base::Init::~Init`, or similar static-destructor frames.
3. Check whether the custom allocator is installed **before any standard library I/O** is exercised. If `cout`/`cerr`/`cin` (or any locale-aware API) is touched only after the allocator swap-in, those singletons will have been constructed inside the bump arena.

## Fix

Force initialization of the library subsystems **before** installing the custom allocator, so they allocate from the standard `malloc`/`free` heap.

Concretely:

- **libstdc++ (GCC)**: call `std::ios_base::Init __ios_init;` (or include `<iostream>` and reference `std::cout`/`std::cin`/`std::cerr`/`std::clog`) **before** swapping in the custom allocator. This forces the iostream facet tables to be allocated via `malloc`.
- **libc++ (Clang)**: same pattern — touch `std::cout` (e.g. `std::cout.tie(nullptr);`) early.
- In general: any function-local `static` of a library type that uses `operator new` must be triggered **before** the allocator takeover.

Typical placement:

```cpp
// In user_init (or the very first thing main does):
std::ios_base::Init __force_libstdc_init;   // or: std::cout.tie(nullptr);
// ... NOW install the custom bump allocator ...
```

If the allocator is installed via `operator new` / `operator delete` overrides, the same rule applies: those overrides must be installed **after** the library subsystems have performed their first allocation.

## Verification

1. Rebuild release binary.
2. Run under Valgrind:
   ```
   valgrind --leak-check=full --show-leak-kinds=definite --error-exitcode=1 ./release_binary
   ```
3. Confirm:
   - **Zero** invalid reads/writes.
   - **Zero** definite leaks. (Some "still reachable" from `__libc_start_main` is normal for iostreams — that is the singleton we just protected, allocated via `malloc`.)
4. Run the program to clean exit (`echo $?` should be 0).

## Common Pitfalls

- Touching `std::cout` once is not enough if other static-subsystem-allocated types (locale facets, `std::regex`, `std::thread`-related globals) are used later. Audit each library subsystem used.
- Overriding `operator new`/`operator delete` at link time overrides **all** allocations including libstdc++ internals. The fix above (early touch) still works because the early touch happens **before** the override is installed.
- Do **not** try to "fix" this by leaking or never freeing the arena — the crash indicates a real use-after-free; the early-init fix is the correct remedy.

## When This Skill Does Not Apply

- Crashes during normal execution (not exit) → look elsewhere (logic bug, real UAF in user code, etc.).
- Debug builds also crash → not a destruction-order issue; investigate the allocator's own bookkeeping or memory exhaustion.
- No custom allocator in use → static destruction issues are rare; suspect double-free or missed `delete` instead.