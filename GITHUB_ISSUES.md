# GitHub Issues — paper-mode per-subtask-hook refactor (commit c8ef0c6)

Copy each `<-- ISSUE -->` block to GitHub → New Issue.

> **2026-06-16 — Project rename**: The repo was renamed from `mg`
> → `skillq`. The issues below still reference the old names
> (`paper/`, `mg_*`, `[paper]` labels) because they were authored
> against the pre-rename codebase. If you re-open any of these,
> please update the path/label references in the new issue text
> (or add a comment pointing to the rename PR). For a summary of
> what changed, see the top entry in `CHANGELOG.md`.

---

<!-- ISSUE 1 -->
**Title**: [paper] Container wiring not automated — `PaperClaudeCodeAgent.run` does not start embedding daemon, dump state, or inject hook settings

**Labels**: bug, paper-mode, blocking
**Milestone**: per-subtask-hook refactor

The helper functions `hook_env` and `hook_settings_json` exist in `paper/paper_mode/agent.py`, but `bridge.run_paper_job` does not call them. The end-to-end smoke (per-subtask hook firing) is therefore blocked at the infrastructure layer — no hook env reaches the container, no `mg_skill_calls.jsonl` is written, no Q-table updates happen.

Concretely, `bridge.run_paper_job` needs to:
1. Start `embedding_service.start_embedding_service_background(...)` before `Job.create` (or right after, in a `try/finally` with `stop_embedding_service` on trial end).
2. Dump `lib.json` / `emb_cache.json` / `q_table.json` to `trial_dir/agent/sessions/mg_*.json` so the container can read them via mount.
3. Inject `settings.json` with the `PreToolUse` hook entry pointing at the hook script in the container.
4. Mount `paper/paper_mode/hook.py` into the container at `$CLAUDE_CONFIG_DIR/hooks/mg_skill_hook.py`.

This is a hard prerequisite for any per-subtask-hook smoke test.

---

<!-- ISSUE 2 -->
**Title**: [paper] `paper.method.embedding_service` and `paper.paper_mode.hook` add hard deps (`fastapi`, `uvicorn`, `requests`) not declared in `pyproject.toml`

**Labels**: build, packaging, paper-mode

The new modules import `fastapi`, `uvicorn`, `requests` at module level. None are listed in `pyproject.toml`'s `dependencies`. `uv sync` will currently work (they happen to be transitive deps of harbor / litellm), but a clean `uv pip install` against a `pyproject.toml` that lists only what's declared will fail.

Add to `[project].dependencies`:
- `fastapi>=0.110`
- `uvicorn>=0.27`
- `requests>=2.31`

The hook script (`paper/paper_mode/hook.py`) only needs `requests` at runtime; the other two are only needed by the host-side daemon. Both should still be project deps for one install.

---

<!-- ISSUE 3 -->
**Title**: [paper] `start_embedding_service_background` is never stopped — daemon thread + uvicorn leak per trial

**Labels**: bug, paper-mode, resource-leak

`embedding_service.start_embedding_service_background` starts a `threading.Thread(daemon=True)` and a `uvicorn.Server` bound to a TCP port. `bridge.run_paper_job` has no `try/finally` to call `stop_embedding_service`. Running 100 trials = 100 leaked threads + 100 leaked uvicorns, port 8765 will eventually refuse new binds.

Fix: in `bridge.run_paper_job` (or in a `Job`-level lifecycle hook), wrap the `await job.run()` in `try/finally` and call `stop_embedding_service(handle)` on exit.

---

<!-- ISSUE 4 -->
**Title**: [paper] Hook timeout 5s is fail-open (returns `approve`) — should degrade to Q+UCB-only ranking, not bypass entirely

**Labels**: bug, paper-mode, hook

`paper/paper_mode/hook.py:_post_embed` returns `None` on any embedding-service failure. The main flow then calls `_score_skills(subtask_emb=None, ...)` which sets sims to 0.0 for every skill. With all sims=0, only the global Q + UCB bonus differentiate skills — **but the score is still computed**, the decision is "block + suggest top-k" (not approve). So the hook never fully bypasses; it just loses the sim term.

However: when `subtask_emb is None` AND the ranker returns an empty top-k, the hook does `if not retrieved: return instruction` — which means the agent gets NO skill info at all (no Q ranking, no hook response suggesting skills). This is a hard fail-open that the user might not expect.

Fix: when embedding fails AND the top-k is non-empty, return `permissionDecision: "allow"` (rely on Q+UCB). When embedding fails AND top-k is empty, return a clear `permissionDecision: "deny"` with reason "embedding service unavailable; no skill ranking available; re-try or skip".

---

<!-- ISSUE 5 -->
**Title**: [paper] Container-side hook script has no standalone test

**Labels**: testing, paper-mode

`paper/paper_mode/hook.py` is the only file the agent container reads. It must be self-contained (no `paper.*` import). It has 0 unit tests. Bugs in the stdin/stdout JSON parsing, the Eq. 4 math, the `approve` vs `deny` decision logic — none are caught by CI.

