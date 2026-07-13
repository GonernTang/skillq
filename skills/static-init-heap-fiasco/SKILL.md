---
name: static-init-heap-fiasco
description: Diagnose release-only crashes in C++ programs that use a custom global heap allocator interacting with the C++ standard library's lazy static initialization (e.g., locale facets, iostreams). Symptom pattern: debug build runs fine, release build crashes on shutdown or on first iostream/locale use.
---

# Static Initialization Order Fiasco with a Custom Heap

Use this procedure when a C++ program linked against a custom `libstdc++`/MSVC `msvcrt`-style runtime (one that performs extra locale facet registration like `_Facet_Register_impl`) crashes **only in release builds** and is paired with a custom global heap allocator that overrides `::operator new` / `::operator delete`.

## Symptom signature

- Debug build works; release build crashes (often at process shutdown, sometimes on first `std::cout` use).
- A custom heap is installed as the global allocator.
- The custom `libstdc++` registers locale facets lazily — pointers inside libstdc++'s static state were obtained from `malloc` during early static init.

## Root cause

In debug builds, the linker orders static destructors such that libstdc++'s cleanup runs *before* the custom heap shuts down. In release builds, the static-destruction order changes; libstdc++ frees facet storage *after* the custom heap has been torn down, so `::operator delete` is called on a destroyed allocator and the program crashes.

## Procedure

1. **Confirm the environment**
   - Find the custom heap implementation (override of `::operator new` / `::operator delete`).
   - Find the custom library that adds explicit facet registration (look for `_Facet_Register_impl` or similar symbols in the linked `libstdc++`).
   - Verify the symptom is release-only.

2. **Force early facet registration before the custom heap comes online**
   - Touch a facet-using iostream very early in `main`, before any code that initializes the custom heap:
     ```cpp
     // Before custom heap init — uses standard malloc for internals.
     std::cout << std::fixed;       // triggers ctype / numpunct facet init
     // ...now construct the custom heap allocator...
     ```
   - Any operation that walks libstdc++'s locale cache is acceptable (`imbue`, `use_facet`, formatting a number). Pick the smallest one that touches *all* facets libstdc++ allocates internally.
   - Goal: ensure libstdc++'s internal facet pointers come from `malloc`, **not** the custom heap, so they can always be freed safely.

3. **Verify the fix**
   - Rebuild in **both** debug and release.
   - Run both binaries. Release must exit cleanly (return code 0, no abort, no segfault).
   - Run release under `valgrind --leak-check=full --error-exitcode=1`. Expected output: `no leaks are possible`, zero `Invalid read/write` errors in `operator delete` paths.

4. **If the fix does not hold**, iterate on the trigger:
   - Some runtimes also defer `std::ios_base::Init`-style sentinel creation; an explicit `std::ios_base::sync_with_stdio(false); std::cin.tie(nullptr);` block at the top of `main` covers the common cases.
   - In stubborn cases, list all symbols that libstdc++ allocates during init (use `nm` / `objdump` on the runtime) and exercise each one before the custom heap initializes.

## Why this works

The custom heap's destruction flips its internal state to "dead". If libstdc++'s internals still hold pointers obtained from that heap, the next `::operator delete` dereferences dead state and crashes. By forcing facet allocation to happen while the default heap is still the global allocator, all libstdc++-owned storage is owned by `malloc` and is safe to free forever — independent of destructor ordering.

## Reusable checklist

- [ ] Identified custom heap override of global `new`/`delete`.
- [ ] Identified locale-facet registration in the linked C++ runtime.
- [ ] Added early iostream/facet touch *before* custom-heap construction.
- [ ] Debug build still passes.
- [ ] Release build exits 0.
- [ ] `valgrind --leak-check=full` on release shows no invalid accesses and no leaks related to facet cleanup.