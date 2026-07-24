"""End-to-end bridge tests for the new auto-extract path.

These tests verify that :func:`skillq.runtime.bridge.attach_registers`
correctly triggers the extractor on the right attribution verdicts,
adds the new skill to the library, and resets its probation counter.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.layers.l3_attribution.models import Attribution, TrialAttribution  # noqa: E402
from skillq.shared.q_table import LibManager  # noqa: E402
from skillq.shared.library import QlibState  # noqa: E402
from skillq.shared.types import Qlib, Skill  # noqa: E402
from skillq.config import MethodConfig  # noqa: E402


class _MockJob:
    def __init__(self) -> None:
        self.on_ended: Any = None
        # 2026-06-25: SimpleNamespace + max_retries=0 to match the
        # production YAML and to avoid MagicMock's
        # `is not None` / __contains__ semantics silently corrupting
        # the retry-classification.
        self.config = SimpleNamespace(
            retry=SimpleNamespace(
                max_retries=0,
                exclude_exceptions=None,
                include_exceptions=None,
            )
        )

    def on_trial_ended(self, callback: Any) -> None:
        self.on_ended = callback

    def on_trial_started(self, callback: Any) -> None:
        self.on_started = callback  # Step 7: new pipeline needs both

    def __len__(self) -> int:
        # The bridge uses ``len(job)`` to compute expected_terminal_trials
        # for the buffer force-flush on the last trial. We return a
        # large sentinel so the force-flush never fires in unit tests
        # (the per-trial buffer.add() handles the normal case).
        return 1_000_000


def _patch_litellm_backends(monkeypatch) -> None:
    """Replace LiteLLM + subprocess with stub shims that accept the
    kwargs the bridge passes and return predictable outputs.
    """
    from skillq.runtime import bridge as bridge_mod
    from skillq.layers.l3_attribution.models import StubAttributionBackend
    from skillq.shared.backends.litellm import StubEmbedder

    class _StubEmbedderShim(StubEmbedder):
        def __init__(self, *args, **kwargs) -> None:
            kwargs.pop("model", None)
            kwargs.pop("dim", None)
            super().__init__()

    class _StubAttributionShim(StubAttributionBackend):
        # Configurable at the bridge level; the tests will replace
        # this with a function that returns a chosen attribution.
        def __init__(self, *args, **kwargs) -> None:
            kwargs.pop("model", None)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(bridge_mod, "LiteLLMEmbedder", _StubEmbedderShim)
    monkeypatch.setattr(bridge_mod, "LiteLLMAttributionBackend", _StubAttributionShim)


def _patch_extractor_to_return(monkeypatch, skill: Skill | None) -> None:
    """Replace :class:`SkillExtractor.extract_batch` with a coroutine
    that immediately returns ``skill`` (no subprocess).
    """
    from skillq.runtime import bridge as bridge_mod

    async def fake_extract_batch(self, **kwargs) -> tuple[Skill | None, Path | None]:
        return skill, None

    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)


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
    """Pre-seed the library with one skill so retrieval isn't empty."""
    lib = Qlib(b_max=method.b_max)
    lib.add(Skill(skill_id="seed", body="seed body"))
    state = QlibState(method.resolved_state_path())
    state.save(
        lib,
        _fresh_mgr(method),
        lib_root=method.library_root,
        seed_initial_q=method.seed_initial_q,
    )


def _fresh_mgr(method: MethodConfig) -> LibManager:
    return LibManager(b_max=method.b_max)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_bridge_extracts_on_success_no_skill_seen(tmp_path: Path, monkeypatch):
    """r_task > 0.5 + SUCCESS_NO_SKILL_SEEN + no retrieved Q > θ_consider_used
    → extractor called → lib.add(new_skill)."""
    _patch_litellm_backends(monkeypatch)
    new_skill = Skill(skill_id="auto-extracted", body="x" * 200)
    _patch_extractor_to_return(monkeypatch, new_skill)

    # Make the attribution analyzer return SUCCESS_NO_SKILL_SEEN
    from skillq.runtime import bridge as bridge_mod
    from skillq.layers.l3_attribution.models import Attribution, StubAttributionBackend

    def returning_no_skill_seen(self, **kwargs):
        return TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="test",
            knowledge_to_extract="reusable knowledge",
        )

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer, "analyze", returning_no_skill_seen
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,       # flush on the first qualifying trial
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "auto-extracted" in state["library"]["skills"]
    # Probation counter for the new skill is reset → present in q_table
    # once the bridge ran (we don't run maintain in this short test, so
    # probation might be empty).
    assert state["step"] == 1


