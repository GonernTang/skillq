---
name: binary-reconstruction
description: Reverse-engineer a static compiled binary (ray tracer, renderer, or similar graphics program) and produce a faithful C reimplementation that compiles with -static -lm, runs in isolation, and produces output identical (or within 1%) to the original. Use when given a stripped binary and asked to recreate its source or output behavior.
---

# Binary Reconstruction

When asked to recreate a compiled binary's behavior in C source, follow this guard-rail pipeline. The most common failure is producing a reimplementation whose output diverges from the original by more than ~1%, usually because floating-point constants were guessed instead of extracted from `.rodata`, or the domain (ray tracer vs. rasterizer) was misidentified.

## Diagnostic checklist

Run these checks BEFORE committing to a full C reimplementation:

1. **Domain identified from strings and symbols.** Run `strings binary | grep -iE "ray|trace|sphere|plane|light|SDL|PPM|P6"` and check linked libraries (`ldd`, `nm -D`). The domain determines the algorithm family — do not guess ray tracing when the strings say "rasterizer", and do not pull in SDL when the binary uses plain `fwrite` to stdout.
2. **Floating-point constants extracted from `.rodata`, not approximated.** Disassemble with `objdump -d` / `objdump -s -j .rodata` and copy every constant used by the main loop (camera origin, light direction, sphere/plane parameters, material colors) directly from the constant table. Spot-check by patching one constant in the reconstruction and confirming the output shifts predictably.
3. **Pixel/render loop mirrors the binary's iteration order.** Match the nested loop bounds exactly, preserve the order of intersection tests, and respect any early-exit conditions. Swapping x/y loops or reordering math operations changes the final output byte.
4. **Compile clean, run in isolation.** The reconstructed C must compile with `gcc -O2 -static -lm source.c -o out` (no extra libs unless the original uses them), accept the same CLI arguments, and produce an output file the original also produces.

## Procedure

1. **Identify the domain.** Scan strings, function names, and library symbols (SDL, X11, OpenGL, plain stdio). PPM/P6 output via `fwrite` is the safest target — no display server, no fontconfig.
2. **Disassemble entry point and `main`.** Recover top-level control flow: arg parsing → scene/parameter setup → render loop → output.
3. **Map `.rodata` constants to scene parameters.** Every literal that lands in a camera origin, light direction, geometry parameter, or material color must be copied verbatim from `.rodata`.
4. **Reconstruct the scene graph and rendering loop in plain C.** Use only `math.h` (trig, sqrt, fmin/fmax). Keep the inner loop structure identical to the disassembly.
5. **Compile** with `gcc -O2 -static -lm source.c -o out`. No extra flags unless the original was built with them.
6. **Compare outputs.** Run the original and the reconstruction on identical inputs, then `cmp` or hash the outputs. Acceptable tolerance: byte-identical preferred; ≤1% mean per-channel absolute error if the original uses SIMD or `-O3` you cannot reproduce.

## Stop signal

- If **3 reconstruction attempts** all produce output differing by more than 1% mean per-channel error from the original, **stop iterating on the same approach** and reset: (a) re-disassemble and re-extract every constant fresh from `.rodata` (do not trust cached extractions), (b) re-verify the domain-identification step, (c) consider wrapping the original binary's renderer with a thin shim rather than reimplementing the math.
- If the **compressed reconstructed source exceeds ~4 KB**, you are over-engineering — the original binary's logic typically fits in well under 2 KB of source. Trim, and re-derive every parameter from `.rodata` rather than from guessed pseudocode.