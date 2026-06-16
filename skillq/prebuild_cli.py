"""``skillq prebuild`` — pre-build per-task Docker images for TB / TB Pro / SWE-Bench Pro.

skillq re-uses Harbor's trial-orchestration pipeline and the same Docker
images that the vendored ``skillsvote/`` package prebuilds. This
subcommand is a thin wrapper around the vendored
``skillsvote/prebuild_images.py`` (which itself shells out to
``harbor datasets download`` and ``docker build``).

The vendored ``prebuild_images.py`` is sourced from the in-tree
``./skillsvote/`` directory — no external ``../lqrl`` path is needed.
Override the path via ``$SkillQ_ROOT`` or ``--skillsvote-root``.

Why prebuild at all? Every trial runs in a fresh container. Without
prebuild, the trial would have to apt-get / pip install the agent +
dependencies from scratch on each launch — that's 5-10 minutes per
trial. Prebuild installs the agent once, tags the image as
``local/<task>:<tag>`` (or the configured registry), and every
subsequent trial reuses that image. For 50-trial runs this saves
hours.

Typical usage:

    # Pre-build all TB 2.0 task images (default: 4 workers, today's date)
    uv run skillq prebuild run --benchmark tb2 --agent claude_code

    # TB Pro, claude-code agent, custom image tag
    uv run skillq prebuild run --benchmark tb_pro --agent claude_code \\
        --image-tag 20260605

    # SWE-Bench Pro, codex agent
    uv run skillq prebuild run --benchmark swebenchpro --agent codex

    # Pass a custom prebuild YAML
    uv run skillq prebuild run --benchmark tb2 --agent claude_code \\
        --cfg-path /path/to/my_prebuild.yaml

Note: the per-benchmark YAMLs (``scripts/configs/prebuild_images*.yaml``)
are not vendored — the user supplies a ``--cfg-path`` (or the script
falls back to a vendored default if one exists).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Vendored skillsvote package root. The prebuild script lives at
# ``$SkillQ_ROOT/experiments/prebuild/prebuild_images.py`` (mirrors
# the upstream ``lqrl/scripts/prebuild_images.py`` location).
# Override via ``$SkillQ_ROOT`` env var or ``--skillsvote-root`` CLI flag.
SkillQ_ROOT = Path(os.environ.get("SkillQ_ROOT", "./skillsvote"))


def build_parser(parent: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Attach prebuild args to ``parent`` (the ``skillq prebuild`` subparser)."""
    parent.add_argument(
        "--cfg-path",
        type=Path,
        default=None,
        help=(
            "Path to a prebuild YAML config. Required unless "
            "$SkillQ_ROOT/prebuild_default.yaml exists."
        ),
    )
    parent.add_argument(
        "--image-tag",
        default=None,
        help="Image tag (default: today's YYYYMMDD).",
    )
    parent.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Parallel Docker builds (passed via env to prebuild_images.py).",
    )
    parent.add_argument(
        "--skillsvote-root",
        type=Path,
        default=SkillQ_ROOT,
        help=(
            "Path to the vendored skillsvote tree (default: "
            "$SkillQ_ROOT or ./skillsvote)."
        ),
    )
    parent.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help=(
            "Path to a dotenv file (OPENAI_*/ANTHROPIC_*/CODEX_*). "
            "Same shape as the upstream skillsvote .env."
        ),
    )
    parent.set_defaults(handler=_run_command)
    return parent


def _run_command(args: argparse.Namespace) -> int:
    # Load .env so the vendored prebuild script sees the same env vars
    # as `skillq paper run`.
    from skillq.env import load_env_file

    try:
        load_env_file(args.env_file)
    except FileNotFoundError as exc:
        print(f"[skillq prebuild] {exc}", file=sys.stderr)
        return 2

    skillsvote_root: Path = args.skillsvote_root
    if not skillsvote_root.exists():
        print(
            f"[skillq prebuild] skillsvote tree not found at {skillsvote_root}. "
            "Pass --skillsvote-root or set $SkillQ_ROOT.",
            file=sys.stderr,
        )
        return 2

    prebuild_script = skillsvote_root / "experiments" / "prebuild" / "prebuild_images.py"
    if not prebuild_script.exists():
        print(
            f"[skillq prebuild] prebuild script not found at {prebuild_script}.",
            file=sys.stderr,
        )
        return 2

    cfg_path: Path | None = args.cfg_path
    if cfg_path is None:
        # Fall back to a vendored default if the user has one.
        candidate = skillsvote_root / "prebuild_default.yaml"
        if candidate.exists():
            cfg_path = candidate
        else:
            print(
                "[skillq prebuild] --cfg-path is required (no vendored "
                "default found). Pass --cfg-path or place "
                "prebuild_default.yaml under the skillsvote tree.",
                file=sys.stderr,
            )
            return 2
    if not cfg_path.exists():
        print(
            f"[skillq prebuild] prebuild YAML not found: {cfg_path}",
            file=sys.stderr,
        )
        return 2

    image_tag = args.image_tag or datetime.now().strftime("%Y%m%d")
    print(f"[skillq prebuild] cfg={cfg_path}")
    print(f"[skillq prebuild] image_tag={image_tag}")
    print(f"[skillq prebuild] max_workers={args.max_workers}")

    cmd = [
        sys.executable,
        str(prebuild_script),
        "--cfg-path",
        str(cfg_path),
    ]
    print(f"[skillq prebuild] {' '.join(cmd)}")
    env = os.environ.copy()
    env["MAX_WORKERS"] = str(args.max_workers)
    result = subprocess.run(cmd, cwd=str(skillsvote_root), env=env)
    return result.returncode


if __name__ == "__main__":  # pragma: no cover
    parser = argparse.ArgumentParser(prog="skillq prebuild")
    build_parser(parser)
    sys.exit(_run_command(parser.parse_args()))