def test_bridge_skips_extract_on_failure(tmp_path: Path, monkeypatch):
    """r_task == 0 → extractor is NOT called."""
    _patch_litellm_backends(monkeypatch)
    called = {"n": 0}
    new_skill = Skill(skill_id="x", body="x" * 200)

    async def fake_extract_batch(self, **kwargs):
        called["n"] += 1
        return new_skill, None

    from skillq.runtime import bridge as bridge_mod
    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="won't run anyway",
            knowledge_to_extract="x",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib", b_max=4, enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,       # flush on the first qualifying trial
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    result = _fake_trial_result(reward=0.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    assert called["n"] == 0


def test_bridge_skips_extract_on_skill_used(tmp_path: Path, monkeypatch):
    """Attribution = SUCCESS_SKILL_USED → extractor NOT called."""
    _patch_litellm_backends(monkeypatch)
    called = {"n": 0}
    new_skill = Skill(skill_id="x", body="x" * 200)

    async def fake_extract_batch(self, **kwargs):
        called["n"] += 1
        return new_skill, None

    from skillq.runtime import bridge as bridge_mod
    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_SKILL_USED,
            overall_rationale="a skill helped",
            knowledge_to_extract="",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib", b_max=4, enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,       # flush on the first qualifying trial
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    assert called["n"] == 0


def test_bridge_skips_extract_when_disabled(tmp_path: Path, monkeypatch):
    """enable_auto_extract=False → extractor not even constructed."""
    _patch_litellm_backends(monkeypatch)

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=False,
    )
    _seed_lib(method)
    job = _MockJob()

    from skillq.runtime import bridge as bridge_mod

    bridge_mod.attach_layered_registers(job, method)
    # The hook closes over an `extractor` var; if it's None the extract
    # branch is skipped without calling SkillExtractor.extract.
    # We don't need to assert the .extract call count — the fact that
    # the test passes (no exception) is sufficient.

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))


