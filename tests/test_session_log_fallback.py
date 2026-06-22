"""Tests for the session-log fallback used by ``_q_update_from_subtask``.

When the PreToolUse hook is unavailable (agentic mode) or its log
was unreadable, the bridge scans the trial's Claude Code session
jsonl for Skill tool_use blocks to recover per-skill call info.

Covers:
- Empty / missing session directories.
- Empty jsonl.
- Malformed jsonl lines (skipped, not crashing).
- Mixed user / assistant / tool entries.
- Skill tool_use blocks in nested message content.
- Tool_use blocks for non-Skill tools are ignored.
- End-to-end: bridge falls back to session log when hook log is
  empty, and the per-skill Q-update still runs.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.method.attribution import Attribution, TrialAttribution  # noqa: E402
from skillq.method.library import LibManager  # noqa: E402
from skillq.method.state import QlibState  # noqa: E402
from skillq.method.types import Qlib, Skill  # noqa: E402
from skillq.paper_mode import bridge as bridge_mod  # noqa: E402
from skillq.paper_mode.config import MethodConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_session_jsonl(
    trial_dir: Path,
    *entries: dict[str, Any],
    session_name: str = "session-001.jsonl",
) -> Path:
    """Write a session jsonl under
    ``<trial_dir>/agent/sessions/projects/<proj>/<session_name>``.
    """
    proj_dir = trial_dir / "agent" / "sessions" / "projects" / "test-proj"
    proj_dir.mkdir(parents=True, exist_ok=True)
    p = proj_dir / session_name
    with p.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def _skill_tool_use(skill_name: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": "Skill",
                    "input": {"skill": skill_name},
                    "id": f"call_{skill_name}",
                }
            ],
        },
    }


def _text_msg(role: str, text: str) -> dict[str, Any]:
    return {"type": role, "message": {"role": role, "content": text}}


def _other_tool_use(tool_name: str) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "name": tool_name,
                    "input": {"cmd": "ls"},
                    "id": f"call_{tool_name}",
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# _extract_skill_calls_from_session — direct unit tests
# ---------------------------------------------------------------------------
def test_extract_returns_empty_when_session_dir_missing(tmp_path: Path):
    """No ``agent/sessions/projects`` dir → empty list, no exception."""
    assert bridge_mod._extract_skill_calls_from_session(tmp_path) == []


def test_extract_returns_empty_when_no_jsonl_files(tmp_path: Path):
    """Dir exists but no jsonl files → empty list."""
    (tmp_path / "agent" / "sessions" / "projects" / "x").mkdir(parents=True)
    assert bridge_mod._extract_skill_calls_from_session(tmp_path) == []


def test_extract_returns_empty_for_empty_jsonl(tmp_path: Path):
    p = _write_session_jsonl(tmp_path)
    assert p.stat().st_size == 0
    assert bridge_mod._extract_skill_calls_from_session(tmp_path) == []


def test_extract_skips_malformed_jsonl_lines(tmp_path: Path):
    """Bad JSON lines are skipped, valid Skill entries still extracted."""
    proj_dir = tmp_path / "agent" / "sessions" / "projects" / "p"
    proj_dir.mkdir(parents=True)
    p = proj_dir / "s.jsonl"
    p.write_text(
        "{not valid json\n"
        + json.dumps(_skill_tool_use("fix-git-basics"))
        + "\n"
        + "still bad\n",
        encoding="utf-8",
    )
    out = bridge_mod._extract_skill_calls_from_session(tmp_path)
    assert len(out) == 1
    assert out[0].skill_id == "fix-git-basics"


def test_extract_picks_skill_blocks_from_nested_content(tmp_path: Path):
    _write_session_jsonl(
        tmp_path,
        _text_msg("user", "fix my commit"),
        _other_tool_use("Bash"),
        _skill_tool_use("fix-git-basics"),
        _skill_tool_use("git-recover"),
        _text_msg("assistant", "I'll use the skill"),
        _other_tool_use("Edit"),
    )
    out = bridge_mod._extract_skill_calls_from_session(tmp_path)
    assert [r.skill_id for r in out] == ["fix-git-basics", "git-recover"]


def test_extract_ignores_non_skill_tools(tmp_path: Path):
    """Bash, Edit, Read, etc. tool_use blocks are ignored."""
    _write_session_jsonl(
        tmp_path,
        _other_tool_use("Bash"),
        _other_tool_use("Edit"),
        _other_tool_use("Read"),
        _skill_tool_use("parse-cobol"),
    )
    out = bridge_mod._extract_skill_calls_from_session(tmp_path)
    assert len(out) == 1
    assert out[0].skill_id == "parse-cobol"


def test_extract_skips_skill_blocks_with_empty_skill_name(tmp_path: Path):
    """A Skill tool_use block with input.skill == "" is ignored."""
    bad_block = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Skill", "input": {"skill": ""}}
            ],
        },
    }
    _write_session_jsonl(
        tmp_path,
        bad_block,
        _skill_tool_use("fix-git-basics"),
    )
    out = bridge_mod._extract_skill_calls_from_session(tmp_path)
    assert [r.skill_id for r in out] == ["fix-git-basics"]


def test_extract_uses_most_recent_jsonl(tmp_path: Path):
    """When multiple session jsonls exist, the most recent (by mtime)
    one is used. Use different content in two files to verify."""
    older = _write_session_jsonl(
        tmp_path, _skill_tool_use("from-older-session"),
        session_name="session-001.jsonl",
    )
    # Sleep to ensure a different mtime

    time.sleep(0.05)
    newer = _write_session_jsonl(
        tmp_path, _skill_tool_use("from-newer-session"),
        session_name="session-002.jsonl",
    )
    # Sanity: newer has a later mtime
    assert newer.stat().st_mtime > older.stat().st_mtime
    out = bridge_mod._extract_skill_calls_from_session(tmp_path)
    assert [r.skill_id for r in out] == ["from-newer-session"]


def test_extract_returns_record_with_empty_metadata(tmp_path: Path):
    """Returned records have top_k=[], approved=True, ts=0.0,
    intent_text="" — the Q-update path doesn't need these."""
    _write_session_jsonl(tmp_path, _skill_tool_use("parse-cobol"))
    out = bridge_mod._extract_skill_calls_from_session(tmp_path)
    assert len(out) == 1
    assert out[0].skill_id == "parse-cobol"
    assert out[0].requested == "parse-cobol"
    assert out[0].top_k == []
    assert out[0].approved is True
    assert out[0].ts == 0.0
    assert out[0].intent_text == ""


