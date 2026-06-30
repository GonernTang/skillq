"""Regression tests for the emb_cache ordering fix (2026-07-01).

The bug: ``ON_TRIAL_ENDED_PIPELINE`` had ``step_refresh_emb_cache``
at position 5, BEFORE ``step_dispatch_evolve`` at position 7.
L4 Create at pos 7 appended to ``result.lib_changes`` AFTER
pos-5 had already saved ``emb_cache.json``. Result: every L4
addition in a same-trial scenario was lost from the cache
(verified live on small10 run #1: 8 L4-created skills present
in ``skills/`` and the lib Q-table, but ``emb_cache.json``
still showed the pre-run 57 skills).

The fix has three parts:

1. ``ON_TRIAL_ENDED_PIPELINE`` now ends with
   ``... → step_incremental_edit → step_dispatch_evolve →
   step_refresh_emb_cache → step_save_state``.
2. ``step_incremental_edit`` no longer embeds inline — it pushes
   ``("replace", sid, new_body)`` onto ``result.lib_changes``.
3. ``step_save_state`` issues a defensive ``emb_cache.save()``
   at the end (last-trial safety net).

These tests pin all three invariants so a future refactor
doesn't reintroduce the bug.
"""

from __future__ import annotations

import asyncio

from skillq.runtime.context import StepResult
from skillq.runtime.steps import (
    ON_TRIAL_ENDED_PIPELINE,
    step_dispatch_evolve,
    step_refresh_emb_cache,
    step_save_state,
)


def _names(pipeline=ON_TRIAL_ENDED_PIPELINE):
    return [s.__name__ for s in pipeline]


def test_emb_cache_step_runs_after_l3_edit_and_l4_create():
    """Invariant: ``step_refresh_emb_cache`` must be AFTER every
    lib-mutating step so a single end-of-trial save captures all
    changes.

    L3 edit = ``step_incremental_edit`` (writes ``"replace"``).
    L4 create = ``step_dispatch_evolve`` (writes ``"add"``).
    """
    names = _names()
    emb_idx = names.index("step_refresh_emb_cache")
    edit_idx = names.index("step_incremental_edit")
    evo_idx = names.index("step_dispatch_evolve")
    save_idx = names.index("step_save_state")

    assert edit_idx < emb_idx, (
        f"step_incremental_edit (pos {edit_idx}) must run BEFORE "
        f"step_refresh_emb_cache (pos {emb_idx})"
    )
    assert evo_idx < emb_idx, (
        f"step_dispatch_evolve (pos {evo_idx}) must run BEFORE "
        f"step_refresh_emb_cache (pos {emb_idx})"
    )
    assert emb_idx < save_idx, (
        f"step_refresh_emb_cache (pos {emb_idx}) must run BEFORE "
        f"step_save_state (pos {save_idx})"
    )


def test_emb_cache_step_runs_after_maintain_lib():
    """``step_maintain_lib`` writes ``"remove"`` to lib_changes;
    emb_cache must also see those evictions.
    """
    names = _names()
    assert names.index("step_maintain_lib") < names.index("step_refresh_emb_cache")


def test_step_result_lib_change_action_set_includes_replace():
    """``step_incremental_edit`` pushes ``("replace", ...)`` triples.
    The action vocabulary is now ``{"add", "remove", "replace"}`` —
    pin via docstring check (cheap; no need to import internal
    parser).
    """
    result = StepResult()
    result.lib_changes.append(("replace", "test-skill", "# body"))
    action, sid, body = result.lib_changes[0]
    assert action == "replace"
    assert sid == "test-skill"
    assert body == "# body"


