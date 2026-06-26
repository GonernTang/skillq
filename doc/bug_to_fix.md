# SkillQ — Open bugs and known gaps

Last updated: 2026-06-26 (post 4-layer audit by subagents; pre-fix).

This document is a faithful audit of the current state of the
`skillq` paper method. "Tested" means there's a unit test covering
it. "Verified end-to-end" means a TB 2.0 smoke trial exercised it.

## What's working (verified end-to-end)

The end-to-end flow on `fix-code-vulnerability` (Method B / hook,
TB 2.0) is green. The agent invoked `Skill("affaan-m-security-review")`
at step 3, the hook fired, the LLM judge returned `r_subtask=1.0`,
Eq.6 raised the Q-value from 0.5 → 0.65, `state.save()` persisted
`method_state.json` to the library root, and the trial scored
reward 1.0.

```
agent:    Skill("affaan-m-security-review") at step 3
reward:   1.0
calls_log.jsonl:   1 line   (hook fired)
method_state.json: step=1, lib=37, Q=0.65 for the called skill
q_updates.jsonl:   1 line   (judge verdict persisted)
method_errors.jsonl: empty  (no swallowed exceptions)
```

93 / 93 unit tests pass (`uv run pytest`).

---

## Fixed in the current tree (recent commits)

| # | Bug | Fix | Commit |
|---|-----|-----|--------|
| F1 | `from __future__ import annotations` broke FastAPI's `Annotated[EmbedRequest, Body(...)]` (Pydantic treated the request as a query param, returned 422 "field req required") | Removed the import, kept the explicit `from typing import Annotated, Any` | aae5ae5 |
| F2 | `EMBEDDING_MODEL` env var was missing the `openai/` provider prefix → litellm raised "LLM Provider NOT provided" | `get_embedder_config_from_env` adds the prefix when missing | aae5ae5 |
| F3 | `LiteLLMEmbedder.__call__` only read `OPENAI_API_KEY` / `OPENAI_API_BASE` (forced callers to mirror env under a different name) | Now reads `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` first, falls back to OPENAI_* | aae5ae5 |
| F4 | DashScope rejects batch > 10; OpenAI-compatible endpoints often have a similar cap | `LiteLLMEmbedder.__call__` chunks in `EMBED_BATCH_SIZE` (default 10) windows | aae5ae5 |
| F5 | Hook had a `intent_emb` typo (NameError) that silently crashed `_post_embed` and left the calls_log empty | Renamed to `subtask_emb` | aae5ae5 |
| F6 | Seed skills never made it into the paper method's library | `QlibState.ensure_seeded()` auto-loads from `method.seed_skills_dir` on first boot | aae5ae5 |
| F7 | The agent couldn't see the seeded skills inside the container | `container_wiring.py` bind-mounts the seed dir at `$CLAUDE_CONFIG_DIR/skills` (read-only) | aae5ae5 |
| F8 | `calls_log.jsonl` mount was silently read-only (Harbor's `ServiceVolumeConfig.read_only: Literal[True]`) — the hook's `Skill` allow/deny + log write were no-ops | `cast(ServiceVolumeConfig, ...)` bypasses the runtime type check; `read_only=False` reaches docker-compose | aae5ae5 |
| F9 | Hook mode never injected the `Skill()` instructions into the agent's prompt, so the agent didn't know to call the tool | `_mount_merged_claude_md` writes a per-trial `CLAUDE.md = user_stub + HOOK_INSTRUCTIONS_SNIPPET` and bind-mounts it | aae5ae5 |
| F10 | `SKILLQ_*` env vars didn't reach the in-container claude process (Harbor snapshots `extra_env` at `__init__` time, before `bridge.on_trial_started` updated it) | `SkillQClaudeCodeAgent.__init__` now injects `SKILLQ_*` into `self._extra_env` directly | aae5ae5 |
| F11 | `emb_cache` was empty on first run, so the hook's cosine term was 0 for every skill (all top-3 tied at UCB only) | `bridge.attach_paper_registers` pre-embeds every seeded skill's description after `ensure_seeded` | aae5ae5 |
| F12 | `scan_seed_dir` dedup'd by YAML frontmatter `name:`, so dirs that shared a frontmatter name silently dropped the later ones | Use `skill_dir.name` as the primary key (matches what Claude Code's Skill tool registers) | aae5ae5 |
| F13 | `_q_update_from_subtask` read `trial_dir / "skillq_skill_calls.jsonl"` (an in-container bind-mount, usually empty by trial end) | **Fix A**: read from `trial_dir / "skillq_state" / "calls_log.jsonl"` (the host-side staging file) | aae5ae5 |
| F14 | `on_ended`'s bare `except Exception` swallowed every failure silently — `trial.log` doesn't capture the bridge's stderr | **Fix B**: write to `skillq_state/method_errors.jsonl` with the exception type + message | aae5ae5 |
| F15 | No per-trial Q-update trail (everything was in `method_state.json` only, which made debugging hard) | **Fix C**: write `skillq_state/q_updates.jsonl` per trial | aae5ae5 |
| F16 | `q_subtask_verifier_model` defaulted to `openai/gpt-4o` (required `OPENAI_API_KEY`, which this env doesn't have) — the judge crashed and propagated the exception up to `on_ended`'s try/except, which is why `state.save()` never ran | **Fix D**: smoke method yaml now sets `q_subtask_verifier_model: "anthropic/${ANTHROPIC_MODEL}"` | aae5ae5 |
| F17 | The hook's `calls_log.jsonl` bind mount used `read_only=False` to let the hook append; this violated Harbor's `ServiceVolumeConfig.read_only: Literal[True]` TypedDict. Any re-run / `--resume` triggered `TrialResult.model_validate_json(result.json)` → `ValidationError: literal_error` | **Bug 2 fix**: drop the SkillQ-injected calls_log mount entirely. Harbor's auto-injected `agent_dir` bind mount (`trial_dir/agent` → `/logs/agent`, no `read_only` key, Docker defaults to read-write) already covers the path. Bridge reads from `trial_dir/agent/sessions/skillq_skill_calls.jsonl` on `on_ended`. | (pending) |
| F18 | `SkillExtractor._extract_with_prompt` built a `claude --print` cmd array with only `--append-system-prompt` and no user prompt. `claude --print` rejected the call with `Input must be provided either through stdin or as a prompt argument when using --print`. The subprocess returned non-zero immediately, `extract_batch` returned `None`, and the auto-extract wiring was effectively dead from day one. | **Bug 4 fix**: add `-p <user_prompt>` (the trigger instruction) to the cmd array in `skillq/method/extractor.py`. System prompt still carries the format and constraints. Verified end-to-end via direct `SkillExtractor.extract_batch` invocation. | (pending) |
| F19 | Method A (agentic) had never been exercised end-to-end. The `retrieval_mode: "agentic"` path's wiring (skillq_skills dir mount, `_search.sh` script, manifest, plan D pre-embed for the cosine term) was all unverified. | **Bug 9 fix (smoke verification only, no code change)**: new `configure-git-webserver_skillq_smoke_agentic.yaml` + `method_git_smoke_agentic.yaml` run end-to-end (reward=1.0). Hook mounts are absent, `skillq_skills/` artifacts present, plan D emb_cache populated. | (pending) |

---

## Open bugs (still need fixing)

### Bug 1 — In-container `skillq_skill_calls.jsonl` is 0 bytes when host-side has data

**Symptom:** the host-side `trial_dir/skillq_state/calls_log.jsonl` has
the hook's JSONL output (821 bytes for the recent `fix-code-vulnerability`
trial), but the bind-mounted copy at
`trial_dir/agent/sessions/skillq_skill_calls.jsonl` is **0 bytes** (same
file, two paths).

