# Running skillq experiments

Quick-start for the single-driver workflow (post-4-layer refactor, 2026-06-29).

## TL;DR

```bash
# 1. Quick single-task test (chess-best-move, ~10 min)
uv run skillq paper run --benchmark tb2 --variant full \
  --method-override datasets.task_names=[chess-best-move] \
  --method-override n_concurrent_trials=1

# 2. Full 89-task TB 2.0 run (~1-1.5h wall)
uv run skillq paper run --benchmark tb2 --variant fromscratch_r2

# 3. From-scratch run (empty seed skills, 89 tasks)
uv run skillq paper run --benchmark tb2 --variant fromscratch

# 4. Full SWE-Bench Pro
uv run skillq paper run --benchmark swebenchpro --variant full

# 5. Baseline (no paper method, skillsvote mode)
uv run skillq skillsvote run -c experiments/configs/tb_pro_skillsvote.yaml
```

## Layout

```
experiments/
├── configs/
│   ├── tb2_skillq_fromscratch.yaml        # 89-task from-scratch (R1)
│   ├── tb2_skillq_fromscratch_r2.yaml     # 89-task seeded Q-learning (R2)
│   ├── tb2_skillq_fromscratch_r3.yaml     # 89-task per-trial extract (R3)
│   ├── tb2_skillq_fromscratch_r4.yaml     # 85-task BM25 hybrid (R4)
│   ├── tb2_skillq_zerostart.yaml          # 89-task zerostart baseline
│   ├── tb2_skillq_zerostart_r2.yaml       # 89-task zerostart R2
│   ├── tb2_skillq_zerostart_r4.yaml       # 85-task zerostart R4
│   ├── tb2_skillq_fromscratch_resume.yaml # resume from interrupted fromscratch
│   ├── tb2_skillq_full.yaml               # full TB 2.0 with method subtree
│   ├── tb2_hard6.yaml                     # 6 hard tasks benchmark
│   ├── swebenchpro_skillq.yaml            # SWE-Bench Pro
│   ├── tb_pro_skillsvote.yaml             # baseline (skillsvote mode, no paper method)
│   └── prebuild_tb2_claude.yaml           # Docker image prebuild config
└── run/
    └── run_benchmark.py                   # single-driver (--benchmark/--variant/...)
```

## Single-driver flags

```bash
uv run python experiments/run/run_benchmark.py \
    --benchmark {tb2,swebenchpro} \
    --variant {fromscratch,zerostart,full,hard6,fromscratch_r2,fromscratch_r3,fromscratch_r4,zerostart_r2,zerostart_r4,fromscratch_resume} \
    [--fresh-start]                       # clear Q-table + emb_cache before run
    [--runtime {new,legacy}]              # new (default) = 4-layer pipeline, legacy = (gone, raises)
    [--method-override retrieval.score_mode=additive]   # dotlist override any method subtree field
    [--dry-run]                            # write merged yaml, skip skillq.cli invocation
    [--jobs-dir output]                    # where to write job output (default: output)
```

- `--fresh-start`: equivalent to setting `method.reuse_q_table: false` and `method.reuse_embedding_cache: false`. Use for clean baseline runs.
- `--method-override key=value`: applied via OmegaConf dotlist. Repeatable. Example: `--method-override evolve.enabled=false`.
- `--runtime legacy`: raises `RuntimeError` post-Step-7 (the legacy closure was deleted); kept as a fail-loud stub so old YAMLs that set `method.runtime: legacy` produce a clear migration message.
- `--dry-run`: writes the merged YAML to `<jobs-dir>/<job_name>.yaml` and exits; useful for inspecting the resolved config before launching.

## YAML shape (merged single-source-of-truth)

Each `tb2_skillq_*.yaml` and `swebenchpro_skillq.yaml` has:

