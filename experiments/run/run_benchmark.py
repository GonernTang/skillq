"""Single-driver for all skillq paper-mode experiments (Step 8, 2026-06-27).

Replaces the 11 split-configs + 5 scripts under ``experiments/``:

- Old layout (deleted in Step 8.2 / 8.4): 11 YAMLs (5 ``method_*.yaml`` +
  6 ``tb2_skillq_*.yaml`` variants) + 5 driver scripts
  (``run_benchmark.py`` / ``run_terminalbench.py`` / ``ablation.py`` /
  ``beta_sweep.py`` / ``run_tb2_paper.sh``).
- New layout: 4 merged YAMLs (job + method-subtree in one file) +
  this single driver. Fresh-start / legacy-runtime / per-field
  overrides are CLI flags instead of extra YAMLs.

Usage:

    # TB 2.0 full 89-task run (default variant)
    uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant full

    # TB 2.0 1-task smoke
    uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant smoke

    # TB 2.0 3-task e2e (all 4 layers)
    uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant e2e

    # SWE-Bench Pro 20-instance subset
    uv run python experiments/run/run_benchmark.py --benchmark swebenchpro --variant full

    # Override any method field via dotted-path key=value
    uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant smoke \\
        --method-override retrieval.score_mode=additive \\
        --method-override evolve.enabled=false

    # Fresh-start: clear Q-table + emb_cache on boot
    uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant full --fresh-start

    # Roll back to the legacy closure-based bridge (Step 7 raises
    # a friendly RuntimeError — only useful for diagnosing that error).
    uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant smoke --runtime legacy

    # Dry run: just write the merged YAML, don't invoke the runner
    uv run python experiments/run/run_benchmark.py --benchmark tb2 --variant smoke --dry-run

The merged YAML format is a Harbor JobConfig + a top-level
``method:`` subtree (per plan §6.3). This driver splits the merged
file into a job YAML and a method-config YAML and invokes
``skillq paper run -c <job> --method-config <method>``, which
preserves the existing CLI surface (per plan §8 contract: "CLI
surface: skillq {skillsvote,paper,prebuild} <sub> 完全不变").
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from omegaconf import OmegaConf
import yaml

# Make ``skillq.*`` importable when this file is run directly
# (``python experiments/run/run_benchmark.py ...``). The import
# also registers the ``${now:...}`` and ``${abspath:...}`` OmegaConf
# resolvers that the merged YAMLs use in their ``job_name`` and
# ``mounts_json.source`` fields (see skillq/_resolvers.py).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
import skillq._resolvers  # noqa: F401  (auto-registers OmegaConf resolvers)
from skillq.runtime.benchmark_config import (
    BENCHMARK_VARIANTS,
    parse_overrides,
    deep_merge,
    split_method_subtree,
    write_method_yaml,
    resolve_merged_yaml_path,
)


# Per (benchmark, variant) YAML file.


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_benchmark",
        description=(
            "Single-driver for skillq paper-mode experiments (Step 8, 2026-06-27). "
            "Replaces the 11 split-configs + 5 driver scripts under experiments/."
        ),
    )
    parser.add_argument(
        "--benchmark",
        choices=sorted({b for b, _ in BENCHMARK_VARIANTS}),
        required=True,
    )
    parser.add_argument(
        "--variant",
        choices=sorted({v for _, v in BENCHMARK_VARIANTS}),
        required=True,
    )
    parser.add_argument(
        "--fresh-start",
        action="store_true",
        help=(
            "Set reuse_q_table=false on the method config — Q-table "
            "starts at seed_initial_q for every skill (no inherited "
            "history). emb_cache is NOT touched: it's content-derived "
            "and invariant across runs. (Replaces the deleted "
            "method_tb2_skillq_fresh_start.yaml.)"
        ),
    )
    parser.add_argument(
        "--runtime",
        choices=["new", "legacy"],
        default="new",
        help=(
            'Pipeline selector (MethodConfig.runtime). "new" (default) '
            'dispatches to the closure-free 8-step pipeline; "legacy" '
            "raises a friendly RuntimeError (Step 7 deleted the legacy "
            "bridge — useful only for diagnosing the migration error)."
        ),
    )
    parser.add_argument(
        "--method-override",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help=(
            "Override any method-subtree field via dotted-path key=value. "
            "Repeatable. Example: --method-override retrieval.score_mode=additive. "
            "Numeric values are coerced (b_max=2000 → int 2000); "
            "booleans too (reuse_q_table=false → False)."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help=(
            "Where to write the split <job_name>.method.yaml. "
            "Default: same dir as the merged YAML (experiments/configs/)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Write the split method-config YAML and print the "
            "would-be ``skillq paper run`` command, but do not invoke it."
        ),
    )
    args = parser.parse_args(argv)

    merged_path = resolve_merged_yaml_path(args.benchmark, args.variant)
    if not merged_path.exists():
        raise SystemExit(
            f"[run_benchmark] merged YAML not found: {merged_path}\n"
            f"  (Step 8.1 should have created it; check git status / file path)"
        )

    # Source .env BEFORE resolving interpolations so ${oc.env:...}
    # references pick up the .env values (e.g. ANTHROPIC_MODEL=
    # deepseek-v4-flash) rather than stray shell values (e.g.
    # ANTHROPIC_MODEL=MiniMax-M3 leaking from the test harness).
    # The CLI does the same via load_env_file() inside paper run;
    # we have to do it explicitly because OmegaConf resolves
    # interpolations at split time, not at CLI invocation time.
    from skillq.env import load_env_file

    env_file = Path(os.environ.get("SkillQ_ENV_FILE", ".env")).resolve()
    try:
        load_env_file(env_file)
    except FileNotFoundError as exc:
        print(f"[run_benchmark] {exc}", file=sys.stderr, flush=True)
        return 2

    # Load via OmegaConf so all interpolations resolve (incl.
    # ${now:%Y-%m-%d__%H-%M-%S}, ${oc.env:...}, ${job_name} inside
    # the method subtree, etc.). Then snapshot the resolved dict
    # as a plain mapping for the rest of the driver.
    raw_text = merged_path.read_text(encoding="utf-8")
    conf = OmegaConf.create(raw_text)
    resolved = OmegaConf.to_container(conf, resolve=True)
    if not isinstance(resolved, dict):
        raise SystemExit(
            f"[run_benchmark] merged YAML must be a mapping; got {type(resolved).__name__}"
        )
    job_cfg, method_cfg = split_method_subtree(resolved)
    if method_cfg is None:
        raise SystemExit(
            f"[run_benchmark] {merged_path.name} has no top-level 'method:' subtree. "
            f"This driver only handles the merged paper-mode YAMLs (tb2_*/swebenchpro_). "
            f"Use ``skillq skillsvote run -c ...`` for the baseline."
        )

    overrides = parse_overrides(args.method_override)
    job_name = job_cfg.get("job_name", f"{args.benchmark}_skillq_{args.variant}")
    output_dir = (args.output_dir or merged_path.parent).resolve()
    method_yaml_path = output_dir / f"{job_name}.method.yaml"

    written_method = write_method_yaml(
        method_cfg,
        method_yaml_path,
        fresh_start=args.fresh_start,
        runtime=args.runtime,
        overrides=overrides,
    )

    # Persist the (resolved job_cfg without method-subtree) back to
    # disk so the user can inspect what the driver actually passed
    # to the CLI. All interpolations (incl. ${now:...}, ${oc.env:...},
    # ${job_name}) are already resolved — the on-disk job YAML is
    # literal, not a template, so subsequent edits to the merged
    # YAML don't leak into the on-disk job config.
    job_yaml_path = output_dir / f"{job_name}.job.yaml"
    job_yaml_path.write_text(
        yaml.safe_dump(job_cfg, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )

    cmd = [
        sys.executable, "-m", "skillq.cli", "paper", "run",
        "-c", str(job_yaml_path),
        "--method-config", str(method_yaml_path),
    ]
    cmd_str = " ".join(shlex.quote(c) for c in cmd)

    print(f"[run_benchmark] benchmark={args.benchmark} variant={args.variant}")
    print(f"[run_benchmark] job_name={job_name}")
    print(f"[run_benchmark] fresh_start={args.fresh_start} runtime={args.runtime}")
    if overrides:
        print(f"[run_benchmark] overrides: {overrides}")
    print(f"[run_benchmark] wrote {job_yaml_path}")
    print(f"[run_benchmark] wrote {method_yaml_path}")
    print(f"[run_benchmark] cmd: {cmd_str}")
    print(f"[run_benchmark]   (effective method.runtime = {written_method.get('runtime', 'new')!r})")
    print(f"[run_benchmark]   (effective method.reuse_q_table = {written_method.get('reuse_q_table', True)})")
    print(f"[run_benchmark]   (effective method.reuse_embedding_cache = {written_method.get('reuse_embedding_cache', True)})")

    if args.dry_run:
        return 0

    # cd into the repo root so ``skillq.cli`` and the YAML relative
    # paths resolve correctly.
    return subprocess.run(cmd, cwd=str(REPO_ROOT)).returncode


if __name__ == "__main__":
    sys.exit(main())
