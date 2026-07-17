---
name: allocator-bootstrap
description: Force-allocate library-internal state via malloc before installing a custom (e.g. bump/arena) allocator, so static destructors that call operator delete get a heap that still exists at exit.
---

# Bootstrap library state before installing a custom allocator

When a program installs a custom heap allocator (bump, arena, pool, jemalloc
shim, etc.) and then links against a third-party library that registers
singleton/static state internally, those library-internal objects are
typically allocated through the active allocator at first-use. At program
exit, static destructors run **after** the custom heap has been torn down
in many setups, so `operator delete` falls back to `free()` on a region
already destroyed — producing a crash that looks unrelated to the custom
allocator.

## When this matters

- A static-lifetime crash appears in library code (registries, factories,
  thread-local caches, format-string tables) with no obvious cause.
- The program replaces the global allocator, uses a non-`free`-compatible
  heap, or destroys the heap before statics unwind.
- The first use of the library happens **after** the custom allocator is
  installed, so its internal allocations go to the custom heap.

## Procedure

1. **Identify the registration hook.** Find the library function whose
   first call allocates the library's static state (e.g. a factory,
   registrar, init, or any constructor that touches a global table).
   It is usually called lazily on first use, but it must be force-invoked
   from your bootstrap.
2. **Allocate it on the real heap.** Wrap or precede the call with a
   deliberate `malloc`/`new` of a small sentinel object in the same
   translation unit / dynamic library as the registration, so that the
   internal singleton lives on the libc heap, not your custom heap.
   - Equivalently: call the registrar from a constructor/destructor that
     runs *before* your custom allocator is installed.
3. **Install the custom allocator only after step 2 completes.** If your
   project has a `user_init` / pre-main / plugin-load callback that runs
   before the allocator swap, do the forced registration there.
4. **Verify destruction.** Confirm the previously crashing static
   destructor no longer fires `free()` against the torn-down heap. A
   quick `ltrace`/`valgrind` pass on exit should show those frees going
   to the libc heap you allocated from.

## Minimal pattern

```c
// Force library registration on the libc heap before the
// custom allocator is installed.
static void bootstrap_library(void) {
    void *sentinel = malloc(1);                // touches libc heap first
    (void)sentinel;
    library_register_all_handlers();          // allocates internals via malloc
}

__attribute__((constructor))
static void pre_allocator_init(void) {
    bootstrap_library();                      // runs before user_init
}
```

## Common pitfalls

- The registration function is **itself** overloaded `operator new` —
  in that case the bootstrap alone is not enough; the library must
  expose a plain-C registration entry point, or you must `dlsym` it
  from a TU compiled without the custom allocator.
- Multiple singletons in the library: force one allocation per singleton,
  or call every public entry point once, to ensure each static is
  materialized on the real heap.
- If you use `LD_PRELOAD` to swap allocators, the preloaded library's
  constructors still run after the application’s constructors — so
  force the registration from a constructor in a library loaded
  *before* the preloaded one, or from `main` before any allocator swap.

## Why this works

`operator delete` is not required to call `free`; many implementations
do so as a fallback when the pointer wasn't tracked by their pool. By
making sure the library's static state is allocated through the libc
allocator (and therefore tracked by libc's free list), the eventual
`operator delete` → `free()` path is valid even after your custom heap
has been destroyed.