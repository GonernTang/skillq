"""argparse subcommand for ``mg skillsvote``."""

from __future__ import annotations

import argparse
from pathlib import Path


def _path_exists(s: str) -> str:
    """Argparse type: return ``s`` if it points to an existing file path.

    ``argparse.PathType`` was removed in Python 3.12; this is a
    stdlib-only replacement that mirrors the pre-3.12 behaviour.
    """
    p = Path(s)
    if not p.exists():
        raise argparse.ArgumentTypeError(f"file does not exist: {s}")
    return str(p)


def build_parser(parent: argparse.ArgumentParser) -> None:
    """Attach ``mg skillsvote <subcommand>`` subparsers to ``parent``."""
    sub = parent.add_subparsers(
        dest="skillsvote_command", required=True, metavar="SV_CMD"
    )

    run_p = sub.add_parser(
        "run",
        help="Run a SkillsVote-baseline Harbor job (the comparison method).",
    )
    run_p.add_argument(
        "-c",
        "--config",
        "--config-path",
        dest="config_path",
        type=_path_exists,
        required=True,
    )
    run_p.add_argument(
        "--env-file",
        type=_path_exists,
        default=".env",
    )
    run_p.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation when tasks read environment variables from the host.",
    )
    run_p.add_argument(
        "overrides",
        nargs="*",
        help="OmegaConf dotlist overrides, e.g. job_name=my_job",
    )
    run_p.set_defaults(handler=_run_command)


def _run_command(args: argparse.Namespace) -> int:
    """Dispatch to upstream SkillsVote's :func:`skills_vote.harbor.cli.main`."""
    # Late import: keep the paper-mode modules un-imported when the user
    # only uses ``mg skillsvote``.
    from skills_vote.harbor.cli import main as skillsvote_main

    argv: list[str] = ["run", "-c", args.config_path, "--env-file", args.env_file]
    if args.yes:
        argv.append("-y")
    argv.extend(args.overrides)
    return skillsvote_main(argv)
