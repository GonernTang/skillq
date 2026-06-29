# Running skillq experiments

Quick-start for the single-driver workflow (post-4-layer refactor, 2026-06-29).

## TL;DR

```bash
# 1. smoke (1 task, ~10 min, fastest sanity check)
uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant smoke

# 2. e2e (3 task spanning L1/L2/L3/L4, ~30 min)
uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant e2e

# 3. full 89-task TB 2.0 run (~1-1.5h wall)
uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant full

# 4. SWE-Bench Pro 1-task smoke
uv run python experiments/run/run_benchmark.py --benchmark swebenchpro --variant smoke

# 5. Baseline (no paper method, skillsvote mode)
uv run skillq skillsvote run -c experiments/configs/tb_pro_skillsvote.yaml
```

## Layout

```
experiments/
├── configs/
│   ├── tb2_skillq_smoke.yaml     # 1 task (chess-best-move)
│   ├── tb2_skillq_e2e.yaml       # 3 task (chess+circuit+extract)
│   ├── tb2_skillq_full.yaml      # 89 task (full TB 2.0)
│   ├── swebenchpro_skillq.yaml   # SWE-Bench Pro 20-instance subset
│   └── tb_pro_skillsvote.yaml    # baseline (skillsvote mode, no paper method)
└── run/
    ├── run_benchmark.py          # single-driver (--benchmark/--variant/...)
    └── run_tb2_paper.sh          # thin wrapper: forwards to run_benchmark.py --benchmark tb2 --variant smoke
```

## Single-driver flags

```bash
uv run python experiments/run/run_benchmark.py \
    --benchmark {tb2,swebenchpro} \
    --variant {smoke,e2e,full} \
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
    c_ucb: 0.5
  attribution_model: anthropic/${oc.env:ANTHROPIC_MODEL,...}
  editor_model:      anthropic/${oc.env:ANTHROPIC_MODEL,...}
  embedder_model:    openai/${oc.env:EMBEDDING_MODEL,...}
  evolve:                                   # L4
    enabled: true
    extract_every_n_trials: 5
    semantic_dedup_threshold: 0.85
  b_max: 1000
  seed_initial_q: 0.5
  reuse_q_table: true
  reuse_embedding_cache: true
  runtime: new                              # 'new' = 4-layer pipeline (only option post-Step-7)
```

`tb_pro_skillsvote.yaml` is the baseline and has **no** `method:` subtree — it runs pure skillsvote mode without the paper method.

## Variant matrix

| variant | tasks | n_concurrent | timeout | expected duration |
|---|---|---:|---:|---|
| smoke | 1 (chess-best-move) | 1 | 1800 s | ~10 min |
| e2e | 3 (chess + circuit + extract) | 1 | 1800 s | ~30 min |
| full | 89 (all TB 2.0) | 8 | 3600 s | ~1-1.5 h |

## E2E acceptance (from plan §9.6)

- **smoke**: `output/<job_name>/<trial>/result.json` exists, reward ∈ {0.0, 1.0}, `method_state.json` written, `skillq_skill_calls.jsonl` non-empty.
- **e2e**: 3 trials all produce `result.json`; circuit-fibsqrt triggers L3 EditRefiner (edited body in `seed_skills_dir`); extract-elf triggers L4 SkillExtractor (new skill in lib + mirrored).
- **full**: pass@1 within ±5 % of v3 baseline (`doc/old/SKILLQ_RUN_RESULTS_2026-06-25.md` records the 2026-06-25 baseline at pass@1 = 0.584).

## Prerequisites

- `.env` configured: `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL=claude-sonnet-4-5`, `EMBEDDING_*`
- Prebuilt image `skills_vote/<task>:20260604` available
- `input/terminal-bench/<task>/task.toml` vendored
- `skills/_seed_stub/SKILL.md` exists

## Out of scope

- **Single-trial mode**: not exposed via `run_benchmark.py`. For ad-hoc debug, run `skillq paper run -c <generated_yaml>` directly.
- **Ablation sweeps** (`ablation.py`, `beta_sweep.py`): pre-4-layer scripts, deleted in Step 8.4. To re-introduce an ablation, write a new YAML under `experiments/configs/` and call `run_benchmark.py --method-override ...`.
- **Pre-4-layer configs** (`method_tb2_skillq_*.yaml`, `tb2_skillq_*_v3.yaml`): deleted in Step 8.2. The single merged YAML per experiment replaces them.
- **Legacy `runtime: legacy`**: raises `RuntimeError` (intentional deprecation stub). Roll back to v0.x tag if you need pre-Step-7 behaviour.

## Historical reference

Pre-4-layer baselines, run results, and bug audits are archived under `doc/old/`:

- `doc/old/SKILLQ_RUN_RESULTS_2026-06-25.md` — pass@1 = 0.584 baseline (pre-refactor).
- `doc/old/SKILLQ_CONTEXT_SNAPSHOT.pre-refactor.md` — pre-4-layer architecture snapshot.
- `doc/old/bug_to_fix.pre-refactor.md` — pre-4-layer bug ledger.
- `doc/old/analysis/step_9b_circuit_fibsqrt_root_cause.md` — Step 9B timeout RCA.

See `CHANGELOG.md` for the post-4-layer architectural record.