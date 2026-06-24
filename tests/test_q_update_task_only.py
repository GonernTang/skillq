"""Tests for the simplified task-only Q-update (2026-06-23).

The pre-2026-06-23 path used an LLM judge to score each Skill() call
as ``r_subtask`` ∈ {0, 1}, then blended it with ``r_task``. With the
pull-mode Top-K injection (one skill called per trial) the judge was
redundant — ``r_subtask`` almost always equalled ``r_task``, and the
LLM call was wasted compute. The bridge now does standard Eq.5:

    Q(skill) += q_alpha * (r_task - Q(skill))

with ``r_task`` ∈ {0, 1} shared by every skill called in the trial.

These tests verify:
1. ``_q_update`` reads the hook log and applies Eq.5 per skill.
2. Multi-call skills get ``n_retrievals += n_calls`` (Bug 11).
3. The session-log fallback still drives Q-updates when the hook
   log is empty (agentic mode).
4. No Q-update fires when there are zero Skill calls.
5. The delta formula is exactly ``q_alpha * (r_task - q_old)`` —
   no ``q_w_subtask``, no ``q_w_task``, no judge LLM call.
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

from skillq.method.attribution import Attribution, TrialAttribution  # noqa: E402
from skillq.method.library import LibManager  # noqa: E402
from skillq.method.state import QlibState  # noqa: E402
from skillq.method.types import Qlib, Skill  # noqa: E402
from skillq.paper_mode import bridge as bridge_mod  # noqa: E402
from skillq.paper_mode.config import MethodConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers (mirrors tests/test_session_log_fallback.py's helpers)
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
    """Stub the LLM backends so the test doesn't hit network."""
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
# Tests
# ---------------------------------------------------------------------------
def test_q_update_uses_only_r_task(tmp_path: Path, monkeypatch):
    """Two skills, both called once → both get the same Eq.5 delta.

    delta = q_alpha * (r_task - q_old) = 0.3 * (1 - 0.5) = +0.15
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

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=8,
        enable_auto_extract=False,
        seed_initial_q=0.5,
    )
    _seed_lib(method, ["skill-a", "skill-b"])
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    # 2 skills, each called once. Hook log is empty → fall back to
    # session-log extraction.
    trial_dir = tmp_path / "trial-2skills"
    trial_dir.mkdir()
    _write_session_jsonl(
        trial_dir,
        _skill_tool_use("skill-a"),
        _skill_tool_use("skill-b"),
    )

    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-2skills", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_table = dict(state["q_table"])
    # Both skills were Q=0.5 (seed), got +0.15 → Q=0.65.
    # The q_table may have one entry per skill; assert both are at
    # 0.65.
    assert abs(q_table["skill-a"] - 0.65) < 1e-9, q_table
    assert abs(q_table["skill-b"] - 0.65) < 1e-9, q_table


def test_q_update_no_calls_no_op(tmp_path: Path, monkeypatch):
    """No Skill calls → no Q-update. ``state.step`` still increments."""
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
    _seed_lib(method, ["git-basics"])
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    # Empty trial dir, no session log, no hook log.
    trial_dir = tmp_path / "trial-empty"
    trial_dir.mkdir()
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-empty", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    # Trial was processed end-to-end (step incremented).
    assert state["step"] == 1
    # Seed skill still at Q=0.5 (no update fired).
    q_table = dict(state["q_table"])
    assert abs(q_table["git-basics"] - 0.5) < 1e-9
    # n_retrievals stays at 0 — never-used skills must not see UCB decay.
    assert state["library"]["skills"]["git-basics"]["n_retrievals"] == 0


def test_q_update_delta_formula_is_alpha_times_r_task_minus_q_old(
    tmp_path: Path, monkeypatch
):
    """The Q-update must be exactly ``delta = q_alpha * (r_task - q_old)``.

    No ``q_w_subtask``, no ``q_w_task``, no judge LLM call. Assert by
    comparing the post-trial Q to the closed-form expression.
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

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
        q_alpha=0.3,  # explicit; default is 0.3 too
    )
    _seed_lib(method, ["git-basics"])
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    trial_dir = tmp_path / "trial-formula"
    trial_dir.mkdir()
    _write_session_jsonl(trial_dir, _skill_tool_use("git-basics"))

    # Failed trial (r_task=0).
    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-formula", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_new = dict(state["q_table"])["git-basics"]
    q_old = 0.5
    expected = q_old + method.q_alpha * (0 - q_old)
    assert abs(q_new - expected) < 1e-9, (
        f"q_new={q_new}, expected {expected} "
        f"(q_alpha={method.q_alpha}, r_task=0, q_old={q_old})"
    )


