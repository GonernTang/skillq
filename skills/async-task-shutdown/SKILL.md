---
name: async-task-shutdown
description: Build an async task runner in Python with bounded concurrency (asyncio.Semaphore) and a graceful shutdown triggered by SIGINT — the first Ctrl+C stops scheduling new work and lets in-flight tasks finish (running their `finally` blocks); the second Ctrl+C exits immediately. Use when a script must run many async tasks concurrently, cap parallelism, and survive interruption cleanly.
---

# Async Task Runner With Graceful Shutdown

## When to use
- Running N async tasks where you want at most `max_concurrent` in-flight.
- The script runs from a terminal and must respond to Ctrl+C by **stopping new work** but **letting current work complete** (e.g. to honor `finally` cleanup like closing files, flushing buffers).
- A second Ctrl+C should bypass grace and terminate.

## Procedure

### 1. Set up the shutdown flag
Use a module-level flag flipped by a signal handler. The first SIGINT sets it and prints a friendly message; the second SIGINT restores the default handler so the next signal kills the process.

```python
import asyncio, signal, sys

_shutdown = False

def _on_sigint(signum, frame):
    global _shutdown
    if _shutdown:
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        raise KeyboardInterrupt
    _shutdown = True
    print("\nShutdown requested — finishing in-flight tasks. "
          "Press Ctrl+C again to exit immediately.", file=sys.stderr)

try:
    signal.signal(signal.SIGINT, _on_sigint)  # main thread only; wrap in try
except ValueError:
    pass  # not in main thread (e.g. Windows / embedded) — skip gracefully
```

### 2. Cap concurrency with a semaphore
Create **one** `asyncio.Semaphore(max_concurrent)` shared across all tasks. Each coroutine acquires it **before** doing work; this is what bounds parallelism.

### 3. Schedule tasks, checking the flag in the loop
In the scheduling loop, before creating a new task, check `_shutdown`. If set, stop scheduling immediately — do not cancel already-running tasks.

```python
async def run_with_limit(coros, max_concurrent):
    sem = asyncio.Semaphore(max_concurrent)
    tasks = []
    for coro in coros:
        if _shutdown:
            break
        await sem.acquire()
        if _shutdown:                # re-check after a possible await
            sem.release()
            break
        task = asyncio.create_task(_wrapped(coro, sem))
        tasks.append(task)
    return await asyncio.gather(*tasks, return_exceptions=True)

async def _wrapped(coro, sem):
    try:
        return await coro
    finally:
        sem.release()
```

### 4. Collect results, surface the first real failure
After `gather(..., return_exceptions=True)`, scan results and re-raise the **first non-`CancelledError` exception**. `CancelledError` belongs to the shutdown path and should not be reported as an error.

```python
for r in results:
    if isinstance(r, BaseException):
        if not isinstance(r, asyncio.CancelledError):
            raise r
```

### 5. Cleanup happens automatically
Because you **do not cancel** running tasks on the first SIGINT, their `finally` blocks run to completion when the coroutine returns naturally. Only the second SIGINT (or post-gather re-raise) takes the process down.

## Edge cases to test
- **Empty input list** — `gather()` of empty list returns `[]`; re-raise loop is a no-op.
- **`max_concurrent=1`** — semaphore guarantees serial execution; shutdown still lets the lone task finish.
- **Multiple failures** — first non-`CancelledError` exception wins; later ones are logged but not raised.
- **Exception inside one task** — does not kill siblings because `return_exceptions=True`; semaphore still releases via `finally`.
- **Signal arrives between acquire and re-check** — re-checking the flag after `await sem.acquire()` prevents scheduling work you no longer want.
- **Non-main thread / Windows** — `signal.signal` raises `ValueError`; the `try`/`except` above makes the runner usable there (Ctrl+C simply won't trigger graceful shutdown, but everything else works).

## Common pitfalls
- Calling `task.cancel()` on every task at shutdown — defeats the purpose of "let it finish" and skips `finally` for in-flight I/O.
- Re-raising `CancelledError` as if it were a user error — distinguish it explicitly.
- Forgetting `await sem.release()` on the exception path — wrap the worker body in `try/finally` so the semaphore is always freed.
- Sharing the flag check only before the await — re-check after any `await` that can yield control.