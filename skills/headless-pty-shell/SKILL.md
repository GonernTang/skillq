---
name: headless-pty-shell
description: Build a Python wrapper around a pseudo-terminal (PTY) that drives an interactive shell programmatically (send keystrokes, read output, send Ctrl+C/Ctrl+Z). Applies whenever you need a "headless terminal", a non-tty process that still behaves like a real interactive shell (sources .bashrc, runs `cat`, accepts job-control signals). Domain keywords: pty, terminal emulation, interactive shell, headless terminal, forkpty, fcntl, termios.
---

# Headless PTY Shell Wrapper (Python)

## When to use
You need to spawn a long-lived interactive process and drive it from Python: send text as if typed, read what it would print on a TTY, and deliver control characters (Ctrl+C, Ctrl+Z, Ctrl+D). Plain `subprocess.Popen` is **not enough** — many programs (bash login mode, `cat`, `ssh`, `vim`, REPLs) detect a non-tty stdin and either refuse to run or disable line-editing. The fix is to put the child behind a PTY.

## Guard rail — apply before writing the spawn loop

1. **Spawn via `pty.fork()` (or `os.openpty` + `os.fork`).** Never pipe stdin/stdout to a normal pipe for interactive programs.
2. **Exec the shell as `bash -i --login`** (or the equivalent for the target shell). `-i` forces interactive mode even when stdin is not a tty in the parent's eyes; `--login` makes it source `.bash_profile`/`.profile` so aliases, prompts, and PATH are loaded. Skipping either silently breaks most users' setups.
3. **Put the master FD into non-blocking mode** with `fcntl.fcntl(master_fd, fcntl.F_SETFL, os.O_NONBLOCK)` immediately after `fork()`. Without this, `read()` blocks forever on a quiet child and your polling loop stalls.
4. **Use `select.select([master_fd], [], [], timeout)` for both writes and reads.** Wrap every `read()` and `write()` in a `try/except OSError` that catches `errno.EINTR` and retries — signals (notably `SIGCHLD`) will otherwise raise out of the syscall.
5. **Install a `SIGCHLD` handler** (`signal.signal(signal.SIGCHLD, handler)`) and reap the child with `os.waitpid(..., os.WNOHANG)` so a dying shell doesn't become a zombie and so you can detect EOF on the master FD.
6. **Restore terminal attrs and close FDs in every exit path.** Register cleanup via `__exit__`, `__del__`, **and** `atexit.register`. Forgetting one leaks FDs and, worse, can leave the child attached to a real terminal on test harnesses.
7. **Support the context manager protocol** (`__enter__`/`__exit__`). Callers will nest this inside `with` blocks; if cleanup is missing the next test will fail mysteriously with "device busy".

## Pitfalls that produced this skill (checklist)

- `fcntl` or `termios` not imported — the code uses `F_GETFL`/`F_SETFL`/`TCSANOW` but the import is missing, and the error surfaces only on the first run.
- Calling `bash` without `--login`, so `.bashrc` is never sourced and the prompt / aliases the user expected are absent.
- Reading the master FD without `select()` first, which blocks forever on idle input.
- Treating `OSError(EINTR)` as fatal instead of retrying the syscall.
- Sending `\x03` for Ctrl+C as a normal write without flushing, so the kernel buffers it and the SIGINT never arrives before the next `read()`.
- Forgetting `os.setsid()` / `os.setpgid()` in the child, so Ctrl+C sent to the wrapper also kills its own process group.
- Closing the master FD but not waiting on the child PID, leaving zombies that fill the process table after a few hundred runs.

## Diagnostic checklist — run BEFORE committing to this architecture

1. **Round-trip a no-op:** spawn the shell, `send("echo hello\n")`, `read()` and assert the buffer contains `hello`. If this fails, fix the spawn flags (usually missing `-i` or `--login`) before doing anything else.
2. **Round-trip an interactive program:** `send("cat\n")`, `send("typing\n")`, assert you receive `typing` back. If `cat` exits immediately, stdin was detected as non-tty → PTY setup is wrong, not the I/O loop.
3. **Round-trip a signal:** `send("sleep 30\n")`, then `send("\x03")`, assert the process exits within `wait_sec`. If `sleep` survives, the Ctrl+C byte was not delivered as a signal → check that you are writing to the master FD, not a pipe, and that `setsid` was called.
4. **Round-trip context-manager cleanup:** wrap usage in `with HeadlessShell(): ...`, exit the block, then assert `child.poll()` is not `None`. A live child after `__exit__` means cleanup is leaking.

## Stop signal

If you have rewritten the spawn / `select` / signal-handling layer **3 times** and any of the four diagnostics above still fails, **stop and switch approach**:
- Use `pexpect` (a battle-tested PTY wrapper) instead of raw `pty`/`fcntl`/`termios`, **or**
- If the target program supports it, drive it via a CLI flag / `--batch` mode rather than emulating a TTY.

Do not write a fourth version of the same architecture — the 2026-06-24 case study shows 7 rewrites of the same generator burned 115 minutes with no progress. The bug is almost certainly a missing import, a missing flag, or a missing `setsid`; re-read the Guard rail list above once more before you start version 4.

## Minimal skeleton (reference, not copy-paste-ready)

```python
import os, pty, fcntl, termios, struct, select, signal, atexit, errno

class HeadlessShell:
    def __enter__(self):
        self.pid, self.master_fd = pty.fork()
        if self.pid == 0:                       # child
            os.execvp("bash", ["bash", "-i", "--login"])
        flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
        fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        signal.signal(signal.SIGCHLD, self._on_chld)
        atexit.register(self.__exit__)
        return self

    def send(self, data, wait=1.0):
        os.write(self.master_fd, data.encode())
        return self.read(wait)

    def read(self, wait=1.0):
        r, _, _ = select.select([self.master_fd], [], [], wait)
        if not r: return b""
        try:
            return os.read(self.master_fd, 4096)
        except OSError as e:
            if e.errno == errno.EINTR: return b""
            raise
```