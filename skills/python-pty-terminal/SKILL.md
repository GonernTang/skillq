---
name: python-pty-terminal
description: Build a headless interactive terminal in Python by forking a PTY, exec'ing an interactive shell, and exposing send/read/resize/close methods plus a context-manager protocol.
---

# Headless Terminal via Python `pty`

Use this pattern when you need to drive an interactive shell process programmatically (automation, test harnesses, REPL tooling, sandboxed command runners) without rendering a real TTY.

## Core Structure

Wrap the terminal in a class that takes optional `shell` (defaults to `/bin/bash -i`), `cwd`, `env` (with `TERM` set, e.g. `xterm-256color`), and `size` (rows, cols). On construction, fork a PTY child and capture the master fd plus PID.

## Implementation Steps

1. **Fork the PTY**
   - Call `pty.fork()`. It returns `(pid, fd)` in the parent, and does not return in the child.
   - In the **child branch**: call `os.setsid()` to detach from the parent's controlling terminal, then `os.execvp(shell, [shell])` (or equivalent) to replace the child with the shell. After `execvp`, the child never returns — anything after it is only reached on exec failure (exit 1).
   - In the **parent branch**: store `self.fd = fd`, `self.pid = pid`. Set the master fd non-blocking with `fcntl.fcntl(fd, F_SETFL, os.O_NONBLOCK)`.

2. **Send keystrokes**
   - `send_keystrokes(data: str | bytes)` — convert to bytes if needed, then `os.write(self.fd, data)`. Return number of bytes written (or 0 for empty input). Wrap in `try/except OSError` to tolerate a closed fd.

3. **Read output without blocking**
   - `read_output(timeout: float, max_bytes: int = 4096) -> bytes`
   - Use `select.poll()`: `poll.register(self.fd, select.POLLIN)`, `poll.poll(timeout * 1000)`.
   - If no event fires within the timeout, return whatever you have accumulated (empty bytes on first call, prior buffer on subsequent — implement as a small loop that keeps a buffer across calls, or simply return `b""` if no data ready).
   - When ready, `os.read(self.fd, max_bytes)` — guard against `BlockingIOError` and `OSError`. Truncate to `max_bytes`.

4. **Resize**
   - `resize(rows: int, cols: int)` — pack `struct.pack("HHHH", rows, cols, 0, 0)` and call `fcntl.ioctl(self.fd, termios.TIOCSWINSZ, packed)`. Suppress `OSError` (the child may have exited).

5. **Close / cleanup**
   - `close()` — send a graceful termination signal: write `b"\nexit\n"` (or `b"\nexit\nexit\n"`) to the master, then `os.close(self.fd)`.
   - `os.kill(self.pid, signal.SIGTERM)` (ignore `ProcessLookupError`).
   - `os.waitpid(self.pid, os.WNOHANG)` to reap. Idempotent — track a `closed` flag so repeated calls are no-ops.

6. **Context manager**
   - Implement `__enter__` (returns `self`) and `__exit__(exc_type, exc, tb)` (calls `self.close()`, returns `False`).

7. **PID wait helper**
   - Optional `wait()` that blocks on `os.waitpid(self.pid, 0)` for callers who want synchronous shutdown.

## Edge Cases to Handle

- **Empty keystroke input** — short-circuit, return 0.
- **Short read timeouts** — return accumulated data instead of looping forever.
- **`max_bytes` cap** — slice or use a bounded `os.read`; never let output grow unbounded across calls.
- **Dead child** — `OSError` on read/write/ioctl means the process exited; cleanup and surface a clear error rather than spinning.
- **Custom `TERM`** — pass `TERM=xterm-256color` (or the user's value) into the child env so the shell behaves like an interactive terminal (line editing, colors).
- **Optional cwd** — `os.chdir(cwd)` in the child before `execvp` if requested.
- **Re-entrancy** — guard `close()` with a flag to make context-manager + explicit-close + exceptions safe.

## Minimal Skeleton

```python
import os, pty, fcntl, select, signal, struct, termios

class HeadlessTerminal:
    def __init__(self, shell=("/bin/bash", "-i"), cwd=None, env=None, size=(24, 80)):
        env = env or os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        pid, fd = pty.fork()
        if pid == 0:
            os.setsid()
            if cwd:
                os.chdir(cwd)
            os.execvpe(shell[0], list(shell), env)
            os._exit(1)
        self.pid, self.fd = pid, fd
        flags = fcntl.fcntl(fd, F_GETFL)
        fcntl.fcntl(fd, F_SETFL, flags | os.O_NONBLOCK)
        self.resize(*size)
        self._closed = False

    def send_keystrokes(self, data):
        if not data:
            return 0
        b = data.encode() if isinstance(data, str) else data
        return os.write(self.fd, b)

    def read_output(self, timeout=0.1, max_bytes=4096):
        poller = select.poll()
        poller.register(self.fd, select.POLLIN)
        if not poller.poll(timeout * 1000):
            return b""
        try:
            return os.read(self.fd, max_bytes)
        except (BlockingIOError, OSError):
            return b""

    def resize(self, rows, cols):
        try:
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        try: os.write(self.fd, b"\nexit\n")
        except OSError: pass
        try: os.close(self.fd)
        except OSError: pass
        try: os.kill(self.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError: pass

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()
```

## Verification Smoke Test

```python
t = HeadlessTerminal()
t.send_keystrokes("echo hello-pty\n")
import time; time.sleep(0.3)
out = t.read_output(timeout=0.2)
assert b"hello-pty" in out, out
t.close()
```

## When This Pattern Fits

- Driving CLIs that require a TTY (sudo prompts, `vim`, REPLs).
- Building sandboxed execution environments for AI agents.
- Capturing shell output deterministically with timeouts instead of `subprocess.run`.

## When to Reach for Alternatives

- One-shot, non-interactive commands → use `subprocess.run`.
- True cross-platform (Windows) → use `pywinpty` or `winpty` bindings, not raw `pty`.