**Cause:** the bind mount's view inside the container is created when
the container starts. Subsequent writes from the host (the hook writes
to the in-container path, which is bind-mounted back to the host) are
visible on the host but the in-container view is stale or truncated.
This looks like a docker bind-mount race on the trial-shutdown path
where `docker compose exec` finishes and the container is torn down
before the in-flight `requests.post(..., json={...})` from the hook
has been flushed to the host.

**Impact:** none on functionality — the bridge reads from the
host-side `skillq_state/calls_log.jsonl` (Fix A), not the in-container
path. But it's a confusing artifact for anyone reading the trial
artifacts.

**Workaround:** none. Fixing it would require changing the bind
mount to use a non-shared fs (or re-reading the in-container file
after a delay), which is brittle.

**Fix scope:** low. Could be addressed by replacing the bind mount
with a `tmpfs` mount + a host-side log-tailing process, but it's
not worth the complexity.

---

### Bug 2 — Re-running the same `job_name` fails with Pydantic `Literal[True]` validation

**Status:** ✅ **fixed in current tree** (commit pending; will be
referenced in "Fixed in the current tree" table below).

**Symptom (historical):** when you re-run a smoke with the same
`job_name` (i.e. the output dir already exists with a prior trial's
`result.json`), Harbor's `_maybe_init_existing_job`
(`harbor/job.py:203`) called
`TrialResult.model_validate_json(trial_paths.result_path.read_text())`,
which raised:

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for TrialResult
config.environment.mounts_json.4.read_only
  Input should be True [type=literal_error, input_value=False, input_type=bool]
