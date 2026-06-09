"""Tests for the ``mg skillsvote_mode`` pass-through entrypoint.

These tests verify that the entrypoint is a *pure* pass-through:
- ``SkillsVoteModeConfig`` accepts arbitrary extra fields.
- ``mg.skillsvote_mode.cli._run_command`` dispatches to
  ``skills_vote.harbor.cli.main`` (mocked here, since the upstream
  package's CLI exits the interpreter).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mg.skillsvote_mode.config import SkillsVoteModeConfig  # noqa: E402


def test_skillsvote_mode_config_accepts_arbitrary_extra_fields():
    """SkillsVoteConfig is permissive; mg's marker class should be too."""
    cfg = SkillsVoteModeConfig(
        feedback_prompt_path="prompts/feedback.j2",
        evolve_prompt_path="prompts/evolve.j2",
        evolve_every_n_trials=2,
        register_import_paths=["my_pkg.bridge:register"],
    )
    dumped = cfg.model_dump()
    assert dumped["feedback_prompt_path"] == "prompts/feedback.j2"
    assert dumped["register_import_paths"] == ["my_pkg.bridge:register"]


def test_skillsvote_mode_cli_run_dispatches_to_upstream(monkeypatch, tmp_path):
    """``mg skillsvote run -c X`` should call ``skills_vote.harbor.cli.main``."""
    from mg.skillsvote_mode import cli as skillsvote_cli

    captured: dict = {}

    def fake_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(
        "skills_vote.harbor.cli.main", fake_main, raising=False
    )

    cfg_path = tmp_path / "job.yaml"
    cfg_path.write_text("agents: []\n", encoding="utf-8")

    rc = skillsvote_cli._run_command(
        type("Args", (), {
            "config_path": str(cfg_path),
            "env_file": str(tmp_path / ".env"),
            "yes": True,
            "overrides": ["job_name=abc"],
        })()
    )
    assert rc == 0
    assert captured["argv"][0] == "run"
    assert captured["argv"][1] == "-c"
    assert captured["argv"][2] == str(cfg_path)
    assert "-y" in captured["argv"]
    assert "job_name=abc" in captured["argv"]
