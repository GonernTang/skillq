"""argparse subcommand for ``mg paper``."""

from __future__ import annotations

import argparse
from pathlib import Path

from mg.paper_mode.config import MethodConfig


def build_parser(parent: argparse.ArgumentParser) -> None:
    """Attach ``mg paper <subcommand>`` subparsers to ``parent``."""
    sub = parent.add_subparsers(dest="paper_command", required=True, metavar="PAPER_CMD")

    run_p = sub.add_parser(
        "run",
        help="Run a Harbor job with the four-layer LQRL paper method.",
    )
    run_p.add_argument(
        "-c",
        "--config",
        "--config-path",
        dest="config_path",
        type=Path,
        required=True,
        help="Path to a Harbor JobConfig YAML file.",
    )
    run_p.add_argument(
        "--method-config",
        dest="method_config_path",
        type=Path,
        default=None,
        help=(
            "Optional YAML/JSON with MethodConfig overrides. If omitted, "
            "the method runs with the default hyperparameters."
        ),
    )
    run_p.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help=(
            "Path to a dotenv file with OPENAI_*/ANTHROPIC_* keys. Same "
            "shape as lqrl's .env.example. Default: .env in cwd."
        ),
    )
    run_p.set_defaults(handler=_run_command)


def _load_method_config(path: Path | None) -> MethodConfig:
    if path is None:
        return MethodConfig()
    if not path.exists():
        raise FileNotFoundError(f"Method config not found: {path}")
    if path.suffix in {".yaml", ".yml"}:
        from omegaconf import OmegaConf

        raw = OmegaConf.to_container(OmegaConf.load(str(path)), resolve=True)
    elif path.suffix == ".json":
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"Unsupported method config suffix: {path.suffix}")
    if not isinstance(raw, dict):
        raise TypeError("Method config must be a mapping.")
    return MethodConfig.model_validate(raw)


def _run_command(args: argparse.Namespace) -> int:
    # Load the .env (lqrl-compatible: OPENAI_*, ANTHROPIC_*, CODEX_*).
    # Same loader lqrl uses; lets the user share a single .env between
    # lqrl and mg.
    from mg.env import load_env_file

    try:
        load_env_file(args.env_file)
    except FileNotFoundError as exc:
        print(f"[mg paper] {exc}", flush=True)
        return 2

    method = _load_method_config(args.method_config_path)
    from mg.paper_mode.bridge import run_paper_job_sync

    return run_paper_job_sync(args.config_path, method)