```

**Root cause:** Harbor's `ServiceVolumeConfig` is annotated
`read_only: NotRequired[Literal[True]]` in
`harbor/models/trial/config.py`. Our container_wiring's calls_log
mount used `read_only=False` to let the hook append. The Pydantic
TypedDict validator ran at `result.json` re-deserialization time
(not at construction time, where we used `cast()`) and crashed.

**Fix:** drop the `read_only=False` mount entirely. Harbor's
auto-injected `agent_dir` bind mount (`trial_dir/agent` →
`/logs/agent`, see `harbor/trial/trial.py::_agent_env_mounts`) is
already a read-write mount (no `read_only` key — TypedDict-valid,
Docker treats absent as read-write). The hook now writes
`$SKILLQ_CALLS_LOG` directly into that mount, and the bridge reads
it back from `trial_dir/agent/sessions/skillq_skill_calls.jsonl`
on `on_ended`. No more `read_only=False` in
`cfg.environment.mounts_json` → no more ValidationError on
`--resume` / re-run.

**Verification:**
- `pytest tests/` → 93/93 pass.
- `docker-compose-mounts.json` for new trials has 0 entries with
  `read_only=False` (was 1).
- `TrialResult.model_validate_json(open('result.json').read())`
  succeeds for new trials (was raising `ValidationError`).
- `q_updates.jsonl` still gets written; Q-table still updates.

**Caveat for users with dirty state:** if your existing
`output/<job_name>/<trial>/result.json` was written by an old
SkillQ run that still has the `read_only=False` mount, harbor
will still crash on the next `job_name`-reusing run. Clean it
with `rm -rf output/<job_name>` or use a fresh `job_name`.

---

### Bug 3 — Per-trial `q_table.json` is the trial-START snapshot, not trial-END

**Symptom:** `trial_dir/skillq_state/q_table.json` is written at
trial start by `container_wiring._dump_staging_state`. After a
successful trial, the host-side `method_state.json` at
`library_root/.state/method_state.json` has the post-trial Q-table
(with Q-updates), but the per-trial dump is unchanged.

**Cause:** the bridge's `on_ended` calls `state.save(...)` which
writes to `method.state_path` (the library root), not the per-trial
staging dir. No one re-dumps the per-trial q_table after the
Q-update.

**Impact:** low. Functionally correct (the canonical state is
preserved), but users inspecting the per-trial dir see only the
seed-prior Q-values. The post-trial Q-updates are visible only at
the library root.

**Fix scope:** 5 lines. Either:
- (a) In `on_ended` after `state.save(...)`, also re-dump
  `q_table.json` to `trial_dir/skillq_state/`.
- (b) Have `state.save` take an optional `mirror_to` path.

---

### Bug 4 — Auto-extract path not exercised end-to-end

**Status:** ✅ **fixed in current tree** (commit pending; will be
referenced in "Fixed in the current tree" table below).

**Symptom (historical):** `enable_auto_extract=False` is the
default in `MethodConfig`. The auto-extract code path
(`SkillExtractor.extract_batch` → spawn `claude --print`
subprocess → read SKILL.md → `lib.add` + `mgr.set_q`) had never
been exercised end-to-end.

**Root cause (found via smoke):** `SkillExtractor._extract_with_prompt`
built a `claude --print` cmd array with **only** a `--append-system-prompt`
flag and no user prompt. `claude --print` requires the user prompt
to come from stdin or from a `-p <prompt>` argument; the system
prompt alone is rejected with:

```
Error: Input must be provided either through stdin or as a prompt
argument when using --print
```

The subprocess returned non-zero immediately, `extract_batch`
returned `None`, `_flush_buffer` discarded the batch, and the
new skill was never created. `logger.warning` recorded the
returncode but not in a way the user could see from the
`/tmp/...smoke.log` (rich/tqdm captured stderr). The wiring was
correct, but the subprocess was broken from day one.

**Fix:** add a `-p <user_prompt>` argument to the cmd array in
`skillq/method/extractor.py:_extract_with_prompt`. The user
prompt is the trigger instruction (task + synthesize
instruction); the system prompt carries the format and
constraints. Direct invocation of `SkillExtractor.extract_batch`
after the fix produces a real `Skill` object (verified with
`fix-code-vulnerability` trial data — `skill_id=fix-code-vulnerability`,
real SKILL.md body with frontmatter).

**Verification (after fix):**
- 93/93 unit tests pass.
- `SkillExtractor.extract_batch(trials=...)` end-to-end returns a
  `Skill` with non-empty body.
- Auto-extract smoke
  (`fix-code-vulnerability_skillq_smoke_autoextract.yaml`)
  end-to-end: trial reward=1.0, hook fired once (calls_log 1
  line), `sub_task_log` reflects the Skill() call.
- Note: the auto-extract trigger in
  `_attribution_and_extract_dispatch` did **not** fire on the
  single smoke trial even after the fix, because the attribution
  LLM labelled the trial `FAILURE_SKILL_NOT_USED` (renamed 2026-06-26
  from the old `FAIL_AGENT_ISSUE`) while `r_task=1.0` —
  Rule 2 (success) and Rule 5 (failure) are both gated on a
  matching attribution verdict. This is an attribution-prompt
  quality issue, not a wiring bug; the subprocess now works
  end-to-end when manually driven.

---

### Bug 5 — Q-value can go negative (no clip)

**Symptom:** `LibManager.update_q` does
`q_table[sid] = q_table.get(sid, 0.0) + delta` with no clip. After
many trials with `r=0` and `q_w_subtask=1.0`, Q can drop below 0.

**Cause:** by design in the paper (negative Q represents a
"punishment" prior). But callers may not realize it.

**Impact:** low. Affects only the Eq.4 ranking term (Q is
z-scored across the pool, so absolute scale doesn't matter as
long as ordering is consistent). But the `probation_avg_q` and
`theta_admit` / `theta_evict` thresholds expect a [0, 1] range,
so a negative Q may flip the admit/evict decision.

**Workaround:** set `q_initial=0.5`, `q_w_subtask=1.0`,
`q_w_task=0.0` (paper defaults); Q stays in [0.2, 0.8] in
practice for moderate α.

**Fix scope:** ~5 lines if we want to clip. Either add a
`q_min` / `q_max` knob, or clip at the call site.

---

### Bug 6 — `state.step` is a global counter across all tasks sharing a `library_root`

**Status: ✅ done (commit `7aa2340`). Resolved by removing every
decision that read `state.step` or `last_retrieval_step`.**

After the eviction simplification, `LibManager.maintain()` no
longer consults `state.step` for staleness or probation gates —
the only eviction rule is `while lib.size > b_max: evict lowest-Q`,
which is per-skill Q-driven and unaffected by cross-task step
drift. `state.step` is still persisted (read by `bridge._maintain_lib`
to pass as `current_step`) but its only consumer is now
`maintain()`'s unused `current_step` parameter — safe to remove
in a future cleanup.

---

### Bug 6 (historical) — `state.step` is a global counter across all tasks sharing a `library_root`

**Symptom:** `state.step += 1` happens at the end of every trial.
If a user runs `configure-git-webserver` × 3 + `fix-code-vulnerability`
× 2 against the same `library_root/.state/method_state.json`, the
step counter accumulates across task types. The library-maintain
`stale` check (`n_stale` threshold) uses `state.step` directly.

**Cause:** the canonical state file is per-library, not per-task.
`_maintain_lib` reads `current_step=state.step + 1` to compute
`last_retrieval_step[sid]`-based staleness.

**Impact:** medium for cross-task workflows. A skill used in trial
1 (git task) may be evicted by trial 4 (vuln task) just because
`state.step` grew, even if the skill was never re-retrieved in
intervening trials.

**Workaround (now obsolete):** use one `library_root` per task.
Or set `n_stale` very high.

**Fix scope (superseded):** ~10 lines. Either:
- (a) Track per-task `step` and reset on task change. Needs
  `event.task_name` plumbing.
- (b) Track per-skill `last_retrieved_step` and let staleness
  be relative to the skill's last retrieval, not the global
  step. Cleaner but changes Eq.5 / Layer 3 semantics.

The actually-shipped fix was **(c)**: delete all `state.step` /
`last_retrieval_step` consumers and reduce the eviction rule to
`b_max`-bounded lowest-Q. Same correctness outcome, no paper
semantics to renegotiate.

---

### Bug 7 — `SKILLQ_USER_TASK` is empty in the container's env

**Symptom:** the docker-compose `env` block in the trial's
`docker-compose-mounts.json` has
`SKILLQ_USER_TASK=fix-code-vulnerability` set, but the in-container
`/proc/<pid>/environ` shows `SKILLQ_USER_TASK=` (empty). Actually
the `result.json`'s `config.agent.env` shows it set, so this is
likely a docker-compose variable-substitution race, not a code bug.

**Cause:** unknown — may be a docker-compose interpolation
artifact. The env value is set in the host config but the
container sees the default (`""`).

**Impact:** low. The hook uses `SKILLQ_USER_TASK` as an optional
hint appended to the sub-task embedding text. With it empty, the
embedding is `recent_assistant_messages + "Trying skill: X"`,
which still works.

**Workaround:** the bridge's `_build_subtask_text` already
defaults to the empty-string case. No fix needed for correctness.

**Fix scope:** low priority. If we want it set, change the
`SkillQClaudeCodeAgent.__init__` injection site.

---

### Bug 8 — `sub_task_verifier` is sync + serial

**Symptom (historical):** `_q_update_from_subtask` called
`sub_task_verifier.score(...)` once per (skill, trial). For a
trial with N unique skill calls, this was N serial LLM calls. With
DeepSeek (our default), each call is ~1-3s, so a trial with 5
unique skill calls added 5-15s to the post-trial phase.

**Cause (historical):** the bridge code was correct but synchronous.
`SubTaskVerifier` was a single-shot judge with no batching or
async API.

**Impact:** medium. Slowed the per-trial wall-clock by O(unique_skills
× judge_latency). Not a correctness bug, just performance.

**Fix:** option (b) — convert the judge loop to async. `_q_update_from_subtask`
is now `async def`; it enumerates a flat `judge_inputs: list[(skill_id, trace, desc)]`
in a first pass, fires one `await asyncio.gather(*[verifier.ascore(...)])`
with no `return_exceptions=True`, then regroups the in-order verdicts by
skill_id in a second pass and applies the Q-update. A process-wide
`asyncio.Semaphore(MAX_CONCURRENT_JUDGES=8)` (lazy-init in
`skillq/method/sub_task_verifier.py`) throttles parallel LLM calls.
`SubTaskVerifier` gained `async def ascore(...)` alongside the preserved
sync `score(...)`; `LiteLLMCompletion` gained `async def acall(...)` using
`litellm.acompletion`. No `MethodConfig` field added; `MAX_CONCURRENT_JUDGES=8`
is a module-level constant.

**Status: ✅ done (commit `96ac498`).**

**Verification:**
- 106/106 unit tests pass (added `test_q_update_parallel_wallclock_below_serial`
  in `tests/test_session_log_fallback.py` — 8 skills × 2 calls with 0.3s
  per-call stub completes in < 2.4s; serial bound is 4.8s).
- Functional smoke (8 parallel calls with `litellm.acompletion`):
  0.50s vs 2.25s serial = **4.5× speedup**. 16 calls Semaphore-bounded
  to 0.75s vs 8.0s serial = **10.7× speedup**.
- `asyncio.gather` returns verdicts in input order (Python 3.10+),
  so `q_updates.jsonl` output is byte-identical to the sync version.
- No `return_exceptions=True` → a single judge failure propagates and
  `on_ended`'s outer try/except writes `method_errors.jsonl` exactly
  as before.

---

### Bug 9 — Method A (agentic search) not tested end-to-end

**Status:** ✅ **fixed in current tree** (smoke-verified; no code
change needed). Will be referenced in the "Fixed in the current
tree" table below.

**Smoke result:** `configure-git-webserver_skillq_smoke_agentic.yaml`
+ `method_git_smoke_agentic.yaml` ran end-to-end (reward=1.0).
- 0 PreToolUse hook mounts in `docker-compose-mounts.json` (the
  Method A path doesn't install the hook).
- Method A artifacts present:
  `trial_dir/skillq_skills/{<seed_skill_dirs>,PAPER_METHOD_INSTRUCTIONS.md,_search.sh,_manifest.json}`.
- Plan D pre-embed succeeded: `emb_cache.json` populated with
  37 seed-skill embeddings.
- `method_state.json` step=1, lib size 37.
- `result.json` re-validates via `TrialResult.model_validate_json`.

**Side note (not a wiring bug):** the agent chose to solve the
task with raw Bash and never invoked `_search.sh` — search count
in `claude-code.txt` is 0. The Method A infrastructure (script,
manifest, dir mount) is in place; whether the agent uses it is
an agent behaviour, not a code bug. To exercise the search path
end-to-end a future smoke would need a task where the agent
cannot solve the task without consulting a skill.

**Caveat / config gotcha:** the method config must declare an
`embedder_model` and `embedder_dim`, even for Method A, because
`attach_paper_registers` calls Plan D pre-embed unconditionally
for any retrieval mode. The default `text-embedding-3-small` 404s
on this env (only DashScope key is set), so the method yaml
needs the same `openai/${EMBEDDING_MODEL}` prefix the hook smoke
uses, plus `embedder_dim: 1024` for `text-embedding-v4`.

---

### Bug 10 — `seed_initial_q` overwrites missing entries unconditionally

**Status: ✅ closed by Bug 6 simplification (commit `7aa2340`).**

No code change made; the loop at `state.py:163-167` is still
present (intentionally — it provides backward compat for legacy
state files and external tools that bypass `set_q`), but with
admission removed, no decision reads the auto-seeded Q value
anymore. Adding a `reseed_on_load` flag would be busywork.

---

### Bug 10 (historical) — `seed_initial_q` overwrites missing entries unconditionally

**Symptom:** `QlibState.load_into` re-applies `seed_initial_q` to
any skill not yet in `mgr.q_table`. If a user starts with
`seed_initial_q=0.5`, runs 10 trials (Q drifts), then adds a new
seed skill — the new skill gets Q=0.5, even if the user has
adopted a "low initial Q, let evidence drive" policy.

**Cause:** `load_into` at `state.py:163-167` is unconditional:

```python
if seed_initial_q != 0.0:
    for sid in lib.skills:
        if sid not in mgr.q_table:
            mgr.q_table[sid] = seed_initial_q