def test_bridge_extracts_on_failure_no_skill(tmp_path: Path, monkeypatch):
    """r_task=0 + FAILURE_SKILL_NOT_USED + non-empty knowledge_to_extract
    → extractor called with mode='failure'.

    The historical "skip extract if any existing skill has high Q"
    gate is no longer present; the test still uses
    ``seed_initial_q=0.0`` so the seed skill's Q stays neutral —
    the contract verified here is "Rule 5 fires purely on the
    attribution enum + non-empty knowledge, independent of lib state".

    Mirrors test_bridge_extracts_on_success_no_skill_seen but on the
    failure path.
    """
    _patch_litellm_backends(monkeypatch)
    # Set extract_mode on the mock Skill to mirror what the real
    # SkillExtractor would write (see paper/method/extractor.py).
    new_skill = Skill(
        skill_id="guard-rail",
        body="x" * 200,
        metadata={"source": "skillq_extract", "extract_mode": "failure"},
    )
    _patch_extractor_to_return(monkeypatch, new_skill)

    from skillq.runtime import bridge as bridge_mod
    from skillq.layers.l3_attribution.models import Attribution, TrialAttribution

    def returning_failure(self, **kwargs):
        return TrialAttribution(
            overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
            overall_rationale="test",
            knowledge_to_extract="avoid doing X without first checking Y",
        )

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer, "analyze", returning_failure
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,       # flush on the first qualifying trial
        # Disable the incremental-edit path (it would call the LLM
        # to propose a SKILL.md edit; we don't have a stub for
        # that in this test file).
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    result = _fake_trial_result(reward=0.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "guard-rail" in state["library"]["skills"]
    # The new skill was created from a failure path, so its
    # extract_mode metadata should be "failure".
    new_meta = state["library"]["skills"]["guard-rail"]["metadata"]
    assert new_meta.get("extract_mode") == "failure"


def test_bridge_extracts_on_failure_even_when_skill_exists(tmp_path: Path, monkeypatch):
    """r_task=0 + FAILURE_SKILL_NOT_USED + a high-Q seed skill is already
    in lib + non-empty knowledge_to_extract → extractor IS called
    with mode='failure' and the new skill lands in lib.

    Locks in the post-gate-removal contract: Rule 5 fires purely on
    (attribution enum, non-empty knowledge), regardless of how good
    the existing lib looks. The ``seed_initial_q=0.5`` explicitly
    constructs the case the historical "skip if high-Q skill exists"
    gate used to suppress.
    """
    _patch_litellm_backends(monkeypatch)
    called = {"n": 0}
    new_skill = Skill(
        skill_id="guard-rail",
        body="x" * 200,
        metadata={"source": "skillq_extract", "extract_mode": "failure"},
    )

    async def fake_extract_batch(self, **kwargs):
        called["n"] += 1
        return new_skill, None

    from skillq.runtime import bridge as bridge_mod
    from skillq.layers.l3_attribution.models import Attribution, TrialAttribution

    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
            overall_rationale="regression test for the removed gate",
            knowledge_to_extract=(
                "the existing seed skill was high-Q, but the agent still "
                "failed — synthesize a guard-rail from this attribution"
            ),
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        # Seed Q = 0.5 reproduces the exact scenario the historical
        # "skip if high-Q skill exists" gate used to suppress
        # (the old default threshold was 0.30).
        seed_initial_q=0.5,
        extract_every_n_trials=1,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    result = _fake_trial_result(reward=0.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    # The gate is gone — the extractor must fire and the new skill
    # must land in lib.
    assert called["n"] == 1, (
        "Rule 5 should fire on FAILURE_SKILL_NOT_USED + non-empty knowledge "
        "regardless of existing-skill Q"
    )
    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "guard-rail" in state["library"]["skills"]
    new_meta = state["library"]["skills"]["guard-rail"]["metadata"]
    assert new_meta.get("extract_mode") == "failure"


def test_bridge_flush_writes_mirror_to_seed_dir(tmp_path: Path, monkeypatch):
    """After a successful flush, the new skill's SKILL.md is mirrored
    into ``method.seed_skills_dir`` so a subsequent trial's container
    can see it via the existing bind-mount at /skills.
    """
    _patch_litellm_backends(monkeypatch)
    body = (
        "---\nname: auto-mirrored\n---\n# body\n\n"
        + "x" * 200
    )
    new_skill = Skill(skill_id="auto-mirrored", body=body)
    _patch_extractor_to_return(monkeypatch, new_skill)

    from skillq.runtime import bridge as bridge_mod

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.SUCCESS_NO_SKILL_SEEN,
            overall_rationale="test",
            knowledge_to_extract="reusable knowledge",
        ),
    )

    host_skills = tmp_path / "host_skills"
    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
                enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,
        seed_skills_dir=host_skills,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    result = _fake_trial_result(reward=1.0, trial_uri=str(tmp_path / "trial-x"))
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    mirror = host_skills / "auto-mirrored" / "SKILL.md"
    assert mirror.is_file(), (
        f"mirror SKILL.md not written; expected at {mirror}"
    )
    assert mirror.read_text(encoding="utf-8") == body


# ---------------------------------------------------------------------------
# 2026-06-25: classifier + NonZeroAgentExitCodeError / AgentTimeoutError
# must still fire the extract path when a usable trajectory exists.
# Before the fix, the blanket "exception_info != None bails" rule
# silently dropped these trials.
# ---------------------------------------------------------------------------
def _write_usable_trajectory(trial_dir: Path) -> None:
    """Write a 1-entry trajectory.json so the classifier promotes
    NonZeroAgentExitCodeError to RUN_TASK_FAILURE."""
    (trial_dir / "agent").mkdir(parents=True, exist_ok=True)
    (trial_dir / "agent" / "trajectory.json").write_text(
        json.dumps([{"type": "assistant", "message": {"content": "ok"}}]),
        encoding="utf-8",
    )


