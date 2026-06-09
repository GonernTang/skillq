# mg — Branch-style entrypoint: SkillsVote baseline AND the LQRL paper method

`mg` exposes **two mutually exclusive run modes** on top of
[Harbor](https://github.com/laude-institute/harbor):

- **`mg skillsvote`** — wraps the upstream `skills_vote` package's
  `SkillsVoteClaudeCode` agent and its `attach_registers` / `register`
  lifecycle (recommend → feedback → evolve). This is the **comparison
  baseline** for the LQRL paper. No implementation code lives in
  `mg/skillsvote_mode/`; it's a thin pass-through layer.

- **`mg paper`** — runs the **LQRL paper's** four-layer method
  ([Tang, 2026, PRICAI](https://example.invalid/lqrl-paper)) as an
  independent `on_trial_ended` hook. This is the **user's own
  contribution**:
  1. Two-stage UCB retrieval (cosine → UCB-augmented re-rank, Eq. 4)
  2. β-layered Q-learning (Eq. 6 with informationally isolated verifier)
  3. Q-driven library management (admission / eviction / rejuvenation)
  4. Near-miss-aware incremental editing (verifier-generative, no
     fixed token cap — quality controlled by `r_learning`)

  The paper method is implemented from the
  `implementation_guide/lqrl/` Python skeleton but with renamed
  classes, custom prompts, different default hyperparameters, and a
  LiteLLM-only backend.

> **Naming note**: `lqrl` is the user's paper name; `skills_vote` is
> the *baseline* the paper compares against (a different method
> with a similar lifecycle but a simpler architecture). `mg` is just
> a project code name; both run modes implement the user's
> intended workflow.

## Install

```bash
cd /home/gonern/workspace/mg
uv sync
```

`uv sync` resolves `skills_vote` from `../lqrl` via the
`[tool.uv.sources]` block in `pyproject.toml`. The dependency on
the upstream `skills_vote` (the actual distribution name of the
*baseline*) is pulled in editable mode so the `mg skillsvote`
pass-through can `import` the package's `attach_registers` /
`run_job` directly.

To run the test suite:

```bash
uv run pytest tests/
```

## Run

```bash
# skillsvote mode — runs the *baseline* lifecycle verbatim
uv run mg skillsvote run -c configs/job_skillsvote.yaml

# paper mode — runs the *LQRL paper's* four-layer method
uv run mg paper run -c configs/job_paper.yaml

# Inspect the baseline-side help text (it's the same as `svt run --help`)
uv run mg skillsvote run --help
```

## Layout

```
mg/
├── mg/
│   ├── skillsvote_mode/  # pass-through to upstream skills_vote (baseline)
│   ├── paper_mode/       # bridge + agent + entrypoint for the LQRL method
│   ├── method/           # the four paper layers (TwoStageRanker, BetaLayeredQ,
│   │                     #   LibManager, NearMissRefiner, IndependentVerifier)
│   └── prompts/          # external prompt templates (optional)
├── integration/skills/paper-method/  # SKILL.md for the agent
├── tests/                # unit + integration tests
└── experiments/          # Terminal-Bench 2.0 runs and ablations
```

## Why a branch-style entrypoint

`mg skillsvote` and `mg paper` should not be registered as
concurrent hooks on the same Harbor `Job`. They are alternative
policies for the same lifecycle:

- `skillsvote` (the baseline) evolves whole skills
  (`create_skill`, `error_fix`, `knowledge_addition`,
  `prerequisite_addition`, `skip`).
- The LQRL paper method maintains a Q-table over
  `(intent, skill)` pairs and edits skills on near-miss failures
  (the edit size is unconstrained; quality is controlled by
  `r_learning`).

The two are not composable in a single Job without aliasing skill
identifiers, and they have different state files. So they share
the same `mg` CLI and the same agent subclassing pattern, but
they **do not share the same `on_trial_ended` callback**.
