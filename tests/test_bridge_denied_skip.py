"""Tests for the strict-gate Q-pollution fix (2026-06-25).

The hook can return ``permissionDecision: "deny"`` when no skill in
the library is above the sim gate (default 0.7). In that case the
agent solves the sub-task directly without using any skill.

Before this fix, the bridge unconditionally read
``skillq_skill_calls.jsonl`` and updated the Q-table for **every**
recorded call — including denied ones. The user's strict-gate design
intent is:

    "严格禁止和当前任务不相关的技能污染agent上下文和污染q值演化逻辑"

Concretely: a denied call must not produce any of these side-effects:
  - n_retrievals += 1 (feeds UCB decay)
  - n_uses += 1      (success counter)
  - Q(skill) += α·(r_task − Q(skill))   (Eq.5)
  - cosine-weighted delta
  - q_updates.jsonl trace entry

These tests cover:
  1. SubTaskCallRecord has the denied field
  2. read_skill_calls_log parses the new denied flag
  3. read_skill_calls_log falls back to ¬approved for old JSONL
     files written before the field existed
  4. extract_skill_calls_from_session sets denied=False (agentic
     mode has no hook → nothing to deny)
  5. End-to-end: a trial whose hook log records denied=True for
     every call leaves the Q-table at the seed value
  6. End-to-end: a trial with mixed approved + denied calls only
     Q-updates the approved ones (denied is silently dropped, but
     no error is raised)
  7. End-to-end: a trial with all approved calls Q-updates
     normally (sanity / regression guard)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.layers.l3_attribution.models import Attribution, TrialAttribution  # noqa: E402
from skillq.shared.q_table import LibManager  # noqa: E402
from skillq.shared.library import QlibState  # noqa: E402
from skillq.shared.types import Qlib, Skill  # noqa: E402
from skillq.runtime import bridge as bridge_mod  # noqa: E402
from skillq.shared.calls_log import (  # noqa: E402
    SubTaskCallRecord,
    extract_skill_calls_from_session,
    read_skill_calls_log,
)
from skillq.config import MethodConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _write_hook_log(trial_dir: Path, *records: dict[str, Any]) -> Path:
    """Write a hook-format ``skillq_skill_calls.jsonl`` under
    ``<trial_dir>/agent/sessions/``. Returns the log path."""
    sessions_dir = trial_dir / "agent" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    p = sessions_dir / "skillq_skill_calls.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return p


def _make_hook_record(
    requested: str,
    *,
    approved: bool = True,
    denied: bool | None = None,
    top_k: list[dict] | None = None,
) -> dict[str, Any]:
    """Build a single hook log record. If ``denied`` is None, derives
    it from ``approved`` (mimicking the hook's own behaviour)."""
    return {
        "ts": 1.0,
        "requested": requested,
        "top_k": top_k or [{"skill_id": requested, "score": 0.8}],
        "approved": approved,
        "denied": (not approved) if denied is None else denied,
        "embed_ms": 12.3,
        "intent_text": "fix the bug",
    }


class _MockJob:
    def __init__(self) -> None:
        self.on_ended: Any = None
        self.config = MagicMock()
        self.config.retry = MagicMock()
        self.config.retry.exclude_exceptions = None
        self.config.retry.include_exceptions = None

    def on_trial_ended(self, callback: Any) -> None:
        self.on_ended = callback

    def on_trial_started(self, callback: Any) -> None:
        self.on_started = callback  # Step 7: new pipeline needs both

    def __len__(self) -> int:
        return 1_000_000


def _patch_litellm_backends(monkeypatch) -> None:
    from skillq.layers.l3_attribution.models import StubAttributionBackend
    from skillq.shared.backends.litellm import StubEmbedder

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


def _seed_lib(method: MethodConfig, skill_ids: list[str]) -> None:
    lib = Qlib(b_max=method.b_max)
    for sid in skill_ids:
        lib.add(Skill(skill_id=sid, body=f"body {sid}"))
    state = QlibState(method.resolved_state_path())
    state.save(
        lib,
        LibManager(b_max=method.b_max),
        lib_root=method.library_root,
        seed_initial_q=method.seed_initial_q,
    )


# ---------------------------------------------------------------------------
# Unit tests — SubTaskCallRecord + read_skill_calls_log
# ---------------------------------------------------------------------------
def test_subtask_call_record_has_denied_field():
    """Sanity: the dataclass exposes a `denied` field (defaults False)."""
    rec = SubTaskCallRecord(
        skill_id="x",
        requested="x",
        top_k=[],
        approved=True,
        ts=0.0,
        intent_text="",
    )
    assert rec.denied is False
    rec2 = SubTaskCallRecord(
        skill_id="y",
        requested="y",
        top_k=[],
        approved=False,
        denied=True,
        ts=0.0,
        intent_text="",
    )
    assert rec2.denied is True


def test_read_skill_calls_log_parses_denied_flag(tmp_path: Path):
    """Modern hook log (has `denied` field) is parsed faithfully."""
    log = _write_hook_log(
        tmp_path,
        _make_hook_record("skill-a", approved=True, denied=False),
        _make_hook_record("skill-b", approved=False, denied=True),
    )
    records = read_skill_calls_log(log)
    assert len(records) == 2
    assert records[0].skill_id == "skill-a"
    assert records[0].approved is True
    assert records[0].denied is False
    assert records[1].skill_id == "skill-b"
    assert records[1].approved is False
    assert records[1].denied is True


def test_read_skill_calls_log_back_compat_no_denied_field(tmp_path: Path):
    """Old hook logs (pre-2026-06-25) didn't write `denied`.
    The reader derives it from ¬approved so the bridge can still
    distinguish approved vs denied for old trial data."""
    p = tmp_path / "skillq_skill_calls.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({
            "ts": 1.0,
            "requested": "old-approved",
            "top_k": [],
            "approved": True,
            # NOTE: no "denied" key
            "embed_ms": 1.0,
            "intent_text": "",
        }) + "\n" +
        json.dumps({
            "ts": 2.0,
            "requested": "old-denied",
            "top_k": [],
            "approved": False,
            # NOTE: no "denied" key
            "embed_ms": 1.0,
            "intent_text": "",
        }) + "\n"
    )
    records = read_skill_calls_log(p)
    assert len(records) == 2
    # Approved→ denied=False (back-compat default)
    assert records[0].approved is True
    assert records[0].denied is False
    # Denied → denied=True (back-compat default)
    assert records[1].approved is False
    assert records[1].denied is True


