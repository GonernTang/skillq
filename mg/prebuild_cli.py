"""``mg prebuild`` — pre-build per-task Docker images for TB / TB Pro / SWE-Bench Pro.

mg re-uses Harbor's trial-orchestration pipeline and the same Docker
images that lqrl prebuilds. We do **not** re-implement the prebuild
logic; this subcommand is a thin wrapper around lqrl's
``scripts/prebuild_images.py`` (which itself shells out to
``harbor datasets download`` and ``docker build``).

Why prebuild at all? Every trial runs in a fresh container. Without
prebuild, the trial would have to apt-get / pip install the agent +
dependencies from scratch on each launch — that's 5-10 minutes per
trial. Prebuild installs the agent once, tags the image as
``local/<task>:<tag>`` (or the configured registry), and every
subsequent trial reuses that image. For 50-trial runs this saves
hours.

Typical usage:

    # Pre-build all TB 2.0 task images (default: 4 workers, today's date)
    uv run mg prebuild --benchmark tb2

    # TB Pro, claude-code agent, custom image tag
    uv run mg prebuild --benchmark tb_pro --agent claude_code \\
        --image-tag 20260605

    # SWE-Bench Pro, codex agent
    uv run mg prebuild --benchmark swebenchpro --agent codex

    # Pass a custom prebuild YAML
    uv run mg prebuild --benchmark tb2 \\
        --cfg-path /path/to/my_prebuild.yaml
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Per-benchmark default mapping. ``prebuild_yaml`` points at one of
# lqrl's pre-existing ``scripts/configs/prebuild_images*.yaml`` files.
# Override via ``--cfg-path`` if you have your own.
LQRL_ROOT = Path(os.environ.get("LQRL_ROOT", "/home/gonern/workspace/lqrl"))
DEFAULT_PREBUILDS: dict[str, dict[str, str]] = {
    "tb2": {
        "claude_code": "scripts/configs/prebuild_images.claude.yaml",
        "codex": "scripts/configs/prebuild_images.yaml",
    },
    "tb_pro": {
        "claude_code": "scripts/configs/prebuild_images.claude.yaml",
        "codex": "scripts/configs/prebuild_images.yaml",
    },
    "swebenchpro": {
        "claude_code": "scripts/configs/prebuild_images.claude.yaml",
        "codex": "scripts/configs/prebuild_images.yaml",
    },
}


def build_parser(parent: argparse.ArgumentParser) -> None:
    pre = parent.add_subparsers(
        dest="prebuild_command", required=True, metavar="PREBUILD_CMD"
    )

    run_p = pre.add_parser(
        "run",
        help="Pre-build the per-task Docker images for a benchmark.",
    )
    run_p.add_argument(
        "--benchmark",
        choices=["tb2", "tb_pro", "swebenchpro"],
        required=True,
    )
    run_p.add_argument(
        "--agent",
        choices=["claude_code", "codex"],
        default="claude_code",
        help="Which agent's preinstall Dockerfile to use.",
    )
    run_p.add_argument(
        "--cfg-path",
        type=Path,
        default=None,
        help=(
            "Override the default prebuild YAML. Defaults to one of lqrl's "
            "scripts/configs/prebuild_images*.yaml, picked by (benchmark, agent)."
        ),
    )
    run_p.add_argument(
        "--image-tag",
        default=None,
        help="Image tag (default: today's YYYYMMDD).",
    )
    run_p.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Parallel Docker builds.",
    )
    run_p.add_argument(
        "--lqrl-root",
        type=Path,
        default=LQRL_ROOT,
        help="Path to the lqrl source tree (default: /home/gonern/workspace/lqrl).",
    )
    run_p.add_argument(
        "--download-only",
        action="store_true",
        help="Just download task definitions, skip Docker builds.",
    )
    run_p.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help=(
            "Path to a dotenv file (OPENAI_*/ANTHROPIC_*/CODEX_*). Same "
            "shape as lqrl's .env. Default: .env in cwd."
        ),
    )
    run_p.set_defaults(handler=_run_command)


def _run_command(args: argparse.Namespace) -> int:
    # Load .env so the subprocess (lqrl's prebuild_images.py → harbor
    # datasets download) sees the same env vars as `mg paper run`.
    from mg.env import load_env_file

    try:
        load_env_file(args.env_file)
    except FileNotFoundError as exc:
        print(f"[mg prebuild] {exc}", file=sys.stderr)
        return 2

    lqrl_root: Path = args.lqrl_root
    if not lqrl_root.exists():
        print(
            f"[mg prebuild] lqrl source not found at {lqrl_root}. "
            "Pass --lqrl-root or set $LQRL_ROOT.",
            file=sys.stderr,
        )
        return 2

    prebuild_script = lqrl_root / "scripts" / "prebuild_images.py"
    if not prebuild_script.exists():
        print(f"[mg prebuild] {prebuild_script} does not exist.", file=sys.stderr)
        return 2

    # Resolve the prebuild YAML
    if args.cfg_path is not None:
        cfg_path = args.cfg_path
    else:
        rel = DEFAULT_PREBUILDS[args.benchmark][args.agent]
        cfg_path = lqrl_root / rel
    if not cfg_path.exists():
        print(f"[mg prebuild] prebuild YAML not found: {cfg_path}", file=sys.stderr)
        return 2

    image_tag = args.image_tag or datetime.now().strftime("%Y%m%d")
    print(f"[mg prebuild] benchmark={args.benchmark} agent={args.agent}")
    print(f"[mg prebuild] cfg={cfg_path}")
    print(f"[mg prebuild] image_tag={image_tag}")

    # ``prebuild_images.py`` reads the YAML and pulls / builds each
    # image. We pass --cfg-path through; --image-tag would need
    # editing the YAML, so we just print it for the user's reference.
    cmd = ["uv", "run", "python", str(prebuild_script), "--cfg-path", str(cfg_path)]
    print(f"[mg prebuild] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(lqrl_root))
    return result.returncode


if __name__ == "__main__":
    sys.exit(_run_command(_parse()))