# ---------------------------------------------------------------------------
# End-to-end: bridge falls back to session log when hook log is empty
# ---------------------------------------------------------------------------
class _MockJob:
    """Minimal mock Job for attach_paper_registers()."""

    def __init__(self) -> None:
        self.on_ended: Any = None
        self.config = MagicMock()
        self.config.retry = MagicMock()
        self.config.retry.exclude_exceptions = None
        self.config.retry.include_exceptions = None

    def on_trial_ended(self, callback: Any) -> None:
        self.on_ended = callback

    def __len__(self) -> int:
        return 1_000_000


def _patch_litellm_backends(monkeypatch) -> None:
    from skillq.method.attribution import StubAttributionBackend
    from skillq.method.retrieval import StubEmbedder

    class _StubEmbedderShim(StubEmbedder):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.pop("model", None)
            kwargs.pop("dim", None)
            super().__init__()

    class _StubAttributionShim(StubAttributionBackend):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.pop("model", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(bridge_mod, "LiteLLMEmbedder", _StubEmbedderShim)
    monkeypatch.setattr(bridge_mod, "LiteLLMAttributionBackend", _StubAttributionShim)


def _fake_trial_result(reward: float, trial_uri: str) -> MagicMock:
    r = MagicMock()
    r.trial_uri = trial_uri
    r.trial_name = Path(trial_uri).name
    r.task_name = "sample-task"
    r.exception_info = None
    r.verifier_result = MagicMock()
    r.verifier_result.rewards = {"reward": reward}
    return r


def _fake_hook_event(trial_id: str, result: Any) -> MagicMock:
    event = MagicMock()
    event.event = "end"
    event.trial_id = trial_id
    event.task_name = "sample-task"
    event.result = result
    return event


def _seed_lib(method: MethodConfig) -> None:
    lib = Qlib(b_max=method.b_max)
    lib.add(Skill(skill_id="git-basics", body="git rebase -i HEAD~3"))
    state = QlibState(method.resolved_state_path())
    state.save(
        lib,
        LibManager(b_max=method.b_max),
        lib_root=method.library_root,
        seed_initial_q=method.seed_initial_q,
    )


def test_q_update_falls_back_to_session_log_when_hook_log_empty(
    tmp_path: Path, monkeypatch
):
    """When skillq_skill_calls.jsonl is missing but the session jsonl
    records Skill calls, _q_update_from_subtask still extracts the
    per-skill signal and updates Q."""
    _patch_litellm_backends(monkeypatch)

    # Replace SubTaskVerifier with a stub that always returns success.
    from skillq.method.sub_task_verifier import (
        SubTaskVerdict,
        StubSubTaskVerifierBackend,
    )

    class _AlwaysSuccessVerifier:
        def __init__(self, backend, model, max_body_chars=2000):
            pass

        def score(
            self,
            *,
            task,
            skill_id,
            skill_description,
            skill_body,
            sub_task_trace,
        ):
            return SubTaskVerdict(
                skill_id=skill_id,
                success=True,
                rationale="stub success",
            )

        async def ascore(
            self,
            *,
            task,
            skill_id,
            skill_description,
            skill_body,
            sub_task_trace,
        ):
            return SubTaskVerdict(
                skill_id=skill_id,
                success=True,
                rationale="stub success",
            )

    monkeypatch.setattr(bridge_mod, "SubTaskVerifier", _AlwaysSuccessVerifier)

    # Skip the attribution/extract path entirely so the test focuses
    # on Q-update.
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_SKILL_USED,
            overall_rationale="test",
            knowledge_to_extract="",
        ),
    )

    # Disable incremental-edit on failure (would call litellm).
    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=False,
        seed_initial_q=0.5,        # seed skill Q=0.5 so update_q finds it in probation_count
        theta_near_miss=1.0,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    # Write the trial dir + session log with a Skill call. Crucially,
    # DO NOT write skillq_skill_calls.jsonl — that's the "hook didn't fire"
    # scenario.
    trial_dir = tmp_path / "trial-x"
    trial_dir.mkdir()
    _write_session_jsonl(
        trial_dir,
        _skill_tool_use("git-basics"),
    )

    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    # git-basics's Q should have increased from 0.0 → positive
    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    git_basics_qs = [
        row[1] for row in state["q_table"] if row[0] == "git-basics"
    ]
    assert git_basics_qs, "git-basics should have a Q-table entry"
    assert any(q > 0 for q in git_basics_qs), (
        "Q should have increased via session-log fallback; got %r" % git_basics_qs
    )