def test_extract_skill_calls_from_session_marks_all_approved(tmp_path: Path):
    """Agentic-mode fallback: no hook fired, every Skill() in the
    session log is implicitly approved (agent successfully called it).
    denied must default to False so the bridge still Q-updates."""
    # No hook log, no session log → empty list.
    assert extract_skill_calls_from_session(tmp_path) == []

    # Write a session log with one Skill tool_use.
    proj = tmp_path / "agent" / "sessions" / "projects" / "proj-1"
    proj.mkdir(parents=True)
    (proj / "session-x.jsonl").write_text(
        json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Skill",
                 "input": {"skill": "chess-image-to-move"}, "id": "t1"}
            ]},
        }) + "\n"
    )
    records = extract_skill_calls_from_session(tmp_path)
    assert len(records) == 1
    assert records[0].skill_id == "chess-image-to-move"
    assert records[0].approved is True
    assert records[0].denied is False


# ---------------------------------------------------------------------------
# End-to-end: bridge._q_update skips denied records
# ---------------------------------------------------------------------------
def test_bridge_skips_q_update_when_all_calls_denied(
    tmp_path: Path, monkeypatch
):
    """The smoking-gun test for the user's complaint:

        smoke → agent Skill("chess-image-to-move") → hook DENIED →
        agent solved → chess-image-to-move Q went 0.5 → 0.6174

    After the fix, denied calls must NOT Q-update. The Q-table
    stays at the seed value (0.5), n_retrievals stays 0, and
    q_updates.jsonl is NOT written.
    """
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
        seed_initial_q=0.5,
    )
    _seed_lib(method, ["chess-image-to-move"])

    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-denied"
    trial_dir.mkdir()
    # Hook returned permissionDecision: "deny" for the chess call.
    _write_hook_log(
        trial_dir,
        _make_hook_record(
            "chess-image-to-move",
            approved=False,
            denied=True,
            top_k=[],   # no top_k: hard gate found no survivors
        ),
    )

    # Successful trial — the agent solved directly despite denial.
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-denied", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_table = dict(state["q_table"])
    skill = state["library"]["skills"]["chess-image-to-move"]

    # Q stays at seed (0.5) — the user's complaint fix.
    assert abs(q_table["chess-image-to-move"] - 0.5) < 1e-9, (
        f"denied call must not Q-update; q={q_table['chess-image-to-move']}"
    )
    # n_retrievals stays 0 — UCB decay must not kick in for denied calls.
    assert skill["n_retrievals"] == 0, (
        f"denied call must not increment n_retrievals; "
        f"got {skill['n_retrievals']}"
    )
    # n_uses stays 0 — agent never actually used the skill.
    assert skill["n_uses"] == 0
    # n_success stays 0 — counted per-use, not per-trial.
    assert skill["n_success"] == 0

    # No q_updates.jsonl entry for the denied call.
    trace = trial_dir / "skillq_state" / "q_updates.jsonl"
    if trace.exists():
        entries = [
            json.loads(line) for line in trace.read_text().splitlines()
            if line.strip()
        ]
        for e in entries:
            assert e.get("skill") != "chess-image-to-move", (
                f"denied call must not appear in q_updates trace: {e}"
            )


