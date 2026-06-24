"""argparse subcommand for ``paper paper``."""

from __future__ import annotations

import argparse
from pathlib import Path

from skillq.paper_mode.config import MethodConfig


def build_parser(parent: argparse.ArgumentParser) -> None:
    """Attach ``paper paper <subcommand>`` subparsers to ``parent``."""
    sub = parent.add_subparsers(dest="paper_command", required=True, metavar="PAPER_CMD")

    run_p = sub.add_parser(
        "run",
        help="Run a Harbor job with the four-layer SkillQ paper method.",
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

    # prime-uv-cache (2026-06-24): pre-populate a host-side uv cache
    # so the agent container can reuse torch / pytest wheels instead
    # of cold-downloading them on every verifier trial. See plan
    # bug-3-per-trial-q-table-json-hashed-quilt.md, Fix #1.
    prime_p = sub.add_parser(
        "prime-uv-cache",
        help=(
            "Pre-populate a host-side uv cache with the wheels needed by "
            "slow task verifiers (e.g. torch for pytorch tasks). Bind-mount "
            "this cache into the agent container via "
            "MethodConfig.verifier_uv_cache_path to skip cold downloads."
        ),
    )
    prime_p.add_argument(
        "--cache-path",
        type=Path,
        default=Path.home() / ".skillq_cache" / "uv",
        help=(
            "Host directory to populate. Will be created if missing. "
            "Default ~/.skillq_cache/uv."
        ),
    )
    prime_p.add_argument(
        "--python-version",
        default="3.13",
        help=(
            "Python version to pin wheels to (must match what the "
            "container's test.sh uses, e.g. '-p 3.13' for pytorch tasks). "
            "Default 3.13."
        ),
    )
    prime_p.add_argument(
        "--platform",
        default=None,
        help=(
            "Optional platform tag for the wheel, e.g. 'manylinux2014_x86_64'. "
            "Default None: let uv auto-select for the host. Most useful when "
            "the host and container are different arches (e.g. WSL2 amd64 "
            "container on an arm64 host)."
        ),
    )
    prime_p.add_argument(
        "--wheels",
        nargs="+",
        required=True,
        help=(
            "Wheels to pre-populate, e.g. 'torch==2.7.1' 'pytest==8.4.1'. "
            "Pip version specifiers are passed through to `uv pip download`."
        ),
    )
    prime_p.set_defaults(handler=_prime_uv_cache_command)


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
    # lqrl and paper.
    from skillq.env import load_env_file

    try:
        load_env_file(args.env_file)
    except FileNotFoundError as exc:
        print(f"[mg paper] {exc}", flush=True)
        return 2

    method = _load_method_config(args.method_config_path)
    from skillq.paper_mode.bridge import run_paper_job_sync

    return run_paper_job_sync(args.config_path, method)


def _prime_uv_cache_command(args: argparse.Namespace) -> int:
    """Pre-populate a host-side uv cache so the agent container can
    reuse cached wheels (torch, pytest, ...) instead of cold-downloading
    them on every verifier trial.

    2026-06-24: added to address the 5/6 pytorch-task verifier timeouts
    in the 2026-06-24 full run. See plan
    bug-3-per-trial-q-table-json-hashed-quilt.md, Fix #1.
    """
    import shutil
    import subprocess
    import sys

    cache = args.cache_path.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    wheels_dir = cache / "wheels-v0"
    wheels_dir.mkdir(exist_ok=True)
    envs_dir = cache / "environments-v2"
    envs_dir.mkdir(exist_ok=True)
    # Pre-create the XDG CACHEDIR.TAG marker file. `uvx` inside the
    # container tries to write this when it first touches the cache
    # directory. If the cache is bind-mounted RO (which it is, for
    # safety — the container must not be able to mutate the host
    # cache), that write fails with "Read-only file system (os
    # error 30)" and `uvx` aborts before even checking the wheels.
    # Standard XDG CACHEDIR.TAG contents — see
    # https://bford.info/cachedir/
    cache_dir_tag = cache / "CACHEDIR.TAG"
    if not cache_dir_tag.exists():
        cache_dir_tag.write_text(
            "Signature: 8a477f597d28d172789f06886806bc55\n"
            "# This file is a cache directory tag created by `skillq paper "
            "prime-uv-cache`.\n"
            "# For information about cache directory tags, see:\n"
            "#   https://bford.info/cachedir/\n",
            encoding="utf-8",
        )

    # Sanity check: `uv` must be on PATH. (test.sh installs uv 0.9.5
    # inside the container; the host should also have a recent uv.)
    if shutil.which("uv") is None:
        print(
            "[mg paper prime-uv-cache] ERROR: `uv` not on PATH. "
            "Install via `curl -LsSf https://astral.sh/uv/install.sh | sh` "
            "or `pip install uv`.",
            file=sys.stderr,
            flush=True,
        )
        return 3

    # Step 1: ensure the host has a uv-managed Python at the requested
    # version. `uv pip download` doesn't actually need the interpreter
    # locally (it just needs the version to compute wheel tags), but
    # `uv python install` is the canonical way to advertise the
    # version to uv's internal resolver cache.
    print(
        f"[mg paper prime-uv-cache] ensuring uv-managed Python "
        f"{args.python_version} is available...",
        flush=True,
    )
    try:
        subprocess.run(
            ["uv", "python", "install", args.python_version],
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"[mg paper prime-uv-cache] ERROR: `uv python install` "
            f"failed with exit code {exc.returncode}.",
            file=sys.stderr,
            flush=True,
        )
        return exc.returncode or 4

    # Step 2: pre-download the wheels tagged for the requested Python
    # version. We use the *system* `pip download` here (not
    # `uv pip install --target`) because:
    #
    # - `uv pip install --target` EXTRACTS the wheels into a
    #   venv-like directory (torch/, numpy/, ...), but `uvx` inside
    #   the container looks for raw `.whl` files in its cache, not
    #   extracted packages.
    # - `uv pip download` was removed in uv 0.10+.
    # - System `pip` (3.10+) supports `pip download
    #   --python-version 3.13 --only-binary=:all:` and saves the
    #   .whl files verbatim into the destination dir, which is
    #   exactly the layout `uvx` expects.
    #
    # `--no-deps` keeps the cache small — only the wheels we
    # explicitly asked for land in wheels-v0/. Transitive deps
    # (markupsafe, packaging, ...) are tiny and uvx will resolve
    # them per-trial from its own internal cache.
    if shutil.which("pip3") is None and shutil.which("pip") is None:
        print(
            "[mg paper prime-uv-cache] ERROR: neither `pip3` nor `pip` "
            "is on PATH. Install Python 3 system pip via your OS package "
            "manager, or run inside a uv-managed venv.",
            file=sys.stderr,
            flush=True,
        )
        return 6
    pip_bin = shutil.which("pip3") or shutil.which("pip")
    cmd = [
        pip_bin, "download",
        "--python-version", args.python_version,
        "--only-binary=:all:",
        "--no-deps",
        "--dest", str(wheels_dir),
    ]
    if args.platform:
        cmd.extend(["--platform", args.platform])
    cmd.extend(args.wheels)

    print(
        f"[mg paper prime-uv-cache] downloading {len(args.wheels)} wheel(s) "
        f"to {wheels_dir}...",
        flush=True,
    )
    print(f"[mg paper prime-uv-cache] command: {' '.join(cmd)}", flush=True)
    try:
        subprocess.run(
            cmd,
            check=True,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
    except subprocess.CalledProcessError as exc:
        print(
            f"[mg paper prime-uv-cache] ERROR: `pip download` failed "
            f"with exit code {exc.returncode}. Check the wheel version "
            f"specifiers (got: {args.wheels}).",
            file=sys.stderr,
            flush=True,
        )
        return exc.returncode or 5

    # Step 3: report
    n_wheels = sum(1 for _ in wheels_dir.glob("*.whl"))
    print(
        f"[mg paper prime-uv-cache] done. {n_wheels} wheel(s) in {wheels_dir}.",
        flush=True,
    )
    print(
        f"[mg paper prime-uv-cache] to use, set in your method YAML:\n"
        f"    verifier_uv_cache_path: {cache}",
        flush=True,
    )
    return 0

