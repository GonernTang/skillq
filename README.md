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
  1. Two-stage retrieval with Hard Gate + BM25 hybrid scoring
     (multiplicative mode: ``sim·(1+β·Q)+γ·UCB``, default;
     additive mode: ``(1-λ)·sim_z+λ·q_z+UCB``, legacy Eq. 4)
  2. Standard tabular Q-learning (Eq. 5, ``Q += α·(r−Q)``)
     with optional cosine-weighted delta
  3. Q-driven library management (admission / eviction,
     hard-bounded at ``b_max`` with lowest-Q eviction)
  4. Incremental editing on failure (LLM-generative via
     `EditRefiner` + `LiteLLMEditBackend`; near-miss gate
     removed 2026-06-22 — now unconditional on failure).
     L4 skill creation uses the `skill-creator` meta-skill
     to produce standard-layout skill directories (``SKILL.md``
     + optional ``scripts/``, ``references/``, ``assets/``).

  The paper method originated from the ``implementation_guide/lqrl/``
  Python skeleton (the user's earlier paper name, now renamed to
  **SkillQ**) but has since been rewritten with renamed classes,
  custom prompts, different hyperparameters, and a LiteLLM-only
  backend. ``lqrl`` is kept only as a naming note.

> **Naming note**: `lqrl` was the user's earlier paper name; the
> paper has since been renamed to **SkillQ**. `skills_vote` is the
> *baseline* the paper compares against (a different method with a
> similar lifecycle but a simpler architecture). `skillq` is just a
> project code name; both run modes implement the user's intended
> workflow.

## Environment Setup

### Prerequisites

