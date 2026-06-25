"""``paper/experiments/run_benchmark.py`` — single-driver for TB 2.0 / TB Pro / SWE-Bench Pro.

This is the recommended entrypoint for the three benchmarks you
mentioned (Terminal-Bench 2.0, Terminal-Bench Pro, SWE-Bench Pro).
It supersedes the stub-only ``run_terminalbench.py``.

Usage:

    # TB 2.0, paper mode, Claude Sonnet 4.5
    uv run python -m paper.experiments.run_benchmark \\
        --benchmark tb2 \\
        --mode paper \\
        --agent-model anthropic/claude-sonnet-4-5

    # TB Pro, skillsvote mode, Codex GPT-5.5
    uv run python -m paper.experiments.run_benchmark \\
        --benchmark tb_pro \\
        --mode skillsvote \\
        --agent-import-path skills_vote.harbor.agents:SkillsVoteCodex \\
        --agent-model openai/gpt-5.5 \\
        --agent-version 0.125.0

    # SWE-Bench Pro, paper mode, Opus 4.1
    uv run python -m paper.experiments.run_benchmark \\
        --benchmark swebenchpro \\
        --mode paper \\
        --agent-model anthropic/claude-opus-4-1

The driver writes a Harbor JobConfig YAML to ``--output-dir/configs/`` and
invokes the corresponding ``paper <mode> run -c <yaml>`` subcommand.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Make ``paper.*`` importable when this file is run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Per-benchmark default configuration. Each entry is a dict that gets
# merged into the generated JobConfig YAML. Override individual fields
# via CLI flags.
BENCHMARKS: dict[str, dict[str, Any]] = {
    "tb2": {
        "dataset": {
            "name": "terminal-bench",
            "version": "2.0",
            "download_dir": "input/tb2",
        },
        "default_n_concurrent": 8,
        "default_n_attempts": 5,
        "default_timeout_multiplier": 4.0,
        "default_task_subset": None,  # full 89-task corpus
    },
    "tb_pro": {
        "dataset": {
            "name": "terminal-bench-pro",
            "version": "1.0",
            "download_dir": "input/tb-pro",
        },
        "default_n_concurrent": 4,
        "default_n_attempts": 1,
        "default_timeout_multiplier": 4.0,
        "default_task_subset": [
            "rebuild-fastproc-for-python-3-13",
        ],
    },
    "swebenchpro": {
        "dataset": {
            "name": "swebenchpro",
            "version": "1.0",
            "download_dir": "input/swebenchpro",
        },
        "default_n_concurrent": 2,
        "default_n_attempts": 1,
        "default_timeout_multiplier": 4.0,
        "default_task_subset": [
            "instance_protonmail__webclients-0200ce0fc1d4dbd35178c10d440a284c82ecc858",
            "instance_qutebrowser__qutebrowser-b8c93a8a3a64e2c6cdc2ddde2c6b1ade4dd3cbe9",
        ],
    },
}


def build_job_config(
    *,
    benchmark: str,
    mode: str,
    agent_import_path: str,
    agent_model: str,
    n_concurrent: int,
    n_attempts: int,
    timeout_multiplier: float,
    task_subset: list[str] | None,
    jobs_dir: str,
    job_name: str,
) -> dict[str, Any]:
    """Construct a Harbor-compatible JobConfig dict."""
    spec = BENCHMARKS[benchmark]
    if mode == "paper":
        # Paper mode uses SkillQClaudeCodeAgent directly (no upstream
        # base class). If the user supplied a non-skills_vote import
        # path, fall back to it and skip the paper-specific kwargs.
        if "skills_vote" not in agent_import_path:
            raise ValueError(
                "paper mode requires a skills_vote-backed agent (got "
                f"{agent_import_path!r}). Either pass a skills_vote import "
                "path or use --mode skillsvote."
            )
        agent_block: dict[str, Any] = {
            "import_path": "skillq.skillq_runtime.agent:SkillQClaudeCodeAgent",
            "model_name": agent_model,
            "kwargs": {
                "allowed_skills": [],
                "recommend": {
                    "skills_dir": "${abspath:.skillq_library/seed}",
                    # Intentionally no prompt_path here. skillsvote's
                    # step_recommend calls prompt_path(**kwargs) with
                    # extra kwargs (notably key=...) that
                    # paper.skillq_runtime.retrieval_step.rerank_with_ucb
                    # does not accept, and would TypeError before
                    # PaperClaudeCodeAgent.run gets a chance to call
                    # rerank_with_ucb on the instruction. The mg UCB
                    # rerank is invoked directly from
                    # PaperClaudeCodeAgent.run, not via prompt_path;
                    # leaving prompt_path unset lets skillsvote fall back
                    # to its own DEFAULT_PROMPT_PATH
                    # (skills_vote.recommend.prompt:build).
                },
            },
        }
    else:  # skillsvote mode
        agent_block = {
            "import_path": agent_import_path,
            "model_name": agent_model,
            "kwargs": {
                "allowed_skills": [],
                "recommend": {
                    "skills_dir": "${abspath:.skillq_library/seed}",
                    "prompt_path": "skills_vote.recommend.prompt:build",
                },
            },
        }

    cfg: dict[str, Any] = {
        "jobs_dir": jobs_dir,
        "job_name": job_name,
        "n_attempts": n_attempts,
        "n_concurrent_trials": n_concurrent,
        "quiet": False,
        "retry": {
            "max_retries": 0 if benchmark != "tb2" else 3,
            "exclude_exceptions": [
                "VerifierTimeoutError",
                "RewardFileNotFoundError",
                "RewardFileEmptyError",
                "VerifierOutputParseError",
            ],
        },
        "agent_timeout_multiplier": timeout_multiplier,
        "environment": {
            "type": "docker",
            "force_build": False,
            "delete": False,
        },
        "agents": [agent_block],
        "datasets": [dict(spec["dataset"])],
    }

    if task_subset:
        cfg["datasets"][0]["task_names"] = task_subset
    elif spec["default_task_subset"]:
        cfg["datasets"][0]["task_names"] = list(spec["default_task_subset"])

    return cfg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_benchmark")
    parser.add_argument(
        "--benchmark",
        choices=list(BENCHMARKS.keys()),
        required=True,
    )
    parser.add_argument("--mode", choices=["skillsvote", "paper"], default="paper")
    parser.add_argument(
        "--agent-import-path",
        default="skills_vote.harbor.claude_code:SkillsVoteClaudeCode",
        help="Only used in --mode skillsvote.",
    )
    parser.add_argument(
        "--agent-model",
        default="anthropic/claude-sonnet-4-5",
    )
    parser.add_argument("--n-concurrent", type=int, default=None)
    parser.add_argument("--n-attempts", type=int, default=None)
    parser.add_argument("--timeout-multiplier", type=float, default=None)
    parser.add_argument(
        "--task-subset",
        nargs="*",
        default=None,
        help="Optional list of dataset task names; overrides defaults.",
    )
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        default=Path("output"),
    )
    parser.add_argument(
        "--job-name",
        default=None,
        help="Defaults to <benchmark>_<mode>__<timestamp>.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments/configs"),
        help="Where to write the generated JobConfig YAML.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the config YAML but do not invoke mg <mode> run.",
    )
    args = parser.parse_args(argv)

    spec = BENCHMARKS[args.benchmark]
    n_concurrent = args.n_concurrent or spec["default_n_concurrent"]
    n_attempts = args.n_attempts or spec["default_n_attempts"]
    timeout_multiplier = args.timeout_multiplier or spec["default_timeout_multiplier"]
    task_subset = args.task_subset if args.task_subset else spec["default_task_subset"]

    from datetime import datetime

    job_name = args.job_name or (
        f"{args.benchmark}_{args.mode}__"
        f"{datetime.now().strftime('%Y-%m-%d__%H-%M-%S')}"
    )

    cfg = build_job_config(
        benchmark=args.benchmark,
        mode=args.mode,
        agent_import_path=args.agent_import_path,
        agent_model=args.agent_model,
        n_concurrent=n_concurrent,
        n_attempts=n_attempts,
        timeout_multiplier=timeout_multiplier,
        task_subset=task_subset,
        jobs_dir=str(args.jobs_dir),
        job_name=job_name,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = args.output_dir / f"{args.benchmark}_{args.mode}.yaml"
    import yaml

    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    print(f"[run_benchmark] wrote {cfg_path}")

    if args.dry_run:
        return 0

    cmd = [sys.executable, "-m", "paper.cli", args.mode, "run", "-c", str(cfg_path)]
    print(f"[run_benchmark] {' '.join(cmd)}")
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
