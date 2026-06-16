# skillq — Branch-style entrypoint: SkillsVote baseline AND the SkillQ paper method

`skillq` exposes **two mutually exclusive run modes** on top of
[Harbor](https://github.com/laude-institute/harbor):

- **`skillq skillsvote`** — wraps the upstream `skills_vote` package's
  `SkillsVoteClaudeCode` agent and its `attach_registers` / `register`
  lifecycle (recommend → feedback → evolve). This is the **comparison
  baseline** for the SkillQ paper. No implementation code lives in
  `skillq/skillsvote_mode/`; it's a thin pass-through layer.

- **`skillq paper`** — runs the **SkillQ paper's** four-layer method
  ([Tang, 2026, PRICAI](https://example.invalid/skillq-paper)) as an
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

> **Naming note**: `lqrl` was the user's earlier paper name; the
> paper has since been renamed to **SkillQ**. `skills_vote` is the
> *baseline* the paper compares against (a different method with a
> similar lifecycle but a simpler architecture). `skillq` is just a
> project code name; both run modes implement the user's intended
> workflow.

## Install

```bash
cd /home/gonern/workspace/skillq
uv sync
```

`uv sync` resolves `skills_vote` from `../lqrl` via the
`[tool.uv.sources]` block in `pyproject.toml`. The dependency on
the upstream `skills_vote` (the actual distribution name of the
*baseline*) is pulled in editable mode so the `skillq skillsvote`
pass-through can `import` the package's `attach_registers` /
`run_job` directly.

To run the test suite:

```bash
uv run pytest tests/
```

## Run

```bash
# skillsvote mode — runs the *baseline* lifecycle verbatim
uv run skillq skillsvote run -c configs/job_skillsvote.yaml

# paper mode — runs the *SkillQ paper's* four-layer method
uv run skillq paper run -c configs/job_paper.yaml

# Inspect the baseline-side help text (it's the same as `svt run --help`)
uv run skillq skillsvote run --help
```

## Layout

```
(skillq)/
├── skillq/
│   ├── skillsvote_mode/  # pass-through to upstream skills_vote (baseline)
│   ├── paper_mode/       # bridge + agent + entrypoint for the SkillQ method
│   ├── method/           # the four paper layers (TwoStageRanker, BetaLayeredQ,
│   │                     #   LibManager, NearMissRefiner, IndependentVerifier)
│   └── prompts/          # external prompt templates (optional)
├── integration/skills/skillq-method/  # SKILL.md for the agent
├── tests/                # unit + integration tests
└── experiments/          # Terminal-Bench 2.0 runs and ablations
```

## Why a branch-style entrypoint

`skillq skillsvote` and `skillq paper` should not be registered as
concurrent hooks on the same Harbor `Job`. They are alternative
policies for the same lifecycle:

- `skillsvote` (the baseline) evolves whole skills
  (`create_skill`, `error_fix`, `knowledge_addition`,
  `prerequisite_addition`, `skip`).
- The SkillQ paper method maintains a Q-table over
  `(intent, skill)` pairs and edits skills on near-miss failures
  (the edit size is unconstrained; quality is controlled by
  `r_learning`).

The two are not composable in a single Job without aliasing skill
identifiers, and they have different state files. So they share
the same `skillq` CLI and the same agent subclassing pattern, but
they **do not share the same `on_trial_ended` callback**.
