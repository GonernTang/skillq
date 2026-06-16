"""``paper.env`` — dotenv loader shared by ``paper paper run`` / ``paper prebuild run``.

Mirrors :func:`skills_vote.harbor.cli.load_env_file` so that ``paper .env``
behaves the same as ``skillsvote .env``: same variable names, same precedence
(``override=True``), same silent-when-missing behaviour.

Usage from a CLI module:

    from skillq.env import load_env_file
    explicit_keys = load_env_file(args.env_file)
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_FILE = Path(".env")


def load_env_file(env_file: Path | str | None = None) -> set[str]:
    """Load the env file into ``os.environ`` and return the keys it defined.

    - If ``env_file`` is ``None``, default to ``.env`` in the cwd.
    - If the file does not exist (and is not the default), raise
      :class:`FileNotFoundError` so the user notices.
    - The ``override=True`` flag means explicit process env vars are
      *overridden* by the dotenv file; this matches skillsvote's behaviour
      and is the more useful semantics for "load my secrets, I want
      them to take effect".
    """
    from dotenv import dotenv_values, load_dotenv

    if env_file is None:
        path = DEFAULT_ENV_FILE
    else:
        path = Path(env_file).expanduser()
    if path.exists():
        load_dotenv(path, override=True)
        return {key for key in dotenv_values(path) if key is not None}

    if path != DEFAULT_ENV_FILE:
        raise FileNotFoundError(f"Env file not found: {path}")

    return set()


def load_mg_yaml_env(yaml_path: Path) -> set[str]:
    """Convenience: load ``yaml_path`` (must be ``.env``-style) if it exists.

    Same semantics as :func:`load_env_file` but takes a Path directly.
    """
    if not yaml_path.exists():
        return set()
    return load_env_file(yaml_path)
