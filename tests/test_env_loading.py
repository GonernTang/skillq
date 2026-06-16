"""Tests for the ``paper.env`` dotenv loader.

These tests focus on the contract: a single ``.env`` file is shared
between ``skillq skillsvote`` (which forwards to ``skills_vote.harbor.cli``) and
``skillq paper`` / ``skillq prebuild`` (which use this module's loader). The
keys / values are exactly skillsvote's, so a user can copy ``skillsvote/.env`` to
``mg/.env`` and have it work.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.env import load_env_file, load_mg_yaml_env  # noqa: E402


def test_load_env_file_reads_lqrl_compatible_keys(tmp_path: Path, monkeypatch):
    """Loader must read OPENAI_*/ANTHROPIC_*/CODEX_* the way skillsvote does."""
    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_API_KEY=sk-test-123\n"
        "ANTHROPIC_API_KEY=sk-ant-456\n"
        "CODEX_FORCE_API_KEY=1\n",
        encoding="utf-8",
    )
    # Ensure the test starts in a clean environment for these keys.
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_FORCE_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    keys = load_env_file(env)
    assert keys == {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CODEX_FORCE_API_KEY"}
    assert os.environ["OPENAI_API_KEY"] == "sk-test-123"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-456"
    assert os.environ["CODEX_FORCE_API_KEY"] == "1"


def test_load_env_file_default_path_silently_no_op(tmp_path: Path, monkeypatch):
    """If neither ``.env`` nor the user-specified file exists, no error."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert load_env_file() == set()
    assert "OPENAI_API_KEY" not in os.environ


def test_load_env_file_missing_explicit_path_raises(tmp_path: Path):
    """A non-default, missing path must surface as FileNotFoundError."""
    bogus = tmp_path / "no-such.env"
    try:
        load_env_file(bogus)
    except FileNotFoundError as exc:
        assert "no-such.env" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected FileNotFoundError")


def test_load_env_file_override_true(monkeypatch, tmp_path: Path):
    """Explicit env vars should be overridden by .env values (skillsvote parity)."""
    monkeypatch.setenv("OPENAI_API_KEY", "preexisting-value")
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=from-dotenv\n", encoding="utf-8")

    load_env_file(env)
    assert os.environ["OPENAI_API_KEY"] == "from-dotenv"
