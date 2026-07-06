"""Phase 10 Bug 2: calls_log.jsonl must persist L1 sim per ranked skill.

The container-side PreToolUse hook (skillq/runtime/hook.py) writes a
JSONL line to ``$SKILLQ_CALLS_LOG_PATH`` for every Skill() invocation.
The line shape is documented in
``tests/test_hook_calls_log_l1_sim.py``. This file pins the new
``l1_sims`` field added in Phase 10 Bug 2: post-gate retrieval
similarities keyed by skill_id, distinct from
``q_updates.jsonl:cosine_sim`` (the post-trial query↔trajectory sim
used for Eq.5 Q-update delta scaling).

Naming rationale (L1 sim vs Q-update sim):
  - L1 sim = cosine(query, skill.description) computed during L1
    retrieval, post-Hard-Gate, pre-scoring-formula. Returned in
    ScoredSkill.sim by /rank.
  - Q-update sim = cosine(intent_text, skill.description) computed
    once per trial AFTER the agent runs, used to weight the Eq.5
    Q-update delta. Persisted in q_updates.jsonl.
  - Same name "cosine sim" but different stage / different query /
  different formula / different purpose. Distinct field names
  (``l1_sims`` vs ``cosine_sim``) prevent confusion in audit
  scripts.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.shared.calls_log import (  # noqa: E402
    SubTaskCallRecord,
    read_skill_calls_log,
)


@pytest.fixture
def hook_module_fixture(monkeypatch, tmp_path: Path):
    """Import the container hook with controlled env vars.

    The container hook reads env vars at module-load time
    (RANK_ENDPOINT, TOP_K, etc.) so we patch the env BEFORE the
    import. We point CALLS_LOG_PATH to a tmp_path file so we can
    inspect the JSONL output.
    """
    log_path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("SKILLQ_RANK_ENDPOINT", "http://host:8765")
    monkeypatch.setenv("SKILLQ_CALLS_LOG_PATH", str(log_path))
    monkeypatch.setenv("SKILLQ_HOOK_TOP_K", "3")
    monkeypatch.setenv("SKILLQ_HOOK_LAMBDA", "0.5")
    monkeypatch.setenv("SKILLQ_HOOK_C_UCB", "0.5")
    monkeypatch.setenv("SKILLQ_HOOK_SCORE_MODE", "multiplicative")
    monkeypatch.setenv("SKILLQ_HOOK_MULT_BETA", "0.5")
    monkeypatch.setenv("SKILLQ_HOOK_MULT_GAMMA", "0.2")
    monkeypatch.setenv("SKILLQ_SIM_GATE_MIN_SCORE", "0.0")  # gate off
    monkeypatch.setenv("SKILLQ_SIM_GATE_FLOOR", "0")
    # Drop q_clip knobs (Phase 10 Bug 1: no longer seeded).
    monkeypatch.delenv("SKILLQ_HOOK_Q_CLIP_MIN", raising=False)
    monkeypatch.delenv("SKILLQ_HOOK_Q_CLIP_MAX", raising=False)

    sys.modules.pop("skillq.runtime.hook", None)
    import skillq.runtime.hook as hook_mod

    return {"hook_mod": hook_mod, "log_path": log_path}


def _payload_from_responses(fixture, responses: list[dict]) -> list[dict]:
    """Patch _call_rank to return canned responses, then read back calls_log.

    Each response in ``responses`` is the body returned by /rank for
    one Skill() invocation. The function invokes the hook's
    PreToolUse handler for each entry and returns the lines written
    to calls_log.jsonl.
    """
    hook_module = fixture["hook_mod"]
    log_path = fixture["log_path"]
    queue = list(responses)

    def fake_call_rank(query, top_k, *, timeout=None):
        if not queue:
            return -1, None, "exhausted"
        body = queue.pop(0)
        return 200, body, "ok"

    with mock.patch.object(hook_module, "_call_rank", side_effect=fake_call_rank):
        for skill_name in ["a", "b", "c"]:
            payload = {
                "tool_name": "Skill",
                "tool_input": {"skill": skill_name},
            }
            # Container hook receives the parsed JSON dict on stdin
            # (Claude Code's PreToolUse hook contract).
            hook_module._handle_pretooluse_skill(payload)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_calls_log_writes_l1_sims_dict(hook_module_fixture):
    """Each calls_log line carries ``l1_sims: {skill_id: float}``."""
    responses = [
        {
            "allowed": True,
            "reason": "ok",
            "top_k": [
                {"skill_id": "chess-image-to-move", "score": 0.85, "sim": 0.72,
                 "description": "chess"},
                {"skill_id": "fix-git-basics", "score": 0.61, "sim": 0.55,
                 "description": "git"},
            ],
            "ranking_id": "abc123",
        },
    ]
    # The first Skill() call gets the canned response; the other two
    # fall open (no responses left) so only the first call is
    # assertions-relevant. We assert on lines[0] specifically.
    lines = _payload_from_responses(hook_module_fixture, responses)
    assert len(lines) >= 1
    line = lines[0]
    assert "l1_sims" in line, "calls_log must persist L1 sims (Phase 10 Bug 2)"
    assert line["l1_sims"] == {
        "chess-image-to-move": 0.72,
        "fix-git-basics": 0.55,
    }


def test_calls_log_skips_none_sim_entries(hook_module_fixture):
    """Entries with sim=None are omitted from l1_sims (rare: embed fail)."""
    responses = [
        {
            "allowed": True,
            "reason": "ok",
            "top_k": [
                {"skill_id": "alpha", "score": 0.9, "sim": 0.81,
                 "description": "alpha"},
                # sim missing ⇒ embed unavailable for this skill
                {"skill_id": "beta", "score": 0.7, "description": "beta"},
                {"skill_id": "gamma", "score": 0.5, "sim": None,
                 "description": "gamma"},
            ],
            "ranking_id": "xyz",
        },
    ]
    lines = _payload_from_responses(hook_module_fixture, responses)
    # First call gets the canned response; remaining 2 fall open.
    assert len(lines) >= 1
    # Only alpha has a real sim; beta (missing) and gamma (None) omitted.
    assert lines[0]["l1_sims"] == {"alpha": 0.81}


def test_calls_log_empty_top_k_yields_empty_l1_sims(hook_module_fixture):
    """Hard Gate strict-mode returns top_k=[]; l1_sims is then {}."""
    responses = [
        {
            "allowed": False,
            "reason": "no_relevant_skills",
            "top_k": [],
            "ranking_id": "q",
        },
    ]
    lines = _payload_from_responses(hook_module_fixture, responses)
    assert len(lines) >= 1
    assert lines[0]["l1_sims"] == {}


def test_calls_log_does_not_break_old_fields(hook_module_fixture):
    """Backward compat: the new l1_sims field is additive.

    Old audit scripts reading ranking_id / requested / approved
    must continue to work. This test pins that the additive field
    does not break the existing JSONL line shape.
    """
    responses = [
        {
            "allowed": True,
            "reason": "ok",
            "top_k": [
                {"skill_id": "a", "score": 0.5, "sim": 0.42, "description": "a"},
            ],
            "ranking_id": "rid-1",
        },
    ]
    lines = _payload_from_responses(hook_module_fixture, responses)
    line = lines[0]
    # Old fields still present
    assert line["ranking_id"] == "rid-1"
    assert line["approved"] is True
    assert line["denied"] is False
    assert line["requested"] == "a"  # first fake-call used "a"
    # New field present
    assert line["l1_sims"] == {"a": 0.42}
    # Sanity: at least one log line was written
    assert len(lines) >= 1


# ---------------------------------------------------------------------------
# Phase 10 Debug-Log: pre-gate top-5 sim snapshot
# ---------------------------------------------------------------------------
def test_calls_log_persists_pre_gate_top5(hook_module_fixture):
    """calls_log carries l1_sims_top5_pre_gate from response debug field.

    The host's /rank handler always returns debug.pre_gate_top5 with
    the top-5 highest-sim candidates *before* Hard Gate filtering.
    The hook must transcribe it to calls_log so an audit can answer
    "did L1 see 0.05 sims (off-topic query) or 0.65 sims (gate too
    strict)?" even when top_k=[] and l1_sims={} after the gate.
    """
    responses = [
        {
            "allowed": True,
            "reason": "ok",
            "top_k": [
                {"skill_id": "winner", "score": 0.9, "sim": 0.81,
                 "description": "winner"},
            ],
            "ranking_id": "rid-debug-1",
            "debug": {
                "pre_gate_top5": [
                    {"skill_id": "winner", "sim": 0.81},
                    {"skill_id": "runner_up", "sim": 0.65},
                    {"skill_id": "third", "sim": 0.42},
                ],
            },
        },
    ]
    lines = _payload_from_responses(hook_module_fixture, responses)
    line = lines[0]
    assert "l1_sims_top5_pre_gate" in line, (
        "calls_log must persist l1_sims_top5_pre_gate (Phase 10 Debug-Log)"
    )
    assert line["l1_sims_top5_pre_gate"] == [
        {"skill_id": "winner", "sim": 0.81},
        {"skill_id": "runner_up", "sim": 0.65},
        {"skill_id": "third", "sim": 0.42},
    ]


def test_calls_log_pre_gate_top5_survives_gate_drop(hook_module_fixture):
    """When Hard Gate drops everything (top_k=[]), pre-gate snapshot
    still surfaces the highest pre-gate sims so we can audit the
    gate's decision boundary.
    """
    responses = [
        {
            "allowed": False,
            "reason": "no_relevant_skills",
            "top_k": [],
            "ranking_id": "rid-gate",
            "debug": {
                "pre_gate_top5": [
                    # All under sim_gate_min_score=0.7 — would be dropped
                    {"skill_id": "a", "sim": 0.65},
                    {"skill_id": "b", "sim": 0.42},
                    {"skill_id": "c", "sim": 0.31},
                    {"skill_id": "d", "sim": 0.05},
                    {"skill_id": "e", "sim": 0.01},
                ],
            },
        },
    ]
    lines = _payload_from_responses(hook_module_fixture, responses)
    line = lines[0]
    # post-gate l1_sims is empty (top_k=[]), but pre-gate still shows
    # that the best L1 sim was 0.65 — gate threshold is the issue,
    # not the embedding.
    assert line["l1_sims"] == {}
    assert line["l1_sims_top5_pre_gate"][0]["sim"] == 0.65


def test_calls_log_pre_gate_top5_defaults_empty(hook_module_fixture):
    """If /rank response omits the debug field (legacy callers), the
    calls_log entry must default to an empty list, not KeyError.
    """
    responses = [
        {
            "allowed": True,
            "reason": "ok",
            "top_k": [
                {"skill_id": "x", "score": 0.5, "sim": 0.4, "description": "x"},
            ],
            "ranking_id": "rid-no-debug",
            # no "debug" key
        },
    ]
    lines = _payload_from_responses(hook_module_fixture, responses)
    line = lines[0]
    assert line["l1_sims_top5_pre_gate"] == []


# ---------------------------------------------------------------------------
# Reader side: read_skill_calls_log must surface the new fields
#
# The writer half is pinned by the test_calls_log_* tests above. The
# bug fixed on 2026-06-30 was that the JSONL had the fields but the
# SubTaskCallRecord dataclass + reader dropped them, so e2e consumers
# (L3 attribution, analysis scripts) saw empty / missing data even
# though the data was on disk. These tests pin the reader half.
# ---------------------------------------------------------------------------
def test_subtask_call_record_has_l1_sims_defaults():
    """The dataclass exposes `l1_sims` and `l1_sims_top5_pre_gate`
    with empty defaults so legacy code that constructs a record
    without the new fields keeps working.
    """
    rec = SubTaskCallRecord(
        skill_id="x",
        requested="x",
        top_k=[],
        approved=True,
        ts=0.0,
        intent_text="",
    )
    assert rec.l1_sims == {}
    assert rec.l1_sims_top5_pre_gate == []


def test_read_skill_calls_log_exposes_l1_sims(tmp_path: Path):
    """Modern hook log (Phase 10 Bug 2) carries l1_sims and the
    reader populates SubTaskCallRecord.l1_sims from it.
    """
    log = tmp_path / "skillq_skill_calls.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({
        "ts": 1.0,
        "requested": "skill-a",
        "top_k": [],
        "approved": True,
        "denied": False,
        "intent_text": "",
        "l1_sims": {"skill-a": 0.81, "skill-b": 0.55},
    }) + "\n")
    records = read_skill_calls_log(log)
    assert len(records) == 1
    assert records[0].l1_sims == {"skill-a": 0.81, "skill-b": 0.55}


def test_read_skill_calls_log_exposes_pre_gate_top5(tmp_path: Path):
    """Modern hook log (Phase 10 Debug-Log) carries
    l1_sims_top5_pre_gate and the reader surfaces it on the record.
    """
    log = tmp_path / "skillq_skill_calls.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({
        "ts": 2.0,
        "requested": "skill-a",
        "top_k": [],
        "approved": False,
        "denied": True,
        "intent_text": "",
        "l1_sims": {},
        "l1_sims_top5_pre_gate": [
            {"skill_id": "a", "sim": 0.65},
            {"skill_id": "b", "sim": 0.42},
            {"skill_id": "c", "sim": 0.31},
        ],
    }) + "\n")
    records = read_skill_calls_log(log)
    assert len(records) == 1
    rec = records[0]
    # The bug: this assertion would fail (always [] / not on disk)
    # because the reader dropped the field.
    assert rec.l1_sims_top5_pre_gate == [
        {"skill_id": "a", "sim": 0.65},
        {"skill_id": "b", "sim": 0.42},
        {"skill_id": "c", "sim": 0.31},
    ]
    # And l1_sims must be {} (not KeyError) when the gate drops all.
    assert rec.l1_sims == {}


def test_read_skill_calls_log_back_compat_missing_new_fields(tmp_path: Path):
    """Old hook logs (pre-Phase 10) have neither l1_sims nor
    l1_sims_top5_pre_gate. The reader must yield empty defaults,
    not raise.
    """
    log = tmp_path / "skillq_skill_calls.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(
        json.dumps({
            "ts": 1.0,
            "requested": "old-approved",
            "top_k": [],
            "approved": True,
            "denied": False,
            "intent_text": "",
        }) + "\n" +
        json.dumps({
            "ts": 2.0,
            "requested": "old-denied",
            "top_k": [],
            "approved": False,
            "denied": True,
            "intent_text": "",
        }) + "\n"
    )
    records = read_skill_calls_log(log)
    assert len(records) == 2
    assert records[0].l1_sims == {}
    assert records[0].l1_sims_top5_pre_gate == []
    assert records[1].l1_sims == {}
    assert records[1].l1_sims_top5_pre_gate == []


def test_read_skill_calls_log_ignores_malformed_new_fields(tmp_path: Path):
    """Defensive: a corrupted `l1_sims` (non-dict) or
    `l1_sims_top5_pre_gate` (non-list) yields empty defaults rather
    than raising — the rest of the record is still recovered.
    """
    log = tmp_path / "skillq_skill_calls.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({
        "ts": 1.0,
        "requested": "skill-a",
        "top_k": [],
        "approved": True,
        "denied": False,
        "intent_text": "",
        "l1_sims": "not-a-dict",
        "l1_sims_top5_pre_gate": {"oops": "wrong-type"},
    }) + "\n")
    records = read_skill_calls_log(log)
    assert len(records) == 1
    assert records[0].l1_sims == {}
    assert records[0].l1_sims_top5_pre_gate == []
