# Changelog

All notable changes to `skillq` (the branch-style entrypoint that re-uses
the upstream `skills_vote` lifecycle AND runs the SkillQ paper's
four-layer method on top of Harbor) are documented here.

> **2026-06-30 — Remove L4 semantic dedup + extract-prompt soft hint**
>
> The cosine-based semantic dedup at the L4 extract boundary (L1 Hard
> Gate + L3 attribution routing + name-collision check is judged
> sufficient — L1's `no_relevant_skills` already certifies "lib has
> no skill for this task", so guarding the new-skill-vs-existing-skill
> cosine is redundant). Accepts the risk of paraphrase-duplicate
> skill accumulation over long runs.
>
> - `skillq/runtime/steps.py:_flush_buffer` — removed the 46-line
>   semantic-dedup block; `extract_batch(...)` no longer passes
>   `available_skill_names`.
> - `skillq/config.py:MethodConfig` — removed `semantic_dedup_threshold`
>   field + `EVOLVE_UNPACK` mapping entry.
> - `skillq/layers/l4_evolve/prompts.py` — removed the
>   "Available skills (avoid duplicates)" section and the
>   "{available_skills}" placeholder from both success and failure
>   extract prompts; success prompt step 4 ("Do NOT create a skill
>   that is redundant…") removed as well.
> - `skillq/layers/l4_evolve/create.py:SkillExtractor.extract_batch` —
>   removed the `available_skill_names` parameter and the
>   `available_skills` format-kwarg.
> - YAML configs (`tb2_skillq_full/smoke/e2e`, `swebenchpro_skillq`):
>   dropped `semantic_dedup_threshold` line.
> - Tests: removed `tests/test_semantic_dedup.py` (whole file, 9 tests
>   + 2 helpers) and 5 `semantic_dedup_threshold` tests from
>   `tests/test_method_config_new_fields.py`; cleaned the obsolete
>   `sync_embed` comment block in `tests/test_bridge_create_vs_edit_split.py`.
>
> Not in scope: L3 attribution prompt's `{available_skills}` placeholder
> (path-mapping JSON, separate mechanism).

> **2026-06-29 — Dead-code cleanup + docstring rewrite (layers/runtime refactor follow-up)**
>
> Follow-up to the uncommitted `paper_mode/→skillq_runtime/→layers/+runtime/` refactor:
> - Deleted physical dead dirs: `skillq/method/__pycache__/`, `skillq/skillq_runtime/__pycache__/`, `skillq/paper_mode/` (root-owned Docker residue, needs manual `sudo rm -rf`).
> - Deleted `skillq/layers/l4_evolve/dispatcher.py` — exported `dispatch_evolve()` was never called (the live rule table is `runtime/steps.py:step_dispatch_evolve`).
> - Rewrote 47 `_legacy_runtime`/`_legacy_method` docstring references + 10 bare `skillq_runtime`/`skillq.method` references across 35 files to point at current canonical module paths (`layers/`, `runtime/`, `services/`, `shared/`).
> - Fixed stale "paper"→"skillq" project-name in `_resolvers.py` + `env.py` docstrings.
> - Fixed `experiments/RUNNING.md:202` outdated `import_path: skillq.skillq_runtime.agent` → `skillq.runtime.agent`.
> - Updated `README.md` layout section to the layers/runtime/services/shared structure.
>
> No behavior change. Regression: `import skillq` + `ruff check` + `pytest` pass.

> **2026-06-26 — Attribution enum rename + L3/L4 create-vs-edit split + L1 force-use text**
>
> Three coordinated changes that make the L1→L3→L4 contract explicit.
>
> 1. **`Attribution` enum renamed.** Two members renamed to match the
>    bridge action they trigger; one member deleted as structurally
>    unreachable under the new force-use hook.
>    - `FAIL_SKILL_ISSUE` → `FAILURE_SKILL_USED`
>    - `FAIL_AGENT_ISSUE` → `FAILURE_SKILL_NOT_USED`
>    - `SUCCESS_VIEWED_SKILL_BUT_NOT_USED` → removed
>
> 2. **Create/Edit split driven by attribution.** Previously
>    `_incremental_edit_on_failure` fired on every failed trial with a
>    non-empty lib (independent of attribution), and
>    `_attribution_and_extract_dispatch` routed both `FAIL_AGENT_ISSUE`
>    and `FAIL_SKILL_ISSUE` into the L4 Create path. New routing:
>
>    | r_task | Attribution             | Action                       |
>    |--------|-------------------------|------------------------------|
>    | 1      | `SUCCESS_NO_SKILL_SEEN` | L4 Create (success prompt)   |
>    | 0      | `FAILURE_SKILL_NOT_USED`| L4 Create (failure prompt)   |
>    | 0      | `FAILURE_SKILL_USED`    | L3 Edit (top-Q skill in place)|
>    | 1      | `SUCCESS_SKILL_USED`    | no-op                        |
>    | 0      | `FAIL_ENV_ISSUE`        | no-op                        |
>
>    The Q-update formula is unchanged. The new gate uses a
>    closure-cached `_last_attribution` to avoid a second LLM call per
>    trial.
>
> 3. **Hook force-use text.** `hook._format_top_k` and
>    `hook._format_pull_context` closing lines changed from "or skip if
>    none fit" (advisory) to "You MUST call Skill() with one of these"
>    (required). The hook itself remains fail-open at the protocol
>    level, but the text sharpens the contract: agents are now told to
>    call Skill() with one of the listed candidates before continuing
>    with other tools. The empty top-k path ("no relevant skills, solve
>    directly") is unchanged — MUST-call language would be a lie if
>    there is nothing to call.
>
> Files touched:
> - `skillq/method/attribution.py` — enum rename + parse/clamp defaults
> - `skillq/method/prompts.py` — enum string literals refreshed
> - `skillq/skillq_runtime/bridge.py` — Rule 2/5 tuples reduced;
>   `_incremental_edit_on_failure` gated on `FAILURE_SKILL_USED`;
>   closure-cached `_last_attribution` threaded from step 2 to step 6
> - `skillq/skillq_runtime/hook.py` — MUST-call text in
>   `_format_top_k` / `_format_pull_context`
> - `skillq/skillq_runtime/config.py` — `extract_every_n_trials`
>   docstring updated to the new enum set
> - 4 test files renamed; 1 structurally-dead test deleted; 3 new test
>   files added (`test_attribution_rename.py`,
>   `test_bridge_create_vs_edit_split.py`,
>   `test_hook_force_use_text.py`)
> - `doc/bug_to_fix.md`, `experiments/RUNNING.md` — references updated

> **2026-06-25 — L4 quality gates: structural validation + semantic dedup**
>
> Two new gates at the L4 extract boundary:
>
> 1. **`_collect_skill` enforces failure-prompt structure.** Failure-mode
>    skills produced by `BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT` must
>    contain both a "Diagnostic checklist" section and a "Stop signal"
>    section (case-insensitive). The prompt advertises this as a contract;
>    this commit makes the bridge actually enforce it.
>    - `SkillExtractor.enforce_failure_skill_structure` (default `True`)
>    - `MethodConfig.enforce_failure_skill_structure` (default `True`)
>
> 2. **`bridge._flush_buffer` adds cosine semantic dedup.** Previously,
>    dedup was kebab-case name-only — two semantically equivalent skills
>    with different names would both enter the lib. The new dedup embeds
>    the new skill's description and skips it if max cosine ≥ threshold
>    against any existing skill's cached embedding. Falls open on embed
>    failure (warn, proceed to name-based dedup).
>    - `MethodConfig.semantic_dedup_threshold` (default `0.85`, range
>      `[0, 1]`; set to `0.0` to disable)
>
> Implementation:
> - `skillq/method/extractor.py` — new dataclass field + structural guard
>   in `_collect_skill`
> - `skillq/skillq_runtime/bridge.py` — `_extractor_for_mode` propagates
>   the flag; `_flush_buffer` gains the cosine-dedup block
> - `skillq/skillq_runtime/config.py` — two new fields
>
> Tests: 34 new (10 for structural validation, 9 for semantic dedup
> full-flow, 8 for the new MethodConfig fields, 7 for dead-code
> removal). **253/253 pass**.

>> **2026-06-25 — Dead-code purge: BetaLayeredQ / IndependentVerifier / TwoStageRanker**

> Three classes in `skillq/method/` were never wired into the runtime:
>
> | Deleted | Reason |
> |---|---|
> | `BetaLayeredQ` (Eq. 6 β-mixed Q-update) | Runtime uses plain Eq. 5 since 2026-06-23 |
> | `IndependentVerifier` (Sec. 3.2 information-isolated verifier) | Only consumer was `kappa_sweep.py`; with `BetaLayeredQ` gone, `r_learning` has no consumer |
> | `TwoStageRanker` (Eq. 4 two-stage retrieval) | Superseded by `hook.py:_score_skills` (Hard Gate + multiplicative scoring) |
>
> Also removed:
> - `Verdict` / `RetrievalResult` (`skillq/method/types.py`) — only used by deleted modules
> - `forgetting_rate_upper_bound` (`skillq/method/library.py`) — theoretical helper
> - `VERIFIER_PROMPT` (`skillq/method/prompts.py`) — only used by `IndependentVerifier`
> - `MethodConfig.alpha / beta / increment_clip` — Eq. 6 knobs
> - `experiments/run/kappa_sweep.py` — only consumer of `IndependentVerifier`
>
> `skillq/method/__init__.py` rewritten to export only what the runtime
> imports. `skillq/method/retrieval.py` trimmed to keep only
> `Embedder / StubEmbedder / LiteLLMEmbedder` (which the bridge still
> uses for `emb_cache.json` population).
>
> The algorithmic truth now lives entirely in `skillq/skillq_runtime/`
> (`hook.py` for L1, `bridge.py` for L2–L4). `skillq/method/` is
> reduced to orchestration primitives.
>
> 219/219 tests pass after the deletion.

>>> **2026-06-25 — Bridge skips Q-update for hook-denied calls**
>
> The strict Hard Gate (entry below) fixed **context pollution** but
> the bridge was still updating the Q-table for denied calls. Smoke
> evidence (chess-best-move, 1-task):
>
> | Hook decision | n_retrievals | Q-update | n_uses | n_success |
> |---|---|---|---|---|
> | approved=True  | +1 | α·(r−Q) | +1 if r | +1 if r |
> | approved=False (denied) | **no change** | **skipped** | **no change** | **no change** |
>
> Before this fix, a denied call still produced the Eq.5 update
> (`Q += α·(r_task−Q)`) and incremented `n_retrievals`/`n_uses`/
> `n_success`. That violated the user's strict-gate design intent:
>
> > "严格禁止和当前任务不相关的技能污染agent上下文和污染q值演化逻辑"
>
> After the fix, denied records are skipped at the bridge's
> `by_skill` grouping stage. They are still kept in
> `skillq_skill_calls.jsonl` (for debugging) but trigger no
> Q-side effects.
>
> Implementation:
> - `hook.py` writes an explicit `"denied": not approved` field
>   alongside `approved` in each calls_log record.
> - `bridge.py:_SubTaskCallRecord` gains a `denied: bool = False`
>   field; `_read_skill_calls_log` parses it with back-compat
>   (`rec.get("denied", not approved)` for old JSONL files
>   written before this field existed).
> - `bridge.py:_q_update`'s `by_skill` loop skips records with
>   `c.denied=True` (debug-log only).
> - `bridge.py:_extract_skill_calls_from_session` keeps
>   `denied=False` (agentic-mode fallback — every Skill call
>   the agent successfully executed is implicitly approved).
>
> Tests: 8 new in `tests/test_bridge_denied_skip.py`:
> - 3 unit tests on `_SubTaskCallRecord` / `_read_skill_calls_log`
>   parsing + back-compat for the new `denied` field.
> - 5 end-to-end tests on `bridge.attach_paper_registers` exercising:
>   - all-denied → Q stays at seed (the user's chess-image-to-move case)
>   - mixed approved/denied → only approved Q-updates
>   - all-approved → regression guard (Eq.5 fires normally)
>   - failed trial + denied → no Q punishment for irrelevant skill
>
> 240/240 tests pass (was 232 before this change).
>
> Smoke verification (chess-best-move, 1-task): hook returned
> `top_k=[]`, `approved=false`, `denied=true`. chess-image-to-move
> Q stayed at **0.5** (seed) — n_retrievals=0, n_uses=0,
> n_success=0. Agent still solved the task (reward=1.0).

>> **2026-06-25 — Strict Hard Gate: `sim_gate_floor` default 1 → 0**
>
> The Hard Gate (`sim_gate_min_score=0.7`) drops candidates whose
> raw cosine similarity to the sub-task intent is below threshold.
> The accompanying `sim_gate_floor` parameter was the **minimum
> number of candidates to keep** when the gate would otherwise
> leave the list empty. Its old default of 1 was a footgun:
>
> - The agent's PreToolUse hook received a "best of a bad lot"
>   top-k of irrelevant skills (scored by UCB-only), which
>   polluted its context ("maybe try one of these?").
> - Those same skills got their `n_retrievals` counter incremented
>   in the Q-table, polluting Q-value evolution.
>
> New default: `sim_gate_floor=0` (strict mode). When every
> candidate is below the 0.7 sim gate, the hook returns an
> **empty top-k** and emits an explicit "no relevant skills"
> message — the agent is expected to solve the sub-task
> directly without invoking Skill(). Q-table `n_retrievals`
> does NOT increment for any skill in that trial.
>
> Opt back into the legacy behavior by setting
> `sim_gate_floor: 1` (or higher) in `method-config`. The
> pre-fix fall-through is replaced with a stricter "keep
> top-N by raw sim" path: if the gate leaves fewer than
> `sim_gate_floor` survivors, we keep exactly the top-N
> (not the entire pre-gate list).
>
> Implementation:
> - `MethodConfig.sim_gate_floor` default 1 → 0
>   (`skillq/skillq_runtime/config.py`).
> - `SKILLQ_SIM_GATE_FLOOR` env var default `"1"` → `"0"`
>   (`hook.py:147`).
> - `_score_skills` gate branch rewritten to enforce
>   `len(kept) == sim_gate_floor` instead of falling through
>   to the full pre-gate list.
> - `_format_top_k` and `_format_pull_context` explicit
>   "No skills in the library are relevant" message when
>   `top_k` is empty (replaces the confusing "Top-0 ... Re-call
>   Skill with one of these" wording).
> - `_cosine` tolerates numpy arrays (`not a` raised ValueError
>   on `np.ndarray`).
>
> Smoke verification (chess-best-move, 1-task): with strict
> mode, the hook returned `top_k=[]` and `approved=false`,
> causing the agent to solve the task directly (reward=1).
> At the time this entry was written, the bridge still Q-updated
> denied calls — that bug was fixed in the entry above
> ("Bridge skips Q-update for hook-denied calls"). 232/232
> tests pass (10 new in `tests/test_hard_gate_strict.py`).
>> **2026-06-25 — `MethodConfig.reuse_q_table` + `reuse_embedding_cache`
> + opt-in state co-location**
>
> Two independent bool flags (both default `True`) let users force
> fresh-start semantics for the Q-table and emb_cache separately:
>
> ```yaml
> reuse_q_table: false            # drop Q values; re-seed with seed_initial_q
> reuse_embedding_cache: false    # drop emb_cache; re-embed every skill
> ```
>
> Typical use cases:
> - Switch `embedder_model` (dim mismatch) → set `reuse_embedding_cache: false`
> - Ablation requires Q-table-free start → set `reuse_q_table: false`
> - Reproduce a paper figure from scratch → set both
>
> **State co-location is opt-in.** `resolved_state_path()` keeps the
> legacy `<library_root>/.state/` default. To co-locate method state
> with `seed_skills_dir` (so version control covers both curated
> skills and learned Q-table), set:
>
> ```yaml
> state_path: <seed_skills_dir>/.skillq_state/method_state.json
> ```
>
> `.gitignore` adds `skills/.skillq_state/` so the state files don't
> pollute commit history. New YAML example:
> `experiments/configs/method_tb2_skillq_fresh_start.yaml`.
>
> Implementation:
> - `MethodConfig.resolved_emb_cache_path()` mirrors `resolved_state_path()`.
> - `QlibState.load_into(overwrite_q=...)` lets the bridge load
>   library + probation bookkeeping without touching the Q-table.
> - `VectorTable.clear()` empties the cache and marks `_dirty=True`.
>
> Tests: 11 new (5 unit + 6 integration), 214/214 total pass.

> **2026-06-25 — Rename `paper_mode/` → `skillq_runtime/`**: The
> sub-package that bridges the four-layer `skillq.method/` algorithm
> onto the Harbor harness was renamed for clarity. `paper_mode` was
> confused with the "SkillsVote baseline" (a separate sub-package at
> `skillq/skillsvote_mode/`) and with the upstream `lqrl` paper code;
> `skillq_runtime/` makes the "this is SkillQ's own runtime layer"
> intent explicit and parallels `skillsvote_mode/` cleanly.
>
> - Directory: `skillq/paper_mode/` → `skillq/skillq_runtime/`
> - All `import_path: skillq.paper_mode.agent:SkillQClaudeCodeAgent`
>   strings in `experiments/configs/*.yaml` and
>   `experiments/smoke/*.yaml` updated.
> - All Python imports in `skillq/`, `tests/`, `experiments/run/`,
>   `experiments/smoke/debug_smoke.py` updated.
> - README, RUNNING.md updated. Historical CHANGELOG entries
>   preserved (they document the name at the time).
> - CLI subcommand `skillq paper …` is **unchanged** — only the
>   module path moved. Future PR may rename the subcommand itself
>   (`paper` → `run`) for consistency; tracked separately.
> - 203/203 unit + integration tests pass after the rename.

> **2026-06-16 — Decouple from upstream `lqrl`**: The repository was
> previously a sibling of `/home/gonern/workspace/lqrl` and depended
> on it as an editable Python dependency (`skills_vote`) plus a
> sibling-repo source for `prebuild_images.py` and benchmark input
> data. After this change:
>
> - `lqrl/src/skills_vote/` is **vendored in-tree** at
>   `./skillsvote/` (572KB; 30 Python files). `pyproject.toml`
>   points `skills_vote` at `./skillsvote` instead of `../lqrl`.
> - `prebuild_images.py` is vendored at `./skillsvote/prebuild_images.py`.
>   The `skillq prebuild` wrapper CLI no longer reaches into a sibling
>   repo (`--lqrl-root` flag renamed to `--skillsvote-root`,
>   default `./skillsvote`).
> - The benchmark input data path is now configurable via
>   `MethodConfig.benchmark_input_path` (or `$SkillQ_INPUT` env var,
>   or `./input` fallback) instead of the hard-coded
>   `/home/gonern/workspace/lqrl/input/terminal-bench`.
> - `PaperClaudeCodeAgent` (which inherited from the upstream
>   `SkillsVoteClaudeCode`) is replaced by `SkillQClaudeCodeAgent`,
>   a direct subclass of `harbor.agents.installed.claude_code.ClaudeCode`
>   with no upstream base class. The legacy `PaperClaudeCodeAgent`
>   name is kept as an alias for backwards compatibility.
> - The `--mode lqrl` argparse choice in experiment runners was
>   renamed to `--mode skillsvote` to match the CLI subcommand
>   (`skillq skillsvote`).
>
> Result: `uv sync` resolves everything from `./skillsvote/` and
> the project no longer depends on any sibling-repo source path.

> **2026-06-16 — Project rename**: The repo was renamed from
> `mg` → `skillq` and the project rename cascaded through:
> - Python package: `paper/` → `skillq/` (`paper_mode` and
>   `skillsvote_mode` sub-packages kept their names as logical
>   sub-modes; class names like `PaperClaudeCodeAgent` and
>   `MethodConfig` are unchanged).
> - CLI entry point: `paper` → `skillq`
>   (`uv run paper paper run …` is now `uv run skillq paper run …`).
> - Env-var prefix: `MG_*` → `SKILLQ_*`.
> - Path prefixes: `.mg_library/`, `mg_state/`, `mg_skills/`,
>   `mg_skill_hook.py`, `mg_skill_calls.jsonl`,
>   `mg_extract_<hash>/`, `mg_lib.json`, `mg_q_table.json`,
>   `mg_emb_cache.json` → `skillq_*`.
> - The user's paper was also renamed (LQRL → SkillQ); references
>   to the upstream `lqrl` package (sibling at `../lqrl`,
>   `LQRL_ROOT` env var, `implementation_guide/lqrl/...` skeleton
>   citations) are **preserved** because they point at an
>   external dependency.

This first entry covers everything built during the initial
implementation: the two-mode dispatch, the paper four-layer
implementation, the create_skill path, the experiment scaffolding,
and the developer ergonomics (`.env`, `prebuild`, `RUNNING.md`).

---

## [Unreleased] — 2026-06-08

### Added

#### Top-level package

- `pyproject.toml` — PEP 621 metadata, `uv`-managed deps. Pulls
  `skills_vote` (the upstream `lqrl` distribution) from
  `../lqrl` via `[tool.uv.sources]` because the package is not
  on PyPI. Pulls `harbor==0.5.0`, `litellm`, `pydantic`,
  `omegaconf`, `claude-agent-sdk`, `python-dotenv`,
  `tomlkit`. Dev group has `pytest` + `pytest-asyncio`.
- `README.md` — high-level overview; describes the two
  mutually exclusive run modes and the shared `.env` workflow.
- `.env.example` — same shape as lqrl's `.env.example`
  (`OPENAI_*` / `ANTHROPIC_*` / `CODEX_*` keys) so users can
  `cp lqrl/.env paper/.env` and reuse the same secrets.
- `mg/__init__.py` — re-exports `lqrl_main` and `paper_main`.
- `mg/cli.py` — top-level `paper` console-script with three
  subcommands: `lqrl`, `paper`, `prebuild`. Each builds its own
  `argparse` tree lazily.
- `mg/env.py` — `load_env_file(...)` dotenv loader. Same
  semantics as lqrl's `skills_vote.harbor.cli.load_env_file`:
  `override=True`, silent when the default `.env` is missing.

#### `paper/method/` — paper four layers + extract

- `types.py` — `Skill` / `Qlib` / `Verdict` / `RetrievalResult`
  core data types. Skill carries the body, retrieval/usage
  counters, and metadata; Qlib is a bounded dict-backed library
  (Eq. 2 invariant `|M_t| ≤ B_max`).
- `hash.py` — `qhash(text) → int` (sha1[:16] → int). Used as
  the Q-table's intent key.
- `retrieval.py` — `TwoStageRanker` (Phase A cosine + Phase B
  Eq. 4 re-rank with z-scored similarity, z-scored Q, and
  UCB bonus). `StubEmbedder` for tests; `LiteLLMEmbedder` for
  production.
- `layered_q.py` — `BetaLayeredQ` (Eq. 6 update) with
  `increment_clip` safety guard. Plus three theoretical
  helpers (Theorems 1, 2, 3 of the paper).
- `library.py` — `LibManager` (Sec. 3.3 admission / eviction
  / rejuvenation). Hard `B_t ≤ B_max` constraint enforced in
  `maintain()`. Default hyperparameters intentionally differ
  from the paper defaults (`n_explore=8`, `theta_admit=0.25`,
  `theta_evict=0.15`, `n_stale=80`) to make mg's defaults not
  a verbatim copy.
- `near_miss.py` — `NearMissRefiner` (Sec. 3.4 / Layer 4).
  Triggers on `r_task == 0 ∧ Q ≥ θ_nm`, edits the skill in
  the 20% token cap.
- `verifier.py` — `IndependentVerifier` (Sec. 3.2). Uses
  `LiteLLMVerifierBackend` (independent session, temperature
  0). `StubVerifierBackend` for tests. 4-axis 0-1 scoring
  schema (`old_score`, `new_score`, `improved`, `rationale`).
- `editor_backend.py` — `LiteLLMEditBackend` (separate
  class for clarity; same call shape as verifier).
- `state.py` — `QlibState` JSON serialiser. Path
  `<library_root>/.state/method_state.json`. Skips collision
  with lqrl's `skills_vote_evolve_state.json`.
- `prompts.py` — four prompts in own wording (deliberately
  different from lqrl's 55 KB of inline prompts):
  - `VERIFIER_PROMPT` — 4-axis 0-1 scoring with `r_learning`
    clamping; explicit information-isolation preamble.
  - `EDIT_PROMPT` — 20% token cap, "skill name unchanged / no
    new tools / full text not diff" constraints.
  - `ATTRIBUTION_PROMPT` — 6-class verdict enum
    (`success_skill_used` / `success_viewed_skill_but_not_used`
    / `success_no_skill_seen` / `fail_*`) plus
    `knowledge_to_extract` blob.
  - `EXTRACT_SKILL_PROMPT` — materializes a new `SKILL.md`
    under a sandbox via `claude --print`.
  - `RETRIEVAL_PROMPT` — Eq. 4 audit-only explanation.
  - `EXPLAIN_R_LEARNING_PROMPT` — verifier rationale helper.
- `attribution.py` — `AttributionAnalyzer` runs the
  attribution LLM call. Mirrors lqrl's `step_feedback`
  shape: reads session jsonl + available-skills list,
  produces a 6-class verdict.
- `extractor.py` — `SkillExtractor` spawns a
  `claude --print --permission-mode=bypassPermissions`
  subprocess that physically writes a `SKILL.md` under
  `<sandbox>/create/<name>/`. Mirrors lqrl's
  `evolve/claude_code.py` shape.

#### `mg/lqrl_mode/` — pass-through to upstream lqrl

- `cli.py` / `entrypoint.py` / `config.py` — pure
  pass-through. `paper lqrl run -c X` forwards to
  `skills_vote.harbor.cli.main(argv)`. ~100 lines total,
  zero implementation logic.

#### `paper/paper_mode/` — paper-mode orchestration

- `config.py` — `MethodConfig` Pydantic model with ~20 fields
  covering all paper hyperparameters + LLM model names +
  persistence paths + `enable_auto_extract` /
  `extract_max_new_per_trial` / `extractor_claude_cli`.
- `bridge.py` — `attach_paper_registers(job, method)`
  wires a single `on_trial_ended` hook that runs the
  full pipeline:
    1. `AttributionAnalyzer.analyze(...)` (1 LLM call)
    2. TwoStageRanker `retrieve_for_intent(...)` (Eq. 4)
    3. IndependentVerifier (Sec. 3.2 information-isolated)
    4. β-layered Q-update on each retrieved skill
    5. (NEW) auto-extract trigger on success
    6. `LibManager.maintain(...)` (admission / eviction / stale)
    7. `QlibState.save(...)` (persistence)
    8. (failures only) `NearMissRefiner.propose_edit(...)`
  Wrapped in `try/except Exception: logger.exception(...)` so
  a method bug never aborts the trial.
- `agent.py` — `PaperClaudeCodeAgent(SkillsVoteClaudeCode)`.
  Calls `rerank_with_ucb(...)` to append a "[mg UCB re-rank
  breakdown]" block to the instruction, then delegates to
  `super().run()` (lqrl's recommend step + claude exec).
- `retrieval_step.py` — `rerank_with_ucb(...)` agent-side
  helper. Reads `agent.skills_dir` (the directory lqrl's
  recommend step copied skills into) and re-ranks with
  `TwoStageRanker`.
- `cli.py` / `entrypoint.py` — `paper paper run -c X
  --method-config Y`. Loads `.env`, then dispatches to
  `bridge.run_paper_job_sync`.

#### `paper/prebuild_cli.py` — Docker image prebuilder

- `paper prebuild run --benchmark {tb2|tb_pro|swebenchpro}
  --agent {claude_code|codex}` is a thin wrapper around
  lqrl's `scripts/prebuild_images.py`. The `paper` command
  looks up the right `scripts/configs/prebuild_images*.yaml`
  based on the (benchmark, agent) pair and runs the
  underlying lqrl prebuild via `subprocess.run`. Optional
  `--cfg-path`, `--image-tag`, `--max-workers`, `--lqrl-root`,
  `--download-only`.

#### `integration/skills/skillq-method/`

- `SKILL.md` — Claude-Code-style skill description for the
  paper-mode lifecycle. Reads only this file first, runs
  `route_prompt.py`.
- `scripts/route_prompt.py` — standalone agent-callable
  script that runs `TwoStageRanker` on the mounted
  skills root. Default embedder is `StubEmbedder` (no API
  key needed); `--embedder live` switches to
  `LiteLLMEmbedder`.

#### `experiments/`

- `run_benchmark.py` — single driver for TB 2.0 / TB Pro /
  SWE-Bench Pro. Takes `--mode {lqrl|paper}` and writes
  a job-config YAML to `experiments/configs/<bench>_<mode>.yaml`,
  then dispatches to `paper <mode> run -c <yaml>`. Supports
  `--dry-run`, `--n-concurrent`, `--n-attempts`,
  `--task-subset`, `--agent-model`, `--agent-import-path`.
- `ablation.py` — 6-cell ablation (with/without UCB,
  verifier, near-miss).
- `beta_sweep.py` — 7-cell β sweep (0.0–1.0).
- `kappa_sweep.py` — inter-rater κ audit with 3 verifier
  backends.
- `run_terminalbench.py` — older stub kept for reference.
- `configs/tb2_skillq.yaml` / `tb_pro_skillq.yaml` /
  `swebenchpro_skillq.yaml` — three ready-to-run paper-mode
  templates.
- `configs/tb_pro_lqrl.yaml` — auto-generated lqrl-mode
  template.
- `RUNNING.md` — 8-section operator guide: prerequisites,
  prebuild, three invocation modes, three benchmark
  recipes, output structure, multi-seed / sweep / ablation
  commands, troubleshooting, and the new §8 on
  `enable_auto_extract`.

#### `tests/` — 45 unit tests, all passing

- `test_skillq_method_layers.py` — 14 skillq-method unit
  tests (the same 14 from `implementation_guide/lqrl/tests/
  test_core.py`, ported with renamed classes).
- `test_paper_hooks.py` — QlibState round-trip, bridge
  hook mock with stub LLM backends, retry-failure skip.
- `test_lqrl_mode_attach.py` — passthrough dispatch
  verification.
- `test_env_loading.py` — 4 dotenv loader tests.
- `test_attribution.py` — stub backend, prose-wrapped JSON
  fallback, session jsonl loader.
- `test_extractor.py` — happy path, body under/over cap,
  name length check, subprocess fail / timeout / missing
  CLI.
- `test_bridge_extract.py` — 5 integration tests for the
  extract trigger conditions and Q-bump side effect.

### Notes

- All LLM calls go through `litellm`. No `claude-agent-sdk`
  or `codex` subprocess in the paper-mode code path except
  the optional `extractor_claude_cli` (which is opt-in
  via `MethodConfig.enable_auto_extract`).
- The paper method's create_skill path follows the
  design from the conversation about Q1/Q2/Q3 but those
  *final* Q-value-on-Skill / mixed-factor-eviction
  refactors are **deferred to a follow-up commit**. The
  current code still uses the LibManager-owned Q-table
  with single-skill-level Q via `qhash`. The interface
  for the refactor is documented in `RUNNING.md` §8.
- 45 / 45 tests pass under `uv run pytest tests/`.