def test_bridge_only_updates_approved_when_mixed(tmp_path: Path, monkeypatch):
    """Mixed log: 1 approved + 1 denied. Only the approved skill's Q
    moves; the denied skill stays at seed."""
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

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
        q_alpha=0.3,
    )
    _seed_lib(method, ["approved-skill", "denied-skill"])

    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-mixed"
    trial_dir.mkdir()
    _write_hook_log(
        trial_dir,
        _make_hook_record("approved-skill", approved=True, denied=False),
        _make_hook_record("denied-skill", approved=False, denied=True),
    )

    # Successful trial.
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-mixed", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_table = dict(state["q_table"])
    approved_skill = state["library"]["skills"]["approved-skill"]
    denied_skill = state["library"]["skills"]["denied-skill"]

    # approved-skill: Eq.5 fires → 0.5 + 0.3*(1-0.5) = 0.65.
    assert abs(q_table["approved-skill"] - 0.65) < 1e-9, q_table
    assert approved_skill["n_retrievals"] == 1
    assert approved_skill["n_uses"] == 1
    assert approved_skill["n_success"] == 1

    # denied-skill: nothing changed.
    assert q_table["denied-skill"] == pytest_approx(0.5)
    assert denied_skill["n_retrievals"] == 0
    assert denied_skill["n_uses"] == 0
    assert denied_skill["n_success"] == 0


def test_bridge_q_updates_normally_when_all_approved(
    tmp_path: Path, monkeypatch
):
    """Regression guard: when no calls are denied, the bridge behaves
    exactly as before — Eq.5 fires for every recorded skill."""
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

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
        q_alpha=0.3,
    )
    _seed_lib(method, ["git-basics", "lint-fix"])

    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-all-approved"
    trial_dir.mkdir()
    _write_hook_log(
        trial_dir,
        _make_hook_record("git-basics", approved=True, denied=False),
        _make_hook_record("lint-fix", approved=True, denied=False),
    )

    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-all-approved", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_table = dict(state["q_table"])
    # Both skills: 0.5 + 0.3*(1-0.5) = 0.65.
    assert abs(q_table["git-basics"] - 0.65) < 1e-9
    assert abs(q_table["lint-fix"] - 0.65) < 1e-9


def test_bridge_skips_denied_even_when_trial_failed(
    tmp_path: Path, monkeypatch
):
    """Failed trial + denied call → still no Q-update. This protects
    the orthogonal-skill invariant: an irrelevant skill must not be
    punished for a failure that has nothing to do with it (the hook
    denied precisely because no skill was relevant)."""
    _patch_litellm_backends(monkeypatch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            # Trial failed, but the skill was denied by the hook (never
            # used). Use FAILURE_SKILL_NOT_USED — the failure is
            # "no relevant skill was used", not "skill is at fault",
            # since the skill never executed. (Renamed 2026-06-26
            # from the old FAIL_AGENT_ISSUE.)
            overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
            overall_rationale="test",
            knowledge_to_extract="",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
    )
    _seed_lib(method, ["irrelevant"])

    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-fail-denied"
    trial_dir.mkdir()
    _write_hook_log(
        trial_dir,
        _make_hook_record("irrelevant", approved=False, denied=True),
    )

    # Failed trial.
    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-fail-denied", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_table = dict(state["q_table"])
    skill = state["library"]["skills"]["irrelevant"]
    # Q stays at 0.5. Without the fix it would have gone to 0.35
    # (Eq.5 with r_task=0).
    assert abs(q_table["irrelevant"] - 0.5) < 1e-9, q_table
    assert skill["n_retrievals"] == 0
    assert skill["n_uses"] == 0


# ---------------------------------------------------------------------------
# Small helper for "approximately equal" without importing pytest
# ---------------------------------------------------------------------------
def pytest_approx(value: float) -> "_Approx":
    """A tiny stand-in for pytest.approx so the assertion in
    test_bridge_only_updates_approved_when_mixed reads naturally."""
    return _Approx(value)


class _Approx:
    def __init__(self, value: float, tol: float = 1e-9) -> None:
        self.value = value
        self.tol = tol

    def __eq__(self, other: object) -> bool:
        return abs(float(other) - self.value) <= self.tol