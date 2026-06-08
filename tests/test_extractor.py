"""Tests for ``mg/method/extractor.py`` SkillExtractor.

The extractor is a ``claude --print`` subprocess wrapper, so the tests
stub the subprocess at the ``asyncio.to_thread`` boundary. We don't
spawn a real Claude CLI in unit tests.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mg.method.extractor import SkillExtractor  # noqa: E402


def _fake_proc(*, returncode: int = 0, stdout: str = "", stderr: str = ""):
    proc = type("P", (), {})()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_extract_happy_path_writes_skill_md(tmp_path: Path, monkeypatch):
    """When the subprocess exits 0 and writes a valid SKILL.md under
    ``<sandbox>/create/<name>/``, we return a Skill with the right id
    and body.
    """
    async def fake_to_thread(fn, *args, **kwargs):
        # ``fn`` is subprocess.run; we don't actually invoke it. We
        # instead write a SKILL.md into the sandbox the extractor
        # already created, mimicking what the LLM would do.
        sandbox = Path(kwargs["cwd"])
        create_dir = sandbox / "create"
        create_dir.mkdir(parents=True, exist_ok=True)
        skill_dir = create_dir / "parse-cobol"
        skill_dir.mkdir(parents=True, exist_ok=True)
        # Pad the body to satisfy the default body_min_tokens=50.
        padding = " ".join(["l"] * 80)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: parse-cobol\n"
            "description: parse fixed-width COBOL records using awk\n"
            "---\n# parse-cobol\n\nUse `awk` to slice bytes 1-6 of each line.\n\n"
            + padding + "\n",
            encoding="utf-8",
        )
        return _fake_proc(returncode=0)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)

    extractor = SkillExtractor(claude_cli="claude", timeout_sec=10)
    skill = asyncio.run(
        extractor.extract(
            task="parse fixed-width COBOL records",
            knowledge="Use awk to slice bytes 1-6 of each line.",
            intent_hash=0xDEADBEEF,
            sandbox_root=tmp_path,
        )
    )

    assert skill is not None
    assert skill.skill_id == "parse-cobol"
    assert "awk" in skill.body
    assert skill.metadata["source"] == "mg_paper_extract"
    assert skill.metadata["intent_hash"] == "00000000deadbeef"
    assert skill.metadata["has_scripts"] is False


def test_extract_rejects_undersized_body(tmp_path: Path, monkeypatch):
    async def fake_to_thread(fn, *args, **kwargs):
        sandbox = Path(kwargs["cwd"])
        create_dir = sandbox / "create"
        skill_dir = create_dir / "tiny"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("# tiny\n", encoding="utf-8")
        return _fake_proc(returncode=0)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    extractor = SkillExtractor(body_min_tokens=50, body_max_tokens=2000)
    skill = asyncio.run(
        extractor.extract(
            task="t", knowledge="k", intent_hash=1, sandbox_root=tmp_path
        )
    )
    assert skill is None


def test_extract_rejects_oversized_body(tmp_path: Path, monkeypatch):
    big = " ".join(["token"] * 3000)

    async def fake_to_thread(fn, *args, **kwargs):
        sandbox = Path(kwargs["cwd"])
        create_dir = sandbox / "create"
        skill_dir = create_dir / "huge"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(big, encoding="utf-8")
        return _fake_proc(returncode=0)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    extractor = SkillExtractor(body_min_tokens=50, body_max_tokens=2000)
    skill = asyncio.run(
        extractor.extract(
            task="t", knowledge="k", intent_hash=1, sandbox_root=tmp_path
        )
    )
    assert skill is None


def test_extract_rejects_bad_name_length(tmp_path: Path, monkeypatch):
    async def fake_to_thread(fn, *args, **kwargs):
        sandbox = Path(kwargs["cwd"])
        create_dir = sandbox / "create"
        skill_dir = create_dir / "this-has-way-too-many-words-in-the-name"
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            "# a\n" + " ".join(["b"] * 200), encoding="utf-8"
        )
        return _fake_proc(returncode=0)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    extractor = SkillExtractor(
        name_min_words=1, name_max_words=4, body_min_tokens=10, body_max_tokens=5000
    )
    skill = asyncio.run(
        extractor.extract(
            task="t", knowledge="k", intent_hash=1, sandbox_root=tmp_path
        )
    )
    assert skill is None


def test_extract_returns_none_on_subprocess_failure(tmp_path: Path, monkeypatch):
    async def fake_to_thread(fn, *args, **kwargs):
        return _fake_proc(returncode=2, stderr="claude crashed")

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    extractor = SkillExtractor()
    skill = asyncio.run(
        extractor.extract(
            task="t", knowledge="k", intent_hash=1, sandbox_root=tmp_path
        )
    )
    assert skill is None


def test_extract_returns_none_on_timeout(tmp_path: Path, monkeypatch):
    import subprocess

    async def fake_to_thread(fn, *args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["claude"], timeout=10)

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    extractor = SkillExtractor()
    skill = asyncio.run(
        extractor.extract(
            task="t", knowledge="k", intent_hash=1, sandbox_root=tmp_path
        )
    )
    assert skill is None


def test_extract_returns_none_on_missing_claude_cli(tmp_path: Path, monkeypatch):
    async def fake_to_thread(fn, *args, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    extractor = SkillExtractor()
    skill = asyncio.run(
        extractor.extract(
            task="t", knowledge="k", intent_hash=1, sandbox_root=tmp_path
        )
    )
    assert skill is None