```yaml
jobs_dir: output
job_name: ${oc.env:...}                     # resolved at parse time
n_attempts: 1
n_concurrent_trials: 1                      # sequential for clean attribution
agents:
  - import_path: skillq.runtime.agent:SkillQClaudeCodeAgent
    model_name: ${oc.env:ANTHROPIC_MODEL,anthropic/claude-sonnet-4-5}
    kwargs: {reasoning_effort: high}
datasets:
  - path: ${oc.env:Skillq_INPUT_ROOT,...}/terminal-bench
    task_names: [chess-best-move, circuit-fibsqrt, extract-elf]
method:
  seed_skills_dir: /home/gonern/workspace/skillq/skills
  library_root: ${jobs_dir}/${job_name}/.skillq_library
  retrieval:                                # L1
    top_k: 3
    sim_gate_min_score: 0.7
    score_mode: multiplicative
    beta: 0.5
    gamma: 0.2
    lambda: 0.5
    c_ucb: 0.0
  attribution_model: anthropic/${oc.env:ANTHROPIC_MODEL,...}
  editor_model:      anthropic/${oc.env:ANTHROPIC_MODEL,...}
  embedder_model:    openai/${oc.env:EMBEDDING_MODEL,...}
  evolve:                                   # L4
    enabled: true
    extract_every_n_trials: 5
  b_max: 1000
  seed_initial_q: 0.5
  reuse_q_table: true
  reuse_embedding_cache: true
  runtime: new                              # 'new' = 4-layer pipeline (only option post-Step-7)
```

`tb_pro_skillsvote.yaml` is the baseline and has **no** `method:` subtree — it runs pure skillsvote mode without the paper method.

## Variant matrix

Valid ``(benchmark, variant)`` pairs (see ``skillq/runtime/benchmark_config.py:BENCHMARK_VARIANTS``):

| benchmark | variant | config file | description |
|---|---:|---|---|
| tb2 | fromscratch | tb2_skillq_fromscratch.yaml | 89 tasks, empty seed, reuse_q_table=false |
| tb2 | fromscratch_r2 | tb2_skillq_fromscratch_r2.yaml | 89 tasks, seeded Q-table from R1 |
| tb2 | fromscratch_r3 | tb2_skillq_fromscratch_r3.yaml | 89 tasks, per-trial extract |
| tb2 | fromscratch_r4 | tb2_skillq_fromscratch_r4.yaml | 85 tasks, BM25 hybrid |
| tb2 | zerostart | tb2_skillq_zerostart.yaml | 89 tasks, fresh Q-table per run |
| tb2 | zerostart_r2 | tb2_skillq_zerostart_r2.yaml | 89 tasks, zerostart R2 |
| tb2 | zerostart_r4 | tb2_skillq_zerostart_r4.yaml | 85 tasks, zerostart R4 |
| tb2 | full | tb2_skillq_full.yaml | full TB 2.0 with method subtree |
| tb2 | hard6 | tb2_hard6.yaml | 6 hard tasks benchmark |
| swebenchpro | full | swebenchpro_skillq.yaml | SWE-Bench Pro |

## E2E acceptance

- **fromscratch**: 89 trials all produce `result.json`; L4 creates skills from successful trajectories; ``method_state.json`` written with Q-table entries.
- **full**: pass@1 within ±5 % of previous baseline.
- See ``doc/experiment_r1_r2_report.md`` and ``doc/experiment_summary_for_paper.md`` for detailed results.

## Prerequisites

- `.env` configured: `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL=deepseek-v4-flash`, `EMBEDDING_*`, `OPENAI_API_KEY`
- Prebuilt image `skills_vote/<task>:20260604` available
- `input/terminal-bench/<task>/task.toml` vendored
- ``skills_seed_backup/_seed_stub/SKILL.md`` exists (seed skill stub)

## Out of scope

- **Single-trial mode**: not exposed via `run_benchmark.py`. For ad-hoc debug, run `skillq paper run -c <generated_yaml>` directly.
- **Ablation sweeps**: to run an ablation, write a new YAML under `experiments/configs/` and call `run_benchmark.py --method-override ...`.
- **Legacy `runtime: legacy`**: raises `RuntimeError` (intentional deprecation stub). Roll back to v0.x tag if you need pre-Step-7 behaviour.

## Historical reference

Pre-4-layer baselines, run results, and bug audits are archived under `doc/old/`:

- `doc/old/SKILLQ_RUN_RESULTS_2026-06-25.md` — pass@1 = 0.584 baseline (pre-refactor).
- `doc/old/SKILLQ_CONTEXT_SNAPSHOT.pre-refactor.md` — pre-4-layer architecture snapshot.
- `doc/old/bug_to_fix.pre-refactor.md` — pre-4-layer bug ledger.
- `doc/old/analysis/step_9b_circuit_fibsqrt_root_cause.md` — Step 9B timeout RCA.

See `CHANGELOG.md` for the post-4-layer architectural record.