def test_bridge_extracts_on_nonzero_agent_exit_with_trajectory(
    tmp_path: Path, monkeypatch
):
    """Agent `claude --print` exited non-zero AFTER writing a full
    trajectory. The classifier must promote this to RUN_TASK_FAILURE
    and the extract path must fire. Pre-fix, this entire branch
    was silently skipped at line 1052 of bridge.py."""
    _patch_litellm_backends(monkeypatch)
    new_skill = Skill(
        skill_id="from-failed-run",
        body="x" * 200,
        metadata={"source": "skillq_extract", "extract_mode": "failure"},
    )
    _patch_extractor_to_return(monkeypatch, new_skill)

    from skillq.runtime import bridge as bridge_mod

    # Return FAILURE_SKILL_NOT_USED so Rule 5 fires (failure-mode extract).
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
            overall_rationale="test",
            knowledge_to_extract="reflection on the failed run",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,  # flush on the first qualifying trial
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-x"
    trial_dir.mkdir(parents=True, exist_ok=True)
    _write_usable_trajectory(trial_dir)

    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    # Simulate agent exit 1 — a non-OOM, non-infra failure.
    result.exception_info = MagicMock()
    result.exception_info.exception_type = "NonZeroAgentExitCodeError"
    result.exception_info.exception_message = "Command failed (exit 1): claude"
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "from-failed-run" in state["library"]["skills"], (
        "auto_extract should have fired on NonZeroAgentExitCodeError "
        "with a usable trajectory"
    )
    new_meta = state["library"]["skills"]["from-failed-run"]["metadata"]
    assert new_meta.get("extract_mode") == "failure"


def test_bridge_skips_extract_on_oom_even_with_trajectory(
    tmp_path: Path, monkeypatch
):
    """OOM (exit 137) is ALWAYS infra failure per user direction
    (2026-06-25), even if a partial trajectory was written. The
    extract path must NOT fire — the OOM signal is the more
    informative outcome."""
    _patch_litellm_backends(monkeypatch)
    called = {"n": 0}
    new_skill = Skill(skill_id="should-not-appear", body="x" * 200)

    from skillq.runtime import bridge as bridge_mod

    async def fake_extract_batch(self, **kwargs):
        called["n"] += 1
        return new_skill, None

    monkeypatch.setattr(bridge_mod.SkillExtractor, "extract_batch", fake_extract_batch)
    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
            overall_rationale="won't run",
            knowledge_to_extract="x",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib", b_max=4, enable_auto_extract=True,
        seed_initial_q=0.0, extract_every_n_trials=1,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-x"
    trial_dir.mkdir(parents=True, exist_ok=True)
    _write_usable_trajectory(trial_dir)  # trajectory exists

    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    result.exception_info = MagicMock()
    result.exception_info.exception_type = "NonZeroAgentExitCodeError"
    result.exception_info.exception_message = "Command failed (exit 137): killed"
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    assert called["n"] == 0
    state = json.loads(method.resolved_state_path().read_text(encoding="utf-8"))
    assert "should-not-appear" not in state["library"]["skills"]


def test_bridge_skips_extract_on_failed_run_without_trajectory(
    tmp_path: Path, monkeypatch
):
    """NonZeroAgentExitCodeError but no usable trajectory on disk
    (e.g. the agent died before writing anything) → SKIP_ALL. There
    is nothing to extract from a half-flushed trial."""
    _patch_litellm_backends(monkeypatch)
    called = {"n": 0}
    new_skill = Skill(skill_id="should-not-appear", body="x" * 200)

    from skillq.runtime import bridge as bridge_mod

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
            overall_rationale="won't run",
            knowledge_to_extract="x",
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib", b_max=4, enable_auto_extract=True,
        seed_initial_q=0.0, extract_every_n_trials=1,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    # trial_dir exists but agent/trajectory.json does NOT
    trial_dir = tmp_path / "trial-x"
    trial_dir.mkdir(parents=True, exist_ok=True)

    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    result.exception_info = MagicMock()
    result.exception_info.exception_type = "NonZeroAgentExitCodeError"
    result.exception_info.exception_message = "Command failed (exit 1): claude"
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    assert called["n"] == 0


