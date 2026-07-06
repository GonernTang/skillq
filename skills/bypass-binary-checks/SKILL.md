---
name: bypass-binary-checks
description: Reverse engineer a binary that mixes anti-debugging (ptrace) with an unbounded input primitive (gets/read/scanf) to reach a hidden secret-printing branch. Use when a CTF or vuln-exercise binary calls ptrace() and reads input with no length limit — the procedure combines string/objdump reconnaissance, ptrace stubbing via LD_PRELOAD, and stack-smashing the input primitive to redirect control flow into the secret path, then captures the output to a results file.
---

# Bypass Anti-Debugging + Buffer Overflow to Extract a Hidden Secret

Use this procedure when a binary refuses to run normally because of a `ptrace()` anti-debug check **and** takes user input through `gets()`, `read()`, `scanf("%s", ...)`, or any other unchecked primitive. The hidden code path that prints the secret is reachable only if (a) ptrace returns 0 and (b) the input primitive overwrites a guard variable or a return address on the stack.

## Procedure

### 1. Reconnaissance with `strings` and `objdump`

- Run `strings <binary>` and look for: hidden messages, paths to secret data files, format strings (`%s`, `%x`), and library calls (`ptrace`, `gets`, `system`, `printf`).
- Disassemble with `objdump -d <binary>` (or `-M intel` for Intel syntax) and locate:
  - The `ptrace` call site and the branch that follows (usually `test %eax,%eax` / `jne`/`je` into an "abort" path).
  - The `gets` / `read` / `scanf` call site and what sits on the stack frame after the buffer (a flag byte, a counter, or the saved return address).
  - The code path that prints the secret — it is gated by the variable the input primitive can clobber.

### 2. Stub `ptrace` with a preloadable shared object

Build a one-function `.so` that makes `ptrace` always succeed:

```c
/* ptrace_stub.c */
#include <sys/types.h>
long ptrace(int request, pid_t pid, void *addr, void *data) {
    (void)request; (void)pid; (void)addr; (void)data;
    return 0;
}
```

```bash
gcc -shared -fPIC -o ptrace_stub.so ptrace_stub.c
```

### 3. Craft the input payload

Two common shapes, pick by what `objdump` shows sits past the buffer:

- **Guard variable (e.g. `auth_flag` / `count`)**: a short overflow — pad with 'A's up to the variable's offset, then write the magic byte(s) (often `0`, `1`, or the count's success value). Useful when the binary branches on the variable after `gets`.
- **Return address**: a classic smash — pad to the saved-RIP offset, then append the address of the secret-printing basic block. Confirm the target address by reading the disassembly; if PIE is on, disable it with `setarch $(uname -m) -R` or run under a fixed-`LD_PRELOAD` + matching ASLR-disable wrapper.

### 4. Run with both bypasses active

```bash
LD_PRELOAD=./ptrace_stub.so ./<binary> <<< "$PAYLOAD" | tee <results-file>
```

- Redirect stdin with a here-string (`<<<`) so the payload reaches `gets`/`read` deterministically.
- Pipe through `tee` so stdout is captured AND visible while debugging.
- If the binary still aborts, re-check the disassembly: the `ptrace` branch may compare against `PTRACE_TRACEME == 0` (success) versus `PTRACE_TRACEME == -1` (already traced) — a stub returning `0` defeats both.

### 5. Save and verify the captured secret

- Write the captured output to the required results file path.
- Confirm the secret is the *complete* conditional output, not the always-printed banner — diff against a normal run (`./<binary` without the payload / with the payload ignored) to be sure.

## Failure modes & fixes

- **Still aborts after stub** — the binary may call `ptrace` with a non-`TRACEME` request and check the PID; widen the stub to also accept a fixed PID or return based on `request`.
- **Crash instead of secret** — wrong offset in the payload; rebuild with `gcc -fno-stack-protector -z execstack -no-pie` source if available, or recompute the offset by inspecting the stack frame in `objdump`.
- **No output at all** — the secret branch may `write()` to a file rather than stdout; `strace -f -e trace=write ./<binary>` will reveal the actual fd.
- **PIE relocation** — load address randomizes the target; run `objdump -d` on the *unloaded* binary to get the static address and use `setarch ... -R` to disable ASLR for that run.

## Reusable artifact

A pre-built `ptrace_stub.so` source file lives next to this skill; copy it into the working directory and recompile per target — the stub source is universal across x86_64 Linux binaries.