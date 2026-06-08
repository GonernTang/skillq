# mg — Branch-style entrypoint for lqrl and the LQRL paper method

`mg` exposes **two mutually exclusive run modes** on top of [Harbor](https://github.com/laude-institute/harbor):

- **`mg lqrl`** — wraps the upstream `lqrl` package's `SkillsVoteClaudeCode` agent and
  its `attach_registers` / `register` lifecycle (recommend → feedback → evolve). No
  implementation code lives in `mg/lqrl_mode/`; it's a thin pass-through layer.

- **`mg paper`** — runs the LQRL paper's four-layer method
  ([Tang, 2026, PRICAI](https://example.invalid/lqrl-paper)) as an independent
  `on_trial_ended` hook:
  1. Two-stage UCB retrieval (cosine → UCB-augmented re-rank, Eq. 4)
  2. β-layered Q-learning (Eq. 6 with informationally isolated verifier)
  3. Q-driven library management (admission / eviction / rejuvenation)
  4. Near-miss-aware incremental editing (20% token cap, 5.x sub-section)

  The paper method is implemented from the
  `implementation_guide/lqrl/` Python skeleton but with renamed classes, custom
  prompts, different default hyperparameters, and a LiteLLM-only backend.

## Install

```bash
cd /home/gonern/workspace/mg
uv sync
```

`uv sync` resolves `skills_vote` from `../lqrl` via the
`[tool.uv.sources]` block in `pyproject.toml`. The dependency on the
upstream `skills_vote` (the actual distribution name) is pulled in
editable mode so the `mg lqrl` pass-through can `import` the
package's `attach_registers` / `run_job` directly.

To run the test suite:

```bash
uv run pytest tests/
```

## Run

```bash
# lqrl mode — re-uses the upstream skills_vote lifecycle verbatim
uv run mg lqrl run -c configs/job_lqrl.yaml

# paper mode — runs the four-layer method against Harbor's trial events
uv run mg paper run -c configs/job_paper.yaml

# Inspect the lqrl-side help text (it's the same as `svt run --help`)
uv run mg lqrl run --help
```

## Layout

```
mg/
├── mg/
│   ├── lqrl_mode/        # pass-through to upstream lqrl
│   ├── paper_mode/       # bridge + agent + entrypoint for the paper method
│   ├── method/           # the four paper layers (TwoStageRanker, BetaLayeredQ,
│   │                     #   LibManager, NearMissRefiner, IndependentVerifier)
│   └── prompts/          # external prompt templates (optional)
├── integration/skills/paper-method/  # SKILL.md for the agent
├── tests/                # unit + integration tests
└── experiments/          # Terminal-Bench 2.0 runs and ablations
```

## Why a branch-style entrypoint

`mg lqrl` and `mg paper` should not be registered as concurrent hooks on the
same Harbor `Job`. They are alternative policies for the same lifecycle:

- lqrl evolves whole skills (`create_skill`, `error_fix`, `knowledge_addition`,
  `prerequisite_addition`, `skip`).
- The paper method maintains a Q-table over (intent, skill) pairs and edits
  skills at the 20% token cap on near-miss failures.

The two are not composable in a single Job without aliasing skill identifiers,
and they have different state files. So they share the same `mg` CLI and the
same agent subclassing pattern, but they **do not share the same
`on_trial_ended` callback**.