Add `tests/test_hook.py` that:
- Spawns the script as a subprocess with a synthesised stdin payload
- Asserts on the stdout JSON (allow vs deny vs fail-open)
- Mocks the embedding service to return 0.0/0.5/0.9 vectors and verifies top-k ordering
- Covers the timeout / 5xx / unreachable cases

---

<!-- ISSUE 6 -->
**Title**: [paper] `_description_of` only handles the first `description:` line of YAML frontmatter — no tests, edge cases unexercised

**Labels**: bug, edge-case, paper-mode

`paper/method/vector_table.py:_description_of` reads the YAML frontmatter of a SKILL.md and returns the first `description:` line. Skills that don't follow the Claude-Code standard layout (e.g., lqrl's `examples/recommend_skills`) fall through to a less-tested fallback path (first non-empty line, then first 200 chars of body).

In smoke runs that mount lqrl's example skills (curlsearch, media-downloader, pdf, shellgames, xlsx), the description extraction may not produce the intended "what this skill does in one line" string. If the frontmatter has multiple `description:` keys (e.g., one for `requirements.description` and one for the top-level), the wrong one might win.

Add unit tests covering:
- Standard frontmatter (single description)
- No frontmatter
- Nested description keys
- Multi-line description
- Description with quotes / special chars

Also: write integration-style tests that round-trip a real lqrl example skill through `_description_of` and `sync_lib_to_vector_table` to confirm the embedding input matches human intent.

---

<!-- ISSUE 7 -->
**Title**: [paper] Hook 拒绝逻辑里 Q-table 仍可能"过期" — bridge needs to re-dump on every trial start, not just on attach

**Labels**: bug, paper-mode, multi-trial

The bridge loads `q_table.json` once at `attach_paper_registers` time (per `Job`, not per trial). For multi-trial runs, the Q-table is the same stale snapshot for all trials — no Q-updates from earlier trials feed into the hook's Eq. 4 ranking for later trials.

Fix: in `bridge.run_paper_job` (or via an `on_trial_started` hook), re-dump `lib.json` / `q_table.json` / `emb_cache.json` to each `trial_dir/agent/sessions/mg_*.json` *before* the trial starts. Harbor's `Trial.create` provides the trial_dir early enough.

---

<!-- ISSUE 8 -->
**Title**: [paper] SubTaskVerifier slices only the last 50 session-log records; sub-task boundary detection is coarse

**Labels**: bug, paper-mode, observability

`paper/paper_mode/bridge.py:_slice_sub_task_trace` reads the most recent ~50 entries of the agent's session log. For complex trials with hundreds of tool calls, this misses the early context. The current sub-task boundary is "from Skill call to next non-Skill call", but a Skill call that triggers a long Bash/Read sequence followed by another Skill call gets truncated.

Two fixes (do both):
1. Slice the session log by the *timestamps* of the Skill call (`ts` in `mg_skill_calls.jsonl`) and the next non-Skill call — only include records between them.
2. Keep the last-N fallback when the timestamps can't be parsed (e.g., session log timestamps use a different format than the hook's `time.time()`).

The hook should also include the call's start/end timestamps in `mg_skill_calls.jsonl` so the slice can be precise. Currently it logs only `ts` at fire time.

---

<!-- ISSUE 9 -->
**Title**: [paper] `MethodConfig` exposes hook-related fields but nothing in the bridge actually propagates them to the container

**Labels**: bug, paper-mode, config

`MethodConfig.hook_embedding_service_host` / `hook_embedding_service_port` / `hook_embed_timeout_sec` exist as fields but no code reads them and writes the corresponding `MG_*` env vars into the container's environment.

This is related to Issue #1 (container wiring). Once #1 is fixed, ensure the bridge uses these MethodConfig fields (not hardcoded values) when building `hook_env(...)` so the user can override from `method.yaml`.

Add a unit test that verifies `bridge.hook_env(...)` reads from `MethodConfig` and not from hardcoded constants.

---

<!-- ISSUE 10 -->
**Title**: [test] Full `pytest tests/` hangs at `test_q_initial.py` after `test_skillq_method_layers.py` — likely asyncio event loop / httpx connection leak across test files

**Labels**: testing, flaky

Per-file runs: all 59 tests pass in <2s. Full `pytest tests/`: hangs reproducibly at the first test of `test_q_initial.py` after `test_skillq_method_layers.py` finishes. Multiple `asyncio.run(job.on_ended(event))` calls in sync test functions likely leave httpx / litellm global connection pools in a bad state.

Reproduce: `pkill -9 pytest; uv run pytest tests/` → hangs at ~86% mark.

Workaround: `pytest tests/<file>.py` per file, or `pytest tests/ --forked`.

Proper fix: convert `asyncio.run(...)` to `@pytest.mark.asyncio` async fixtures, or add a finalizer that closes httpx / litellm / anyio global resources. Investigate whether `httpx.Client` instances are being leaked across `asyncio.run` boundaries.
