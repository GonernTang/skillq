"""Tests for ``paper/method/extractor.py`` SkillExtractor.

The extractor is a ``claude --print`` subprocess wrapper, so the tests
stub the subprocess at the ``asyncio.to_thread`` boundary. We don't
spawn a real Claude CLI in unit tests.

Note: the bridge only ever calls :meth:`SkillExtractor.extract_batch`
(the per-trial ``extract()`` method was removed in the cleanup —
per-trial prompts produced too task-specific skills). The tests
below wrap a single trial into a one-element list and call
``extract_batch``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.layers.l4_evolve.create import SkillExtractor  # noqa: E402


def _fake_proc(*, returncode: int = 0, stdout: str = "", stderr: str = ""):
    proc = type("P", (), {})()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


async def _call_extractor_batch(
    extractor: SkillExtractor,
    *,
    task: str,
    knowledge: str,
    intent_hash: int,
    sandbox_root: Path,
    available_skill_names: list[str] | None = None,
):
    """Wrap the (task, knowledge) record into the one-trial list
    shape :meth:`SkillExtractor.extract_batch` expects."""
    return await extractor.extract_batch(
        trials=[
            {
                "task": task,
                "knowledge": knowledge,
                "intent_hash": intent_hash,
            }
        ],
        available_skill_names=available_skill_names,
        sandbox_root=sandbox_root,
        aggregated_intent_hash=intent_hash,
    )


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
        _call_extractor_batch(
            extractor,
            task="parse fixed-width COBOL records",
            knowledge="Use awk to slice bytes 1-6 of each line.",
            intent_hash=0xDEADBEEF,
            sandbox_root=tmp_path,
        )
    )

    assert skill is not None
    assert skill.skill_id == "parse-cobol"
    assert "awk" in skill.body
    assert skill.metadata["source"] == "skillq_extract"
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
        _call_extractor_batch(
            extractor,
            task="t",
            knowledge="k",
            intent_hash=1,
            sandbox_root=tmp_path,
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
        _call_extractor_batch(
            extractor,
            task="t",
            knowledge="k",
            intent_hash=1,
            sandbox_root=tmp_path,
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
        _call_extractor_batch(
            extractor,
            task="t",
            knowledge="k",
            intent_hash=1,
            sandbox_root=tmp_path,
        )
    )
    assert skill is None


def test_extract_returns_none_on_subprocess_failure(tmp_path: Path, monkeypatch):
    async def fake_to_thread(fn, *args, **kwargs):
        return _fake_proc(returncode=2, stderr="claude crashed")

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    extractor = SkillExtractor()
    skill = asyncio.run(
        _call_extractor_batch(
            extractor,
            task="t",
            knowledge="k",
            intent_hash=1,
            sandbox_root=tmp_path,
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
        _call_extractor_batch(
            extractor,
            task="t",
            knowledge="k",
            intent_hash=1,
            sandbox_root=tmp_path,
        )
    )
    assert skill is None


def test_extract_returns_none_on_missing_claude_cli(tmp_path: Path, monkeypatch):
    async def fake_to_thread(fn, *args, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr("asyncio.to_thread", fake_to_thread)
    extractor = SkillExtractor()
    skill = asyncio.run(
        _call_extractor_batch(
            extractor,
            task="t",
            knowledge="k",
            intent_hash=1,
            sandbox_root=tmp_path,
        )
    )
    assert skill is None


def test_make_sandbox_unique_per_call(tmp_path: Path) -> None:
    """Each ``_make_sandbox`` call produces a distinct path even with
    the same ``root``. The 2026-06-22 bug was a deterministic name
    that collided across concurrent ``extract_batch`` calls when
    ``n_concurrent_trials >= 2`` — the first call's rmtree deleted
    the cwd of the second call's still-running ``claude --print``.
    """
    import shutil

    extractor = SkillExtractor()
    s1 = extractor._make_sandbox(tmp_path)
    s2 = extractor._make_sandbox(tmp_path)
    assert s1 != s2, (
        f"sandbox names must differ per call, got {s1} == {s2} — race fix regressed"
    )
    assert s1.is_dir()
    assert s2.is_dir()
    # create/ subdir exists (the LLM writes into it)
    assert (s1 / "create").is_dir()
    assert (s2 / "create").is_dir()
    # Both paths should live under the requested root.
    assert s1.is_relative_to(tmp_path)
    assert s2.is_relative_to(tmp_path)
    shutil.rmtree(s1)
    shutil.rmtree(s2)


def test_make_sandbox_unique_under_concurrent_calls(tmp_path: Path) -> None:
    """Two ``_make_sandbox`` calls back-to-back (mimicking concurrent
    ``on_ended`` callbacks) never yield the same path. This is the
    direct regression test for the race that triggered the
    ``cwd was deleted`` error in the 5-task smoke.
    """
    import shutil

    extractor = SkillExtractor()
    paths = {extractor._make_sandbox(tmp_path) for _ in range(10)}
    assert len(paths) == 10, f"expected 10 unique sandboxes, got {len(paths)}"
    # Clean up.
    for p in paths:
        shutil.rmtree(p)