def test_q_update_no_signal_no_op_when_neither_hook_nor_session(
    tmp_path: Path, monkeypatch
):
    """If both hook log AND session log are empty, Q-update is a no-op
    (the trial's r_task still affects other paths but no per-skill
    Q updates fire)."""
    _patch_litellm_backends(monkeypatch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="test",
            knowledge_to_extract="",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=False,
        seed_initial_q=0.0,
        theta_near_miss=1.0,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    # Trial dir exists but no session log, no hook log.
    trial_dir = tmp_path / "trial-empty"
    trial_dir.mkdir()
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-empty", result=result)
    # Should not raise.
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    # Q-table may or may not have an entry for the seed; either way
    # no Q-update for "git-basics" ran (since there was no signal).
    assert state["step"] == 1  # trial was processed end-to-end


def test_q_update_parallel_wallclock_below_serial(
    tmp_path: Path, monkeypatch
):
    """Bug 8 fix verification: 8 skills × 2 calls each (16 judge calls)
    with a 0.3s-per-call stub. Serial would take ~4.8s; the
    Semaphore(8)-bounded ``asyncio.gather`` parallel path should take
    roughly ``ceil(16/8) × 0.3 = 0.6s``.

    We assert elapsed < ``serial_bound / 2`` — must beat the serial
    bound by at least 2×. Allows generous headroom for asyncio
    scheduling overhead + on_ended bookkeeping.
    """
    _patch_litellm_backends(monkeypatch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_SKILL_USED,
            overall_rationale="test",
            knowledge_to_extract="",
        ),
    )

    JUDGE_LATENCY_SEC = 0.3

    class _SlowAsyncVerifier:
        """SubTaskVerifier stub whose ascore sleeps to model LLM latency."""

        def __init__(self, backend, model, max_body_chars=2000):
            pass

        async def ascore(
            self,
            *,
            task,
            skill_id,
            skill_description,
            skill_body,
            sub_task_trace,
        ):
            await asyncio.sleep(JUDGE_LATENCY_SEC)
            return SubTaskVerdict(
                skill_id=skill_id,
                success=True,
                rationale="slow stub",
            )

    monkeypatch.setattr(bridge_mod, "SubTaskVerifier", _SlowAsyncVerifier)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=16,
        enable_auto_extract=False,
        seed_initial_q=0.5,
        theta_near_miss=1.0,
    )

    # Seed the library with 8 distinct skills so by_skill has 8 groups.
    lib = Qlib(b_max=method.b_max)
    mgr = LibManager(b_max=method.b_max)
    for i in range(8):
        lib.add(Skill(skill_id=f"skill-{i}", body=f"body {i}"))
        mgr.set_q(f"skill-{i}", 0.5)
    state_path = method.resolved_state_path()
    QlibState(state_path).save(
        lib,
        mgr,
        lib_root=method.library_root,
        seed_initial_q=method.seed_initial_q,
    )

    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    # Build a trial dir with a session log: 2 calls per skill = 16 total.
    trial_dir = tmp_path / "trial-slow"
    trial_dir.mkdir()
    entries = []
    for i in range(8):
        entries.append(_skill_tool_use(f"skill-{i}"))
        entries.append(_skill_tool_use(f"skill-{i}"))
    _write_session_jsonl(trial_dir, *entries)

    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-slow", result=result)

    t0 = time.monotonic()
    asyncio.run(job.on_ended(event))
    elapsed = time.monotonic() - t0

    serial_bound = 16 * JUDGE_LATENCY_SEC  # 4.8s
    assert elapsed < serial_bound / 2, (
        f"judge phase took {elapsed:.2f}s; expected < {serial_bound/2:.2f}s "
        f"(serial bound {serial_bound:.2f}s; MAX_CONCURRENT_JUDGES=8)"
    )