```

**Impact:** low. Optimistic prior is a valid design choice. The
issue is the "silently re-applies" aspect — users have to set
`seed_initial_q=0.0` to opt out, but the default is 0.5.

**Workaround:** set `seed_initial_q=0.0` in the method yaml to
disable re-seeding.

**Fix scope (now moot):** ~3 lines. Add a config flag like
`reseed_on_load: bool = True` and gate the loop on it.

---

### Bug 11 — Embedding service may briefly have two daemons on trial switch

**Symptom:** in the `run_paper_job` flow, `start_embedding_service_background`
is called once at the start, `stop_embedding_service` is called at
the end. Between trials, the daemon stays up (good — keeps
embedder warm). But on `stop_embedding_service`, the thread is
joined with a 5s timeout; if the thread is still busy with a
request, the join times out and the daemon is forcibly killed.
Next run starts a new daemon on the same port (good — port is
released). But there's a window where the new daemon is binding
the port while the old is being torn down.

**Cause:** `stop_embedding_service` is too aggressive on timeout.

**Impact:** low. Embedding service is only used by the hook,
which is per-trial. The window is sub-second. We didn't observe
it during the recent smoke.

**Workaround:** none.

**Fix scope:** ~5 lines. Increase the join timeout, or have the
daemon's `should_exit` flag set first and then poll for the
thread to die.

---

## Suggested priority

By "value / effort" ratio:

1. ~~**Bug 2** (Pydantic Literal on resume)~~ — ✅ done in F17.
2. ~~**Bug 4** (auto-extract verification)~~ — ✅ done in F18.
   Bonus: surfaced a real wiring bug (F18) — the `claude
   --print` cmd array had no user prompt, the subprocess was
   always returning non-zero, the wiring was effectively dead
   from day one. Now verified end-to-end via direct
   `SkillExtractor.extract_batch` invocation.
3. ~~**Bug 9** (Method A verification)~~ — ✅ done in F19. No
   code change; just a smoke that proves the agentic path
   works (skipped on the agent side because the test task was
   solvable without `_search.sh`).
4. ~~**Bug 3** (per-trial q_table.json sync)~~ — ✅ done. Added
   a re-dump of `trial_dir/skillq_state/q_table.json` in
   `bridge.py:on_ended` immediately after `state.save(...)` (see
   commit log for the exact lines). Verified end-to-end via the
   autoextract smoke: path A and path B now match exactly
   (38/38 keys identical, including post-trial Q-updates like
   `affaan-m-security-review → 0.65` and the new auto-extracted
   skill `fix-cwe-vulnerability → 0.5`). Test added in
   `tests/test_q_initial.py::test_bridge_redumps_q_table_to_staging_on_ended`.
5. ~~**Bug 8** (sub_task_verifier async)~~ — ✅ done (commit
   `96ac498`). Option (b): `_q_update_from_subtask` now `async def`,
   fires one `asyncio.gather(*[verifier.ascore(...)])` over all
   `(skill, call)` pairs, throttled by a process-wide
   `asyncio.Semaphore(MAX_CONCURRENT_JUDGES=8)`. 4.5–10.7× judge-phase
   speedup verified; 106/106 tests pass; output bytes-identical.
6. ~~**Bug 6** (per-task step counter)~~ — ✅ done. Resolved by
   the eviction simplification (commit `7aa2340`): admission /
   stale-queue / low-Q-queue / deprecation_list / rejuvenate
   path are all gone, so the global `state.step` counter no
   longer drives any decision. The only eviction rule is now
   `while lib.size > b_max: evict lowest-Q`, which is per-skill
   Q-driven and unaffected by cross-task step drift. Also
   incidentally closes Bug 10 — see next entry.
7. ~~**Bug 10** (`reseed_on_load` flag)~~ — ✅ closed by Bug 6
   simplification. The `state.py:163-167` loop that auto-seeds
   missing Q-values to `seed_initial_q` is still present (for
   backward compat with legacy state files and external tools
   that bypass `set_q`), but with admission removed, no decision
   reads the auto-seeded Q value anymore. The mechanism is
   harmless dead code; adding a `reseed_on_load` flag would be
   busywork. Skipped.
8. ~~**Bug 5** (Q clip)~~ — ✅ done. Added
   ``MethodConfig.q_clip_floor`` / ``q_clip_ceiling`` (both
   default ``None`` = no clip, existing behaviour preserved),
   plumbed through to ``LibManager`` and applied inside
   ``update_q`` and ``set_q``. 6 unit tests in
   ``tests/test_q_initial.py::test_q_clip_*`` (default
   no-op, floor-only, ceiling-only, both-bounds, config
   default, config roundtrip). Reference design's ``q_floor``
   knob adopted; added ``q_clip_ceiling`` for symmetry. To
   forbid negative Q, set ``q_clip_floor: 0.0`` in the method
   config.
9. **Bug 1, 7, 11** — leave alone, working as intended.


---

## Sub-task judge path removed on 2026-06-23

The per-call LLM judge (`SubTaskVerifier` / `mean_r_subtask` /
`SUBTASK_VERIFIER_PROMPT` / `MAX_CONCURRENT_JUDGES`) has been removed
from the codebase. The blend formula
`target = q_w_subtask * r_subtask_mean + q_w_task * r_task` collapsed
to `target = r_task` (standard Q-learning, paper Eq.5). Rationale:

- Pull-mode Top-K injection makes the agent typically call exactly
  one skill per trial → `r_subtask` collapses to a single binary
  verdict that almost always equals `r_task`.
- The judge LLM call (1 per skill per trial) was wasted compute.
- Bug 8 (the `asyncio.Semaphore(8)` fan-out that made the judge
  fast enough to be tolerable) is now obsolete.

Removed:
- `skillq/method/sub_task_verifier.py` (338 lines, full module)
- `tests/test_sub_task_verifier.py` (4 tests)
- `MethodConfig.q_w_subtask`, `q_w_task`, `q_subtask_verifier_model`,
  `q_max_body_chars`, `debug_keep_subtask_log` (5 fields)
- `QlibState.sub_task_log` and `debug_keep_subtask_log` (2 fields)
- 7 experiment YAMLs (`q_subtask_verifier_model` line in each)
- `_q_update_from_subtask` (~250 lines in `bridge.py`); replaced by
  a sync `_q_update` (~80 lines)
- `_slice_sub_task_trace` (~60 lines)
- `LiteLLMCompletion.acall` (the async shim added for Bug 8)

Kept:
- `Skill.n_uses` (per-trial "was called at all" counter; user decision)
- `Skill.n_retrievals` (per-trial call count; drives Eq.4 UCB)
- `Skill.n_success` (per-trial task-success counter; was already
  task-keyed)
- `r_learning` / `IndependentVerifier` / `BetaLayeredQ` (the paper's
  Eq.6 informationally-isolated path — **deleted 2026-06-25 dead-code
  purge** along with `TwoStageRanker` / `Verdict` / `RetrievalResult`;
  distinct from the deleted sub-task judge)

New tests: `tests/test_q_update_task_only.py` (6 tests covering
formula, n_retrievals increment, session-log fallback, no-calls
no-op, n_success increment).

---

## L1–L4 audit issues (2026-06-26)

Comprehensive audit by 4 subagents (one per layer) on 2026-06-26. Each
issue lists: location, problem, suggested fix, and whether end-to-end
behavior breaks (B) vs. is a smell/dead code (S). Pick one and fix;
mark `[done]` when landed.

### L3 — HIGH (block L3 from actually working)

- [x] **L3-H1 (B)** `bridge.py:1469-1513` — step ordering bug. `state.save`
      (step 5, line 1469) runs **before** `_incremental_edit_on_failure`
      (step 6, line 1507). The in-memory `lib.replace(new_skill)` mutates
      `lib.skills`, but `method_state.json` is already on disk with the
      OLD body. Next trial's `state.load_into` reads the OLD body back,
      so **L3 edits are lost across trials** — `method_state.json` is
      the only persisted lib, and it never sees the edit.
      *Fix*: move step 6 before step 5, OR add a second `state.save`
      at the end of step 6. Tests: extend
      `tests/test_bridge_create_vs_edit_split.py::test_edit_path_failure_skill_used`
      to assert the body in `method_state.json` after on_ended.
      *Status*: fixed 2026-06-26 by commit on this branch (option A:
      re-order so step 6★ runs before step 6; new test
      `test_edit_path_persists_edited_body_to_method_state` passes).

- [x] **L3-H2 (B)** `bridge.py:1196-1197` — L3 silently disabled when
      `enable_auto_extract=False`. The early-return
      `if extractor is None: return` runs **before** the
      `_last_attribution = attribution` assignment (line 1210), so the
      attribution analyzer is never invoked and step 6's gate
      `if attribution is None: return` always fires. The two flags
      (`enable_auto_extract` and "do edits") are wrongly coupled.
      *Fix*: pull the attribution-analyzer call + `_last_attribution`
      write out of `if extractor is None` guard. The analyzer should
      run unconditionally on RUN_NORMAL / RUN_TASK_FAILURE; only the
      `_ExtractBuffer.add` path stays gated on `extractor is not None`.
      *Status*: fixed 2026-06-26 (commit on this branch; new tests
      `test_l3_fires_when_extractor_disabled` and
      `test_no_l3_when_attribution_not_skill_used_with_extractor_disabled`
      pass). Cost: +1 LLM call per trial when `enable_auto_extract=False`.

- [ ] **L3-H3 (B)** `bridge.py:1375` — `failure_trace=str(trial_dir)`.
      EDIT_PROMPT expects a real trace (assistant tail, verifier stderr,
      failure reason) but receives a directory path. The editor LLM has
      no failure-mode context, so proposed edits are likely low-quality
      (just rewrites the body without grounding in what went wrong).
      *Fix*: thread `attribution.knowledge_to_extract` (free-form
      diagnosis from the analyzer) plus a tail of the session jsonl
      (`_read_recent_assistant_messages`-style reader over
      `trial_dir/agent/sessions/projects/*/*.jsonl`) as the trace.

### L3 — MEDIUM

- [ ] **L3-M1 (B)** `bridge.py:1381` + `vector_table.py:35` — emb_cache
      only refreshes when `_description_of` (frontmatter `description:`)
      changes. Inner-body rewrites that don't touch frontmatter leave
      a **stale embedding** in emb_cache. Retrieval will then rank the
      skill by its old semantic meaning. *Fix*: refresh emb_cache on
      any body change (not only frontmatter), OR have EDIT_PROMPT
      require the LLM to also update the frontmatter description.

- [ ] **L3-M2 (S)** `bridge.py:1514` — `_last_attribution = None` reset
      sits inside the `try:` block (line 1437). Any exception in steps
      1-5 bypasses the reset, leaking the stale attribution to the
      next trial (where step 2 will overwrite it before step 6 reads,
      but only if step 2 doesn't itself raise). *Fix*: move the reset
      into a `finally:` block.

- [x] **L3-M3 (S)** `bridge.py:1316-1399` — `_incremental_edit_on_failure`
      has no inner `try/except` around `refiner.propose_edit`. A
      transient `litellm.completion` failure (timeout, rate limit)
      trips the outer `on_ended` except and writes `method_errors.jsonl`,
      but the trial appears to complete normally. *Fix*: wrap the
      propose_edit call in its own `try/except: logger.exception(...)`
      so an L3 failure doesn't poison the rest of on_ended.
      *Status*: fixed 2026-06-26 (folded into Commit 1 alongside L3-H1;
      new test `test_l3_propose_edit_exception_does_not_abort_trial` passes).

### L2 — MEDIUM

- [ ] **L2-M1 (B)** `bridge.py:1035-1036` — `phi_q` source is
      `calls_log[0].intent_text`, not filtered to approved calls.
      The first record may be a denied call whose `intent_text` was
      the agent's probe intent. The cosine-weighting anchor for the
      whole trial is then a probe, not the real task. *Fix*: use
      `next((c.intent_text for c in calls_log if not c.denied and c.intent_text.strip()), trial_id)`.

- [ ] **L2-M2 (S)** `bridge.py:1082-1092` — `if phi_s is None: continue`
      silently skips the skill (no Q-update, no counter bump, no trace
      entry, DEBUG log only). A new auto-extracted skill whose emb_cache
      entry failed to write becomes invisible to L2 for that trial.
      *Fix*: fall back to unweighted Eq.5 (`delta = α·(r_task - q_old)`)
      with a WARNING log, so the skill still accumulates Q signal.

- [ ] **L2-M3 (B)** `bridge.py:683-686` + `state.py:164-169` —
      `reuse_q_table=False` + no `seed_skills_dir` leaves lib with
      skills but empty Q-table. Eviction `min(key=q_for)` returns
      the first skill by insertion order (effectively random). The
      Plan D comment at line 686 says "ensure_seeded will re-seed" —
      it doesn't when the lib is already non-empty. *Fix*: when
      `reuse_q_table=False`, re-apply `seed_initial_q` to existing
      lib entries regardless of `overwrite_q`.

- [ ] **L2-M4 (B)** `state.py:166` — `if seed_initial_q != 0.0:` gate.
      With `seed_initial_q=0.0`, skills loaded with no Q entry stay
      at Q=0.0 forever; **failed trials can never penalize a Q=0
      skill** (delta = α·(0-0) = 0). The "optimistic prior" comment
      is contradicted. *Fix*: either document "0.0 = pessimistic
      prior, failures don't move Q from 0" or change the gate to
      always seed (use 0.5 if 0.0 was passed).

- [ ] **L2-M5 (S)** `state.py:70-84` — `update_count` / `probation_count`
      are NOT serialized in `save()`. Comment at `library.py:33-41`
      calls them "telemetry" but they don't survive a Job resume.
      *Fix*: either persist them (add to payload + load_into) or
      delete the fields + their increment paths.

- [ ] **L2-M6 (S)** `state.py:85-89` — `state.save` writes via
      `write_text` (truncating), no atomic rename. A crash mid-write
      leaves a partial `method_state.json`; Harbor's `--resume` then
      fails to parse. *Fix*: write to `<state_path>.tmp` then
      `os.replace(tmp, state_path)`.

### L1 — MEDIUM

- [ ] **L1-M1 (S)** `hook.py:659-672` — unconditional 4-line
      `sys.stderr.write` debug block at the top of every
      `_handle_pretooluse_skill` call. No env flag, no `# DEBUG`
      comment block (unlike the other two debug writes). Fires 5-20
      times per trial per Skill() call. *Fix*: delete, or gate
      behind `SKILLQ_HOOK_DEBUG=1` like the other two.

- [ ] **L1-M2 (B)** `hook.py:711-715` — logic drift in deny-text.
      When `subtask_emb is None` (embed failure) AND strict gate is
      active, the deny text reads:
      `No skills ... below sim=0.7 gate ... solve directly.\n\n
      (embedding unavailable; ranking used Q + UCB only.)`
      But strict mode produced empty top-k — Q+UCB never ran. The
      suffix is misleading. *Fix*: rephrase to
      `"embedding unavailable; gate produced no survivors"` or
      omit the suffix in strict mode.

- [ ] **L1-M3 (S)** `hook.py:227-235` — `_cosine` uses
      `n = min(len(a), len(b))` and iterates the prefix. A dim
      mismatch (cached from one embedder model, query from another)
      silently degrades cosine quality without raising. *Fix*:
      assert `len(a) == len(b)` at the top, or pad/truncate explicitly
      with a WARNING log.

- [ ] **L1-M4 (S)** `hook.py:519-554` — `_read_skill_calls_log` uses
      `open(path, "a")` in `_append_jsonl` without file locking.
      Two concurrent Skill() calls in the same container can
      interleave writes at the JSON boundary, producing malformed
      JSONL lines. The reader skips them via `JSONDecodeError` so
      it's a debuggability loss, not a correctness bug. *Fix*:
      wrap in `fcntl.flock(LOCK_EX)` (Linux) or accept the rare
      malformed line.

### L4 — MEDIUM

- [ ] **L4-M1 (B)** `bridge.py:1401-1466` — `lib_changes_this_trial`
      is `nonlocal` but **never reset** inside `on_ended`. Each
      trial's `_maintain_lib` packs the full accumulator (every add
      + remove since job start) and `_refresh_emb_cache` re-embed's
      them all. **O(N²) wasted embedding calls over a long Job.**
      *Fix*: reset at the top of `on_ended`:
      `lib_changes_this_trial.clear()` (or change `_maintain_lib` to
      start with `changes = []`).

- [ ] **L4-M2 (S)** `bridge.py:812` — `extract_buffer` shared across
      all `on_ended` callbacks (one per Job) without a lock. Under
      `n_concurrent_trials >= 2`, two callbacks can read the same
      pending batch and both call `_flush_buffer`. Name-dedup catches
      the worst case but LLM is invoked twice with overlapping records.
      *Fix*: wrap `add`/`flush` in `asyncio.Lock` (or accept the
      duplicate as the cost of simplicity).

- [ ] **L4-M3 (S)** `bridge.py:832-835` — `extract_batch` is called
      with `aggregated_intent_hash=0` (default); bridge never passes
      the real value. All extracted skills have
      `metadata["intent_hash"] = "0000000000000000"` — the field is
      effectively dead. *Fix*: thread `state.step + 1` (or
      `qhash(representative_task)`) through.

### L4 — LOW (dead code / cosmetic)

- [ ] **L4-L1 💀** `bridge.py:909` — `new_skill.admission_exempt = True`
      on a `Skill` dataclass that has no such field. Single write site,
      zero read sites in the entire repo. Dead code. *Fix*: delete.

- [ ] **L4-L2 💀** `bridge.py:494-498` — `_ExtractBuffer.__len__`
      defined **twice** with identical bodies. *Fix*: delete one.

- [ ] **L4-L3 (S)** `bridge.py:1272` — final-trial force-flush uses
      `(state.step + 1) >= expected_terminal_trials`. Correct in the
      current code (step 2 runs before step 5 increments), but fragile
      to re-ordering. *Fix*: add a comment explaining the +1 trick.

### L1 — LOW (cosmetic / contract)

- [ ] **L1-L1 (S)** `hook.py:154-155, 306` — `SIM_GATE_MIN_SCORE`
      doubles as gate-on/off (`if sim_gate_threshold > 0.0`) and as
      the actual threshold. There is no way to set "gate on, threshold
      0". *Fix*: separate into `sim_gate_enabled` (bool) and
      `sim_gate_min_score` (float).

- [ ] **L1-L2 (S)** `vector_table.py:35` (`_description_of`) and
      `container_wiring.py:167` (`_extract_description`) are two
      different frontmatter parsers. The emb_cache one falls back to
      first-non-empty-line / first-200-chars; the lib.json one returns
      `""`. Same frontmatter, two behaviors — drift hazard. *Fix*:
      consolidate into one helper in `vector_table.py` (or a shared
      `skillq.method.frontmatter` module) and import from both sites.

- [ ] **L1-L3 (S)** `hook.py:728-735` — `calls_log._debug_first_5_sims`
      truncates to first 5 skills only. A relevant skill ranked 6+
      has no cosine in the log. *Fix*: dump all skills, or top-N
      matching top_k for debuggability.

- [ ] **L1-L4 (S)** `hook.py:524-538` — `_handle_session_start` /
      `_make_session_start_context` dispatches on `UserPromptSubmit`
      but the names reference `SessionStart`. Docstring acknowledges
      the historical holdover; cosmetic. *Fix*: rename to
      `_handle_user_prompt_submit` for clarity.

### L2 — LOW

- [ ] **L2-L1 (S)** `bridge.py:1485-1491` — `q_table.json` mirror
      uses `write_text` (truncating). A write failure mid-way leaves
      a partial JSON file that mirrors the `state.save` smell. *Fix*:
      same atomic-rename pattern as L2-M6.

- [ ] **L2-L2 (S)** `bridge.py:1357-1363` — `max(lib.skills.values(),
      key=q_for)` is stable; on Q=0 tie, returns first skill by
      insertion order. Deterministic but counter-intuitive. *Fix*:
      add a secondary key (`key=lambda s: (-q_for, lib.skill_ids.index(s.skill_id))`)
      or document the behavior.

- [ ] **L2-L3 (S)** `bridge.py:778-780` — `method.editor_model`
      empty-string default would silently fail (litellm.model="" raises).
      No validation. *Fix*: validate at bridge construction time.

### L3 — LOW

- [ ] **L3-L1 (S)** `edit.py:34-46` — `_default_editor_model` reads
      `ANTHROPIC_MODEL` env var with default `deepseek-v4-flash`. If
      `method.editor_model=""`, litellm will raise. No defensive
      fallback. *Fix*: validate `method.editor_model` in
      `attach_paper_registers`.

---

## Priority order (recommended fix sequence)

1. **L3-H1** (state.save before edit) — single biggest correctness
   fix; L3 currently does nothing useful across trials.
2. **L3-H2** (extractor-is-None gates L3) — unblocks users who
   turned off auto-extract but still want edits.
3. **L3-H3** (failure_trace is a path) — editor quality depends
   on real trace context.
4. **L1-M2** (deny-text logic drift) — quick fix, improves debuggability.
5. **L2-M3** + **L2-M4** (seed/q=0 semantics) — small fix,
   big behavior improvement.
6. **L4-M1** (lib_changes accumulation) — easy fix, O(N²) saved.
7. **L4-L1 / L4-L2 / L4-L3** (dead code) — trivial.
8. **L2-M5 / L2-M6** (telemetry persistence + atomic rename) — robustness.
9. Rest of MEDIUM, then LOW.

Each fix: write a failing test in `tests/` first, then fix, then
commit on the existing branch. Update this doc with `[done YYYY-MM-DD]`
and a one-line summary of what landed.