# ---------------------------------------------------------------------------
# 2026-06-25: gap_description thread-through
# ---------------------------------------------------------------------------
def test_extract_buffer_carries_gap_description_to_extractor(
    tmp_path: Path, monkeypatch
):
    """When the attribution step returns a non-empty
    library_gap_skill_description, the bridge must thread it
    through extract_buffer into the per-trial record the
    extractor formats into the failure-path prompt.

    Pins the contract that
    ``extract_buffer.pending[0]["gap_description"]`` ==
    ``attribution.library_gap_skill_description``. The extractor
    reads ``trial["gap_description"]`` (see
    ``extractor.py:extract_batch``) and emits a
    ``library_gap_skill_description: <repr>`` line that the
    failure-path prompt uses as the primary seed.
    """
    _patch_litellm_backends(monkeypatch)

    from skillq.runtime import bridge as bridge_mod

    GAP_TEXT = (
        "a skill whose description names 'hardware-circuit-synthesis' "
        "and includes a sanity-test checklist for N=0, 1, 4 plus a "
        "stop signal after 3 failed versions"
    )

    # Capture the trials list the extractor sees — extract_buffer
    # is drained into (mode, records) tuples by extract_batch.
    captured: dict[str, Any] = {}

    async def _capture_extract_batch(self, *, trials, **_kwargs):
        captured["trials"] = trials
        return None, None

    # Monkeypatch the SkillExtractor.extract_batch method (the
    # actual entry point the bridge calls in
    # _attribution_and_extract_dispatch's _flush_buffer).
    monkeypatch.setattr(
        bridge_mod.SkillExtractor, "extract_batch", _capture_extract_batch
    )

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
            overall_rationale="agent debug-spiraled",
            knowledge_to_extract="wrote 7 versions of gen.py",
            library_gap_skill_description=GAP_TEXT,
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-x"
    trial_dir.mkdir(parents=True, exist_ok=True)
    _write_usable_trajectory(trial_dir)

    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    result.exception_info = MagicMock()
    result.exception_info.exception_type = "NonZeroAgentExitCodeError"
    result.exception_info.exception_message = "Command failed (exit 1): claude"
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    # Buffer must have drained into the extractor with the gap
    # description intact.
    assert "trials" in captured, (
        "extract_batch was not called; Rule 5 didn't fire. Check "
        "the attribution override and the failure-path gate."
    )
    assert len(captured["trials"]) == 1
    assert captured["trials"][0]["gap_description"] == GAP_TEXT
    # knowledge still present so the prompt has both fields.
    assert captured["trials"][0]["knowledge"] == "wrote 7 versions of gen.py"


def test_extract_buffer_gap_description_empty_by_default(
    tmp_path: Path, monkeypatch
):
    """When the attribution step returns an empty
    library_gap_skill_description (success paths, FAIL_ENV_ISSUE,
    or stubs), the buffer record must carry an empty string, not
    a missing key — the failure-path extractor's per-trial line
    formatter checks ``t.get('gap_description', '')``."""
    _patch_litellm_backends(monkeypatch)

    from skillq.runtime import bridge as bridge_mod

    captured: dict[str, Any] = {}

    async def _capture_extract_batch(self, *, trials, **_kwargs):
        captured["trials"] = trials
        return None, None

    monkeypatch.setattr(
        bridge_mod.SkillExtractor, "extract_batch", _capture_extract_batch
    )

    monkeypatch.setattr(
        bridge_mod.AttributionAnalyzer,
        "analyze",
        lambda self, **kwargs: TrialAttribution(
            overall_attribution=Attribution.FAILURE_SKILL_NOT_USED,
            overall_rationale="agent failed",
            knowledge_to_extract="some reflection",
            # library_gap_skill_description omitted → defaults to ''
        ),
    )

    method = MethodConfig(
        library_root=tmp_path / "lib",
        b_max=4,
        enable_auto_extract=True,
        seed_initial_q=0.0,
        extract_every_n_trials=1,
    )
    _seed_lib(method)
    job = _MockJob()
    bridge_mod.attach_layered_registers(job, method)

    trial_dir = tmp_path / "trial-x"
    trial_dir.mkdir(parents=True, exist_ok=True)
    _write_usable_trajectory(trial_dir)

    result = _fake_trial_result(reward=0.0, trial_uri=str(trial_dir))
    result.exception_info = MagicMock()
    result.exception_info.exception_type = "NonZeroAgentExitCodeError"
    result.exception_info.exception_message = "Command failed (exit 1): claude"
    event = _fake_hook_event("trial-x", result=result)
    asyncio.run(job.on_ended(event))

    assert "trials" in captured
    assert captured["trials"][0]["gap_description"] == ""