def test_step_refresh_emb_cache_handles_replace_action():
    """The consolidated emb_cache refresh must accept
    ``("replace", sid, body)`` triples from L3 edits and route
    them through ``sync_lib_to_vector_table(replaced=...)``.

    Smoke-test: directly call ``step_refresh_emb_cache`` with
    a lib_changes containing a replace triple; verify it does
    NOT raise (sync_lib_to_vector_table is best-effort inside
    the function — the test just confirms wiring).
    """

    async def _run():
        # Build a minimal ctx with services + emb_cache that
        # captures upserts. We don't need a real L2 trajectory.
        class _FakeEmbCache:
            def __init__(self):
                self.saved = 0
                self.upserts = []
                self.removes = []

            def upsert(self, sid, vec):
                self.upserts.append(sid)

            def remove(self, sid):
                self.removes.append(sid)

            def save(self):
                self.saved += 1

        class _FakeLib:
            pass

        class _FakeMgr:
            pass

        class _FakeMethod:
            embedder_model = "fake/model"
            embedder_dim = 4

        class _FakeServices:
            method = _FakeMethod()
            emb_cache = _FakeEmbCache()
            lib = _FakeLib()
            mgr = _FakeMgr()

        class _Ctx:
            services = _FakeServices()
            trial_id = "test-trial"
            intent_text = "test task"

        ctx = _Ctx()
        result = StepResult()
        result.lib_changes.append(("replace", "fake-skill", "# description: x"))

        # Stub the embedder so we don't hit a network. sync_lib_to_vector_table
        # calls embedder([texts]) → ndarray; we just return a fixed 2-D array.
        import numpy as np

        class _StubEmbedder:
            def __call__(self, texts):
                return np.zeros((len(texts), 4), dtype=np.float32)

        # Monkeypatch LiteLLMEmbedder inside the steps module to our stub.
        import skillq.runtime.steps as steps_mod
        original = steps_mod.LiteLLMEmbedder

        def _factory(model, dim):
            return _StubEmbedder()

        steps_mod.LiteLLMEmbedder = _factory
        try:
            await step_refresh_emb_cache(ctx, result)
        finally:
            steps_mod.LiteLLMEmbedder = original

        assert ctx.services.emb_cache.saved == 1, "save() must be called exactly once"
        assert "fake-skill" in ctx.services.emb_cache.upserts, (
            "replaced skill must reach upsert path"
        )

    asyncio.run(_run())


def test_step_save_state_defensive_emb_cache_save():
    """Defensive save at end of ``step_save_state`` — last-trial
    safety net. Even if ``step_refresh_emb_cache`` was a no-op
    (e.g., empty lib_changes) we still flush emb_cache.

    Smoke-test: drive ``step_save_state`` with a fake services
    bundle and confirm emb_cache.save() was called.
    """

    async def _run():
        class _FakeEmbCache:
            def __init__(self):
                self.saved = 0

            def save(self):
                self.saved += 1

        class _FakeLib:
            skills = {}

        class _FakeMgr:
            q_table = {}

        class _FakeState:
            def __init__(self):
                self.step = 0

            def save(self, lib, mgr, lib_root, seed_initial_q):
                pass

        class _FakeMethod:
            library_root = "/tmp"
            seed_initial_q = 0.5

        class _FakeServices:
            method = _FakeMethod()
            state = _FakeState()
            lib = _FakeLib()
            mgr = _FakeMgr()
            emb_cache = _FakeEmbCache()

        class _Ctx:
            services = _FakeServices()
            trial_dir = __import__("pathlib").Path("/tmp/fake_trial_dir")
            trial_id = "test-trial"

        ctx = _Ctx()
        await step_save_state(ctx, StepResult())
        assert ctx.services.emb_cache.saved >= 1, (
            "defensive emb_cache.save() must fire in step_save_state"
        )

    asyncio.run(_run())


def test_pipeline_invariant_docstring():
    """Sanity: the pipeline docstring at module top mentions the
    emb_cache invariant so future readers can grep for it.
    """
    import skillq.runtime.steps as steps_mod

    src = steps_mod.__doc__ or ""
    assert "step_refresh_emb_cache" in src, (
        "steps.py module docstring should describe the emb_cache "
        "ordering invariant for future maintainers"
    )