- Python 3.12+ with [uv](https://docs.astral.sh/uv/)
- Docker (for task trial containers)
- Claude Code API key (set in `.env` as `ANTHROPIC_API_KEY`)
- Embedding API key (set in `.env` as `OPENAI_API_KEY` for `text-embedding-v4`)

### .env file

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=deepseek-v4-flash       # or anthropic/claude-sonnet-4-5
OPENAI_API_KEY=sk-...                   # for text-embedding-v4
EMBEDDING_MODEL=text-embedding-v4
```

### Docker Images (Terminal-Bench 2.0)

The 89 TB2 task images need to be prebuilt before running experiments. Two options:

**Option A: Prebuild from upstream (recommended for new machines)**

Builds images from the original `alexgshaw/<task>:20251031` upstream images, adding the Claude Code agent layer. Requires Docker Hub access (~45 min for all 89 tasks, 4 concurrent).

```bash
uv run python skillq/prebuild_images.py \
  --cfg-path experiments/configs/prebuild_tb2_claude.yaml
```

The script automatically skips already-built images (via `docker image inspect` cache). If the local source image is missing, it falls back to the upstream `alexgshaw/<task>:20251031` image from Docker Hub.

**Option B: Import from existing machine**

```bash
# On the build machine
docker save $(docker images 'skills_vote/*' --format '{{.Repository}}:{{.Tag}}') \
  | gzip > skillq_tb2_images.tar.gz

# Copy to target machine, then
docker load < skillq_tb2_images.tar.gz
```

### Corporate Network / TLS Proxy

If your network uses a TLS inspection proxy (common in corporate environments), Docker may reject Docker Hub's certificate. Add your company's root CA:

```bash
sudo cp company-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
sudo systemctl restart docker
# Verify
docker pull alpine:latest
```

### WSL2 / Docker Resource Limits

When running 8 concurrent trials on WSL2, socket buffer exhaustion may occur. Increase limits:

```bash
# In WSL2 (as root)
sysctl -w net.core.rmem_max=16777216
sysctl -w net.core.wmem_max=16777216

# On Windows host (as Administrator)
netsh int ip set dynamicportrange protocol=tcp startport=1025 numberofports=64500
```

## Quick Start

```bash
# 1. Clone and install
git clone git@github.com:GonernTang/skillq.git
cd skillq
uv sync

# 2. Set up .env with API keys

# 3. Prebuild task images (one-time, ~45 min)
uv run python skillq/prebuild_images.py \
  --cfg-path experiments/configs/prebuild_tb2_claude.yaml

# 4. Run a quick smoke test (single task)
uv run skillq paper run --benchmark tb2 --variant full \
  --method-override datasets.task_names=[chess-best-move] \
  --method-override n_concurrent_trials=1

# 5. Run full experiment (89 tasks, 8 concurrent)
uv run skillq paper run --benchmark tb2 --variant fromscratch_r2
```

## Install

```bash
cd /home/gonern/workspace/skillq
uv sync
```

`uv sync` resolves `skills_vote` from the vendored `./skillsvote/`
directory via the `[tool.uv.sources]` block in `pyproject.toml`. The
baseline package is pulled in editable mode so the `skillq skillsvote`
pass-through can `import` the package directly.

To run the test suite (334 tests):

```bash
uv run pytest tests/
```

## Run

```bash
# skillsvote mode — runs the *baseline* lifecycle verbatim
uv run skillq skillsvote run -c experiments/configs/tb_pro_skillsvote.yaml

# paper mode — runs the *SkillQ paper's* four-layer method
uv run skillq paper run --benchmark tb2 --variant fromscratch

# Available variants: fromscratch, zerostart, full, hard6,
#   fromscratch_r2/r3/r4, zerostart_r2/r4, fromscratch_resume
uv run skillq paper run --benchmark tb2 --variant zerostart_r4

# Or pass a raw Harbor job config directly
uv run skillq paper run -c experiments/configs/tb2_skillq_full.yaml
```

## Layout

```
(skillq)/
├── skillq/
│   ├── layers/            # 4-layer paper method (l1_retrieval, l2_run, l3_attribution, l4_evolve)
│   ├── runtime/           # orchestrator + 8-step pipeline (bridge, steps, hook, container_wiring, ...)
│   ├── services/          # host-side /rank HTTP service (ranking_service, ranking_client)
│   ├── shared/            # Q-table, library, embeddings, calls_log, backends (litellm)
│   ├── skillsvote_mode/   # pass-through to upstream skills_vote (baseline)
│   ├── paper_mode/        # ⚠️ legacy empty dir (rename → runtime/ on 2026-06-25, pending cleanup)
│   └── config.py          # MethodConfig (the method's configuration class)
├── skills/                # skill source files (SKILL.md + optional scripts/, references/)
├── skillsvote/            # vendored upstream skills_vote (the baseline)
├── tests/                 # unit + integration tests (334 tests)
├── experiments/           # Terminal-Bench 2.0 configs and run scripts
└── doc/                   # experiment reports, figures, paper notes
    ├── figures/           # paper-quality PDF/PNG figures
    └── experiment_final_summary.md  # 5-round experiment results
```

## Experiment Results

Full 5-round experiment results and paper-ready figures are in `doc/experiment_final_summary.md`
and `doc/figures/`. Quick summary:

| Series | Rounds | Best Pass Rate | Q Convergence | Skills |
|---|---|---|---|---|
| From-Scratch (A) | R1-R4 | 55.7% (R4, BM25) | 6% → 80% non-default | 67 → 102 |
| Zero-Start (B) | R1-R5 | 57.6% (R4, 2h timeout) | 10% → 69% non-default | 62 → 112 |

Key findings: Q-values predict task success (Q ≥ 0.55 → 90%+ pass rate); task difficulty
dominates (86% cross-round stability); BM25 hybrid retrieval improves pass rate by +5.1pp.

## Why a branch-style entrypoint

`skillq skillsvote` and `skillq paper` should not be registered as
concurrent hooks on the same Harbor `Job`. They are alternative
policies for the same lifecycle:

- `skillsvote` (the baseline) evolves whole skills
  (`create_skill`, `error_fix`, `knowledge_addition`,
  `prerequisite_addition`, `skip`).
- The SkillQ paper method maintains a Q-table over
  `(intent, skill)` pairs and edits skills on failed trials via
  `EditRefiner` (the edit size is unconstrained; quality comes from
  the underlying LLM judgement).

The two are not composable in a single Job without aliasing skill
identifiers, and they have different state files. So they share
the same `skillq` CLI and the same agent subclassing pattern, but
they **do not share the same `on_trial_ended` callback**.
