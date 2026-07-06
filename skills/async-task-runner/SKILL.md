---
name: async-task-runner
description: Build an asyncio task runner that limits concurrency with a semaphore, tracks pending tasks in a set, and handles SIGINT (Ctrl-C) by cancelling in-flight tasks while leaving queued tasks unstarted. Use when you need graceful shutdown of bounded-concurrency async work — e.g., parallel HTTP requests, batch jobs, or worker pools where Ctrl-C must let `finally` blocks run cleanup.
---

# Async Task Runner with Concurrency Cap and Graceful Cancel

## Problem
Run many async tasks with a bounded concurrency limit, and on Ctrl-C (SIGINT): (1) let in-flight tasks finish their `finally` cleanup blocks, (2) never start queued tasks.

## Procedure

1. **Create a semaphore** to cap concurrency:
   ```python
   semaphore = asyncio.Semaphore(max_concurrent)
   ```

2. **Wrap each user coroutine in an inner coroutine** that:
   - `await semaphore.acquire()` *before* running the work
   - Runs the user task inside a `try/finally`
   - Calls `semaphore.release()` in `finally` (always)
   ```python
   async def _runner(coro):
       async with semaphore:
           return await coro
   ```

3. **Track pending tasks in a set** so the signal handler can find them:
   ```python
   pending: set[asyncio.Task] = set()
   for coro in coros:
       task = asyncio.create_task(_runner(coro))
       pending.add(task)
       task.add_done_callback(pending.discard)
   ```
   The `add_done_callback(pending.discard)` removes tasks from the set as they complete, so the set always contains only currently-running tasks.

4. **Install a SIGINT handler** that cancels every pending task:
   ```python
   loop = asyncio.get_running_loop()
   def _on_sigint():
       for t in list(pending):
           t.cancel()
   loop.add_signal_handler(signal.SIGINT, _on_sigint)
   ```

5. **Await all tasks** (handle `CancelledError` inside user code, not in the runner):
   ```python
   results = await asyncio.gather(*pending, return_exceptions=True)
   ```

6. **Restore the default SIGINT handler** once done so a second Ctrl-C behaves normally:
   ```python
   loop.remove_signal_handler(signal.SIGINT)
   signal.signal(signal.SIGINT, signal.default_int_handler)
   ```

## Why this works

- `asyncio.Semaphore` blocks the next task from starting until a slot frees, so queued tasks never run after `cancel()`.
- `Task.cancel()` raises `CancelledError` at the task's next `await` point, propagating into any `try/finally` so user cleanup runs.
- The pending-set + `add_done_callback(pending.discard)` pattern keeps the set's membership accurate without a manual removal loop.
- `loop.add_signal_handler` is asyncio-native (unlike `signal.signal` in a thread); it fires the callback on the event loop, safe to call `task.cancel()` from.

## Key checks

- If you skip `add_done_callback`, the pending set grows forever (cancelled tasks stay in it).
- If you skip `async with semaphore` and use manual `acquire`/`release`, a `CancelledError` between them leaks a slot — always use the context manager.
- Wrap user code in `try/except CancelledError` only if you need to swallow the cancel; otherwise let it propagate so `asyncio.gather` resolves.