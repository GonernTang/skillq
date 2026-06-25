"""Integration tests for reuse_q_table=False / reuse_embedding_cache=False
(2026-06-25).

Verifies the load_into(overwrite_q=...) flow + VectorTable.clear() semantics
that the bridge relies on. Does NOT spin up the full Harbor container
pipeline; exercises the in-process helpers that drive the new flags.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pytest


def _write_disk_state(state_path: Path, q_value: float = 0.42) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "step": 7,
        "q_table": [["skill-A", q_value]],
        "library": {
            "b_max": 50,
            "skills": {
                "skill-A": {
                    "body": "# A\n",
                    "n_retrievals": 3,
                    "n_uses": 1,
                    "n_success": 1,
                    "metadata": {},
                }
            },
        },
        "seed_initial_q": 0.5,
    }))


def test_load_into_overwrite_q_true_resumes(tmp_path):
    """Default (overwrite_q=True): Q-table resumes from disk."""
    from skillq.method.state import QlibState
    from skillq.method.library import LibManager
    from skillq.method.types import Qlib

    state_path = tmp_path / "method_state.json"
    _write_disk_state(state_path, q_value=0.42)

    lib = Qlib(b_max=50)
    mgr = LibManager(b_max=50)
    QlibState(state_path).load_into(lib, mgr, overwrite_q=True)

    # Lib loaded
    assert "skill-A" in lib.skills
    # Q-table resumed
    assert mgr.q_table["skill-A"] == pytest.approx(0.42)


def test_load_into_overwrite_q_false_keeps_lib_drops_q(tmp_path):
    """overwrite_q=False: lib loaded but Q-table untouched."""
    from skillq.method.state import QlibState
    from skillq.method.library import LibManager
    from skillq.method.types import Qlib

    state_path = tmp_path / "method_state.json"
    _write_disk_state(state_path, q_value=0.42)

    lib = Qlib(b_max=50)
    mgr = LibManager(b_max=50)
    QlibState(state_path).load_into(lib, mgr, overwrite_q=False)

    # Lib loaded
    assert "skill-A" in lib.skills
    # Q-table NOT loaded (still empty)
    assert "skill-A" not in mgr.q_table


def test_load_into_overwrite_q_false_then_plan_d_seeds(tmp_path):
    """Simulates the full reuse_q_table=False flow: load_into(overwrite_q=False)
    + mgr.q_table.clear() + ensure_seeded → Q=seed_initial_q."""
    from skillq.method.state import QlibState
    from skillq.method.library import LibManager
    from skillq.method.types import Qlib

    state_path = tmp_path / "method_state.json"
    _write_disk_state(state_path, q_value=0.42)

    lib = Qlib(b_max=50)
    mgr = LibManager(b_max=50)
    state = QlibState(state_path)
    state.load_into(lib, mgr, overwrite_q=False)
    # Bridge does this next:
    mgr.q_table.clear()
    # Plan D ensure_seeded assigns seed_initial_q to every loaded skill:
    seed_initial_q = 0.5
    for sid in lib.skills:
        if sid not in mgr.q_table:
            mgr.q_table[sid] = seed_initial_q

    assert mgr.q_table["skill-A"] == pytest.approx(0.5)


def test_vector_table_clear_marks_dirty(tmp_path):
    """VectorTable.clear() empties the in-memory dict and sets _dirty=True
    so the next save() persists the empty state."""
    from skillq.method.vector_table import VectorTable

    cache = VectorTable(tmp_path / "emb_cache.json")
    cache.upsert("a", np.array([0.1, 0.2], dtype=np.float32))
    cache.upsert("b", np.array([0.3, 0.4], dtype=np.float32))
    assert len(cache) == 2
    assert cache._dirty is True

    cache.clear()
    assert len(cache) == 0
    assert cache._dirty is True

    cache.save()
    on_disk = json.loads((tmp_path / "emb_cache.json").read_text())
    assert on_disk["embeddings"] == {}


def test_vector_table_clear_empty_cache_idempotent(tmp_path):
    """clear() on an empty cache is a no-op (still marks dirty so the
    next save persists the empty state)."""
    from skillq.method.vector_table import VectorTable

    cache = VectorTable(tmp_path / "emb_cache.json")
    assert len(cache) == 0
    assert cache._dirty is False

    cache.clear()
    assert len(cache) == 0
    assert cache._dirty is True


def test_vector_table_clear_then_reload_is_empty(tmp_path):
    """After clear() + save(), a fresh VectorTable.load() yields 0 entries."""
    from skillq.method.vector_table import VectorTable

    cache = VectorTable(tmp_path / "emb_cache.json")
    cache.upsert("a", np.array([0.1, 0.2], dtype=np.float32))
    cache.clear()
    cache.save()

    cache2 = VectorTable(tmp_path / "emb_cache.json")
    loaded = cache2.load()
    assert loaded is True
    assert len(cache2) == 0