def test_q_update_n_retrievals_increments_by_call_count(
    tmp_path: Path, monkeypatch
):
    """Bug 11: ``n_retrievals`` must increment by the per-trial call count.

    2 Skill calls to git-basics → expect n_retrievals == 2.
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

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
    )
    _seed_lib(method, ["git-basics"])
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    trial_dir = tmp_path / "trial-2calls"
    trial_dir.mkdir()
    _write_session_jsonl(
        trial_dir,
        _skill_tool_use("git-basics"),
        _skill_tool_use("git-basics"),
    )

    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-2calls", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    n_ret = state["library"]["skills"]["git-basics"]["n_retrievals"]
    assert n_ret == 2, f"n_retrievals should equal call count (2); got {n_ret}"


def test_q_update_falls_back_to_session_log_when_hook_log_empty(
    tmp_path: Path, monkeypatch
):
    """When skillq_skill_calls.jsonl is missing but the session jsonl
    records Skill calls, the session-log fallback path still drives
    Q-updates.

    This is the agentic-mode case (no PreToolUse hook installed).
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

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
    )
    _seed_lib(method, ["git-basics"])
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    # Crucially, do NOT write skillq_skill_calls.jsonl — that's the
    # "hook didn't fire" scenario.
    trial_dir = tmp_path / "trial-x"
    trial_dir.mkdir()
    _write_session_jsonl(trial_dir, _skill_tool_use("git-basics"))

    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_table = dict(state["q_table"])
    # Session-log fallback recovered git-basics; Eq.5 fired.
    # delta = 0.3 * (1 - 0.5) = +0.15 → Q = 0.65.
    assert "git-basics" in q_table
    assert q_table["git-basics"] > 0.5


