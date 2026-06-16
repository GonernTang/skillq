"""``paper/experiments/run_terminalbench.py`` — main TB 2.0 / TB Pro driver.

Usage:

    # Run the paper method on Terminal-Bench 2.0 (15 tasks, 5 seeds).
    uv run python -m paper.experiments.run_terminalbench \
        --mode paper \
        --benchmark tb2 \
        --n-tasks 15 \
        --n-seeds 5 \
        --jobs-dir output/tb2_skillq

    # Run the vendored skillsvote mode for comparison.
    uv run python -m paper.experiments.run_terminalbench \
        --mode skillsvote \
        --benchmark tb2 \
        --n-tasks 15 \
        --n-seeds 5 \
        --jobs-dir output/tb2_skillsvote

The driver writes one Harbor job-config YAML per (seed, mode) cell
under ``--jobs-dir/configs/`` and then calls the corresponding
``paper <mode> run -c <yaml>`` entrypoint. Results land under
``--jobs-dir/<job_name>/`` per Harbor's own convention.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TBBenchTask:
    """A single Terminal-Bench task stub.

    Replace the loading logic with a call to the official
    ``terminal_bench`` package when it is installed in the runtime
    environment.
    """

    task_id: str
    instruction: str
    verifier: str
    env_image: str
    metadata: dict = field(default_factory=dict)


def load_tb2_stub(n: int = 15, seed: int = 42) -> list[TBBenchTask]:
    """Return a deterministic stub list of ``n`` TB 2.0 tasks.

    Real benchmarks should be loaded via the official client; the stub
    exists so the experiment driver can be exercised end-to-end without
    Docker.
    """
    base = [
        TBBenchTask(
            task_id=f"tb2-{i:03d}",
            instruction=f"Implement the task described in TB2 stub slot {i}.",
            verifier="echo 1 > /logs/verifier/reward.txt",
            env_image="harbor/tb2:stub",
        )
        for i in range(n)
    ]
    return base


def build_job_config(
    *,
    tasks: list[TBBenchTask],
    agent: str,
    model: str,
    mode: str,
    n_concurrent: int,
) -> dict[str, Any]:
    """Construct a Harbor-compatible JobConfig dict for a given (mode, tasks)."""
    return {
        "job_name": f"tb2_{mode}_seed{42}",
        "n_concurrent_trials": n_concurrent,
        "agents": [
            {
                "import_path": (
                    "skillq.paper_mode.agent:SkillQClaudeCodeAgent"
                    if mode == "paper"
                    else "skills_vote.harbor.claude_code:SkillsVoteClaudeCode"
                ),
                "model_name": model,
                "kwargs": {
                    "recommend": {
                        "prompt_path": "prompts/recommend.j2",
                        "skills_dir": "./.skills",
                        "default_top_k": 5,
                    },
                },
            }
        ],
        "tasks": [
            {
                "path": f".tasks/{t.task_id}",
                "instruction": t.instruction,
            }
            for t in tasks
        ],
        "environment": {"type": "docker"},
        "verifier": {"type": "shell"},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_terminalbench")
    parser.add_argument("--mode", choices=["skillsvote", "paper"], required=True)
    parser.add_argument("--benchmark", choices=["tb2", "tbpro"], default="tb2")
    parser.add_argument("--n-tasks", type=int, default=15)
    parser.add_argument("--n-seeds", type=int, default=5)
    parser.add_argument("--agent", default="claude-code")
    parser.add_argument("--model", default="anthropic/claude-sonnet-4-5")
    parser.add_argument("--n-concurrent", type=int, default=2)
    parser.add_argument(
        "--jobs-dir",
        type=Path,
        default=Path("output/tb2"),
    )
    args = parser.parse_args(argv)

    configs_dir = args.jobs_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=True)

    summary: list[dict[str, Any]] = []
    for seed in range(args.n_seeds):
        tasks = load_tb2_stub(n=args.n_tasks, seed=seed)
        cfg = build_job_config(
            tasks=tasks,
            agent=args.agent,
            model=args.model,
            mode=args.mode,
            n_concurrent=args.n_concurrent,
        )
        cfg_path = configs_dir / f"{args.mode}_seed{seed}.yaml"
        import yaml  # local import to keep top-level imports lean

        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

        cmd = [sys.executable, "-m", "paper.cli", args.mode, "run", "-c", str(cfg_path)]
        print(f"[run_terminalbench] {' '.join(cmd)}")
        result = subprocess.run(cmd, env=None)
        summary.append(
            {
                "seed": seed,
                "mode": args.mode,
                "returncode": result.returncode,
                "config": str(cfg_path),
            }
        )

    (args.jobs_dir / f"summary_{args.mode}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