def test_q_update_n_success_increments_when_r_task_one(
    tmp_path: Path, monkeypatch
):
    """``n_success += 1 if r_task`` — task-level success counter per skill."""
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
    )
    _seed_lib(method, ["git-basics"])
    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    trial_dir = tmp_path / "trial-success"
    trial_dir.mkdir()
    _write_session_jsonl(trial_dir, _skill_tool_use("git-basics"))

    # Successful trial (r_task=1).
    result = _fake_trial_result(reward=1.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-success", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    n_success = state["library"]["skills"]["git-basics"]["n_success"]
    assert n_success == 1, f"n_success should be 1 after successful trial; got {n_success}"


# ---------------------------------------------------------------------------
# Cosine-weighted Q-update (Fix 3, 2026-06-24)
# ---------------------------------------------------------------------------
def _seed_emb_cache(method: MethodConfig, emb: dict[str, list[float]]) -> Path:
    """Write ``emb_cache.json`` with the given {skill_id: vec} mapping.
    Returns the cache path.
    """
    import json as _json
    from skillq.method.vector_table import VectorTable

    cache = VectorTable(method.resolved_state_path().parent / "emb_cache.json")
    cache.load()  # ensure parent dir exists / file present
    for sid, vec in emb.items():
        import numpy as np
        cache.upsert(sid, np.asarray(vec, dtype=np.float32))
    cache.save()
    return cache.cache_path


def test_q_update_cosine_weight_irrelevant_zeroed(tmp_path: Path, monkeypatch):
    """Skill phi_s orthogonal to phi(q) → delta clamped to 0.

    With q_update_cosine_weight=True and a skill embedding orthogonal to
    the trial's intent embedding, the skill's Q-value is preserved at
    q_old (delta=0). The trial failure does not pollute the unrelated
    skill's Q.
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

    # phi(q) = [1, 0]; phi_s for "unrelated" = [0, 1] → cos=0 → delta=0
    monkeypatch.setattr(
        bridge_mod, "sync_embed",
        lambda text, host="127.0.0.1", port=8765: [1.0, 0.0],
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
        q_update_cosine_weight=True,
    )
    _seed_lib(method, ["unrelated"])
    _seed_emb_cache(method, {"unrelated": [0.0, 1.0]})

    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    trial_dir = tmp_path / "trial-cos-zero"
    trial_dir.mkdir()
    _write_session_jsonl(trial_dir, _skill_tool_use("unrelated"))

    # Failed trial (r_task=0). Plain Eq.5 would push Q to 0.35.
    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-cos-zero", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_new = dict(state["q_table"])["unrelated"]
    # Cosine weight = max(0, 0) = 0 → delta=0 → q stays at seed_initial_q.
    assert abs(q_new - 0.5) < 1e-9, f"q should stay at 0.5 (cos=0 → no update); got {q_new}"


def test_q_update_cosine_weight_relevant_full(tmp_path: Path, monkeypatch):
    """Skill phi_s parallel to phi(q) → full Eq.5 delta applied."""
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

    # phi(q) = phi(s) = [1, 0] → cos=1 → full delta
    monkeypatch.setattr(
        bridge_mod, "sync_embed",
        lambda text, host="127.0.0.1", port=8765: [1.0, 0.0],
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
        q_update_cosine_weight=True,
        q_alpha=0.3,
    )
    _seed_lib(method, ["relevant"])
    _seed_emb_cache(method, {"relevant": [1.0, 0.0]})

    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    trial_dir = tmp_path / "trial-cos-full"
    trial_dir.mkdir()
    _write_session_jsonl(trial_dir, _skill_tool_use("relevant"))

    # Failed trial (r_task=0).
    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-cos-full", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_new = dict(state["q_table"])["relevant"]
    # cos=1 → full delta: 0.5 + 0.3 * (0 - 0.5) = 0.35
    expected = 0.5 + method.q_alpha * (0 - 0.5)
    assert abs(q_new - expected) < 1e-9, f"q should be {expected} (full delta); got {q_new}"


def test_q_update_cosine_weight_disabled(tmp_path: Path, monkeypatch):
    """q_update_cosine_weight=False → original Eq.5, even if embeddings
    are orthogonal.
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

    # phi(q) != phi(s), but weight disabled so delta is full.
    monkeypatch.setattr(
        bridge_mod, "sync_embed",
        lambda text, host="127.0.0.1", port=8765: [1.0, 0.0],
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
        q_update_cosine_weight=False,  # ← disabled
        q_alpha=0.3,
    )
    _seed_lib(method, ["unrelated-but-disabled"])
    _seed_emb_cache(method, {"unrelated-but-disabled": [0.0, 1.0]})

    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    trial_dir = tmp_path / "trial-disabled"
    trial_dir.mkdir()
    _write_session_jsonl(trial_dir, _skill_tool_use("unrelated-but-disabled"))

    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-disabled", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_new = dict(state["q_table"])["unrelated-but-disabled"]
    # Full Eq.5: 0.5 + 0.3 * (0 - 0.5) = 0.35 — even though phi_s is
    # orthogonal, the weight is bypassed.
    expected = 0.5 + method.q_alpha * (0 - 0.5)
    assert abs(q_new - expected) < 1e-9, f"q should be {expected} (no weight); got {q_new}"


def test_q_update_phi_q_embed_failure_falls_back(tmp_path: Path, monkeypatch):
    """sync_embed raises → phi(q)=None → original Eq.5 (no cosine weight).
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

    def _fake_sync_embed_raise(*args, **kwargs):
        raise RuntimeError("embed service unavailable")
    monkeypatch.setattr(bridge_mod, "sync_embed", _fake_sync_embed_raise)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
        q_update_cosine_weight=True,  # ← enabled but embed fails
        q_alpha=0.3,
    )
    _seed_lib(method, ["any"])
    _seed_emb_cache(method, {"any": [0.0, 1.0]})

    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    trial_dir = tmp_path / "trial-embed-fail"
    trial_dir.mkdir()
    _write_session_jsonl(trial_dir, _skill_tool_use("any"))

    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-embed-fail", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    q_new = dict(state["q_table"])["any"]
    # phi(q)=None → fall back to plain Eq.5
    expected = 0.5 + method.q_alpha * (0 - 0.5)
    assert abs(q_new - expected) < 1e-9, (
        f"q should be {expected} (fall back to Eq.5); got {q_new}"
    )


def test_q_update_cosine_sim_recorded_in_trace(tmp_path: Path, monkeypatch):
    """q_updates.jsonl should record cosine_sim per updated skill."""
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

    monkeypatch.setattr(
        bridge_mod, "sync_embed",
        lambda text, host="127.0.0.1", port=8765: [1.0, 0.0],
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=False,
        seed_initial_q=0.5,
        q_update_cosine_weight=True,
        q_alpha=0.3,
    )
    _seed_lib(method, ["skill-a"])
    _seed_emb_cache(method, {"skill-a": [1.0, 0.0]})  # parallel → cos=1

    job = _MockJob()
    bridge_mod.attach_paper_registers(job, method)

    trial_dir = tmp_path / "trial-trace"
    trial_dir.mkdir()
    _write_session_jsonl(trial_dir, _skill_tool_use("skill-a"))

    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    event = _fake_hook_event("trial-trace", result=result)
    asyncio.run(job.on_ended(event))

    trace_path = trial_dir / "skillq_state" / "q_updates.jsonl"
    assert trace_path.exists(), f"trace missing at {trace_path}"
    entries = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["skill"] == "skill-a"
    assert "cosine_sim" in entry
    assert abs(entry["cosine_sim"] - 1.0) < 1e-6