"""Unit tests for the container-wiring module (issue #2)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.method.library import LibManager  # noqa: E402
from skillq.method.state import QlibState  # noqa: E402
from skillq.method.types import Qlib, Skill  # noqa: E402
from skillq.method.vector_table import VectorTable  # noqa: E402
from skillq.paper_mode.config import MethodConfig  # noqa: E402
from skillq.paper_mode.container_wiring import (  # noqa: E402
    CONTAINER_CALLS_LOG_PATH,
    CONTAINER_EMB_CACHE_PATH,
    CONTAINER_HOOK_PATH,
    CONTAINER_LIB_PATH,
    CONTAINER_Q_TABLE_PATH,
    CONTAINER_SETTINGS_PATH,
    _bind_mount,
    _settings_json_path,
    _write_state_files,
    wire_one_trial,
)


def _fake_event(tmp_path: Path, task_name: str = "sample-task") -> MagicMock:
    """Build a minimal TrialHookEvent stand-in for wiring tests."""
    event = MagicMock()
    event.event = "start"
    event.trial_id = "trial-abc"
    event.task_name = task_name
    # config.agent and config.environment are mutable dicts (the
    # real ones are Pydantic models, but MagicMock suffices for
    # this unit test).
    event.config = MagicMock()
    event.config.trial_name = "sample-task__abcd123"
    event.config.trials_dir = tmp_path
    event.config.agent.env = {}
    event.config.agent.kwargs = {}
    event.config.environment.mounts_json = None
    return event


def _seed_state(tmp_path: Path) -> tuple[Qlib, LibManager, VectorTable]:
    """Write a 1-skill library + Q-table + emb-cache to disk."""
    method_lib_root = tmp_path / ".skillq_library"
    state_path = method_lib_root / ".state" / "method_state.json"
    emb_cache_path = method_lib_root / ".state" / "emb_cache.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)

    lib = Qlib(b_max=10)
    lib.add(Skill(skill_id="git-basics", body="git rebase -i HEAD~3"))

    mgr = LibManager(
        b_max=10, theta_admit=0.3, theta_evict=0.1,
        n_explore=5, n_stale=80,
    )
    mgr.update_q("git-basics", 0.42)

    state = QlibState(state_path)
    state.save(lib, mgr, lib_root=method_lib_root, seed_initial_q=0.5)

    emb_cache = VectorTable(emb_cache_path)
    emb_cache.upsert("git-basics", [0.1, 0.2, 0.3, 0.4])
    emb_cache.save()

    return lib, mgr, emb_cache


def test_write_state_files_produces_four_files(tmp_path: Path):
    lib, mgr, emb_cache = _seed_state(tmp_path)
    lib_p, q_p, emb_p, log_p = _write_state_files(
        tmp_path, lib, mgr, emb_cache
    )
    assert lib_p.exists() and lib_p.name == "lib.json"
    assert q_p.exists() and q_p.name == "q_table.json"
    assert emb_p.exists() and emb_p.name == "emb_cache.json"
    # calls_log path is now under Harbor's auto-injected
    # ``agent_dir`` bind mount (see Bug 2 fix); the wiring only
    # returns the path, it doesn't create the file. The hook
    # creates it on first Skill() call.
    assert log_p.name == "skillq_skill_calls.jsonl"
    assert log_p.parent == tmp_path / "agent" / "sessions"


def test_write_state_files_lib_has_skill_bodies(tmp_path: Path):
    lib, mgr, emb_cache = _seed_state(tmp_path)
    lib_p, _, _, _ = _write_state_files(tmp_path, lib, mgr, emb_cache)
    payload = json.loads(lib_p.read_text())
    assert "skills" in payload
    assert len(payload["skills"]) == 1
    skill = payload["skills"][0]
    assert skill["skill_id"] == "git-basics"
    assert "git rebase" in skill["body"]


def test_write_state_files_q_table_is_global(tmp_path: Path):
    lib, mgr, emb_cache = _seed_state(tmp_path)
    _, q_p, _, _ = _write_state_files(tmp_path, lib, mgr, emb_cache)
    q_table = json.loads(q_p.read_text())
    # Global-Q refactor: {skill_id: q}, no intent dim
    assert q_table == {"git-basics": pytest.approx(0.42, abs=1e-9)}


def test_write_state_files_emb_cache_roundtrips(tmp_path: Path):
    lib, mgr, emb_cache = _seed_state(tmp_path)
    _, _, emb_p, _ = _write_state_files(tmp_path, lib, mgr, emb_cache)
    payload = json.loads(emb_p.read_text())
    # float32 round-trip (np.asarray with dtype=float32 loses a bit
    # of precision) — assert elementwise within 1e-6.
    expected = [0.1, 0.2, 0.3, 0.4]
    actual = payload["embeddings"]["git-basics"]
    assert len(actual) == len(expected)
    for got, want in zip(actual, expected):
        assert abs(got - want) < 1e-6


def test_settings_json_registers_pretooluse_hook(tmp_path: Path):
    settings_path = _settings_json_path(tmp_path)
    assert settings_path.exists()
    payload = json.loads(settings_path.read_text())
    assert "hooks" in payload
    pre_tool_use = payload["hooks"]["PreToolUse"]
    assert len(pre_tool_use) == 1
    matcher = pre_tool_use[0]
    assert matcher["matcher"] == "Skill"
    cmd = matcher["hooks"][0]["command"]
    assert CONTAINER_HOOK_PATH in cmd
    assert cmd.startswith("python3 ")


def test_bind_mount_format():
    mount = _bind_mount("/host/path", "/container/path", read_only=True)
    assert mount == {
        "type": "bind",
        "source": "/host/path",
        "target": "/container/path",
        "read_only": True,
    }


def test_wire_one_trial_populates_env_and_mounts(tmp_path: Path):
    """End-to-end: build event, call wire_one_trial, check the
    mutation landed in agent.env and environment.mounts_json.
    """
    from skillq.paper_mode.container_wiring import ContainerWiringHandle

    _, _, _ = _seed_state(tmp_path)
    method = MethodConfig(
        library_root=tmp_path / ".skillq_library",
        b_max=10,
        n_explore=5,
        seed_initial_q=0.5,
        retrieval_mode="hook",   # force Method B (these tests assert on skillq_state + hook env)
        hook_enabled=True,
        hook_top_k=3,
        hook_lambda=0.5,
        hook_c_ucb=0.5,
    )
    event = _fake_event(tmp_path, task_name="fix-git")
    handle = ContainerWiringHandle(
        embedding={"thread": None, "server": None, "port": 8765, "stop_event": None},
        method=method,
        library_root=method.library_root,
        state_path=method.resolved_state_path(),
    )

    wire_one_trial(handle, event)

    # agent.env should now contain the SKILLQ_* keys. All four
    # file paths point at the container-side bind-mount targets,
    # not the host-side paths the bridge wrote them to. The hook
    # runs inside the agent container, so it needs the in-container
    # paths; the bind is read-write so ``_append_jsonl`` can
    # actually write.
    trial_dir = tmp_path / "sample-task__abcd123"
    env = event.config.agent.env
    assert env["SKILLQ_LIB"] == "/logs/agent/sessions/skillq_lib.json"
    assert env["SKILLQ_Q_TABLE"] == "/logs/agent/sessions/skillq_q_table.json"
    assert env["SKILLQ_EMB_CACHE"] == "/logs/agent/sessions/skillq_emb_cache.json"
    assert env["SKILLQ_CALLS_LOG"] == "/logs/agent/sessions/skillq_skill_calls.jsonl"
    assert env["SKILLQ_EMBED_PORT"] == "8765"
    assert env["SKILLQ_USER_TASK"] == "fix-git"
    assert env["SKILLQ_HOOK_TOP_K"] == "3"
    assert env["SKILLQ_HOOK_LAMBDA"].startswith("0.")
    assert env["SKILLQ_HOOK_C_UCB"].startswith("0.")

    # environment.mounts_json should have 5 entries (3 read-only
    # state files + settings + hook script). The calls_log no
    # longer needs a SkillQ-injected mount — it relies on
    # Harbor's auto-injected ``agent_dir`` read-write mount
    # (see Bug 2 fix).
    mounts = event.config.environment.mounts_json
    assert len(mounts) == 5
    # No mount should have ``read_only: False`` (would violate
    # Harbor's ``ServiceVolumeConfig.read_only: Literal[True]``
    # TypedDict and break ``--resume``).
    assert not any(m.get("read_only") is False for m in mounts)

    # And the state files actually got written
    assert (trial_dir / "skillq_state" / "lib.json").exists()
    assert (trial_dir / "skillq_state" / "q_table.json").exists()
    assert (trial_dir / "skillq_state" / "emb_cache.json").exists()
    # calls_log.jsonl is no longer staged by SkillQ — it lives in
    # Harbor's auto-mounted ``agent_dir`` (see Bug 2 fix) and is
    # created by the hook on first Skill() call.
    assert (trial_dir / "skillq_state" / "settings.json").exists()

    # All SkillQ-injected mounts are read-only. The calls_log is
    # written into Harbor's auto-injected ``agent_dir`` mount,
    # which is read-write by default (no ``read_only`` key — the
    # TypedDict allows this; Docker treats it as read-write).
    rw = [m for m in mounts if not m["read_only"]]
    assert rw == []

    # Verify the container-side targets are what hook.py reads
    targets = {m["target"] for m in mounts}
    assert CONTAINER_LIB_PATH in targets
    assert CONTAINER_Q_TABLE_PATH in targets
    assert CONTAINER_EMB_CACHE_PATH in targets
    assert CONTAINER_SETTINGS_PATH in targets
    assert CONTAINER_HOOK_PATH in targets


def test_wire_one_trial_uses_method_config_tunables(tmp_path: Path):
    """Verify the env forwards MethodConfig values, not hardcoded."""
    from skillq.paper_mode.container_wiring import ContainerWiringHandle

    _, _, _ = _seed_state(tmp_path)
    method = MethodConfig(
        library_root=tmp_path / ".skillq_library",
        b_max=10,
        n_explore=5,
        seed_initial_q=0.5,
        retrieval_mode="hook",   # force Method B
        hook_top_k=7,           # ← custom
        hook_lambda=0.2,        # ← custom
        hook_c_ucb=0.9,        # ← custom
        hook_embedding_service_port=9999,
    )
    event = _fake_event(tmp_path)
    handle = ContainerWiringHandle(
        embedding={"thread": None, "server": None, "port": 9999, "stop_event": None},
        method=method,
        library_root=method.library_root,
        state_path=method.resolved_state_path(),
    )

    wire_one_trial(handle, event)

    env = event.config.agent.env
    assert env["SKILLQ_HOOK_TOP_K"] == "7"
    assert abs(float(env["SKILLQ_HOOK_LAMBDA"]) - 0.2) < 1e-6
    assert abs(float(env["SKILLQ_HOOK_C_UCB"]) - 0.9) < 1e-6
    assert env["SKILLQ_EMBED_PORT"] == "9999"


def test_wire_one_trial_handles_empty_lib(tmp_path: Path):
    """No skills in lib → lib.json has empty skills list (hook no-ops)."""
    from skillq.paper_mode.container_wiring import ContainerWiringHandle

    method = MethodConfig(
        library_root=tmp_path / ".skillq_library",
        b_max=10,
        n_explore=5,
        retrieval_mode="hook",   # force Method B
    )
    # Don't seed any skills — lib is empty.
    event = _fake_event(tmp_path)
    handle = ContainerWiringHandle(
        embedding={"thread": None, "server": None, "port": 8765, "stop_event": None},
        method=method,
        library_root=method.library_root,
        state_path=method.resolved_state_path(),
    )
    wire_one_trial(handle, event)
    # No crash, files still written (empty)
    trial_dir = tmp_path / "sample-task__abcd123"
    assert (trial_dir / "skillq_state" / "lib.json").exists()
    assert json.loads((trial_dir / "skillq_state" / "lib.json").read_text())["skills"] == []


# ---------------------------------------------------------------------------
# Method A (agentic) tests
# ---------------------------------------------------------------------------
def test_wire_one_trial_agentic_writes_skill_tree(tmp_path: Path):
    """In agentic mode wire_one_trial materializes the Method-A
    artifact tree (SKILL.md / _manifest.json / _search.sh /
    PAPER_METHOD_INSTRUCTIONS.md) and bind-mounts it to
    $CLAUDE_CONFIG_DIR/<agentic_skill_dir_name>/.
    """
    from skillq.paper_mode.container_wiring import ContainerWiringHandle

    _, _, _ = _seed_state(tmp_path)
    method = MethodConfig(
        library_root=tmp_path / ".skillq_library",
        b_max=10,
        n_explore=5,
        seed_initial_q=0.5,
        retrieval_mode="agentic",
    )
    event = _fake_event(tmp_path)
    handle = ContainerWiringHandle(
        embedding={"thread": None, "server": None, "port": 8765, "stop_event": None},
        method=method,
        library_root=method.library_root,
        state_path=method.resolved_state_path(),
    )

    wire_one_trial(handle, event)

    trial_dir = tmp_path / "sample-task__abcd123"
    skills_dir = trial_dir / "skillq_skills"
    # Per-skill SKILL.md
    assert (skills_dir / "git-basics" / "SKILL.md").exists()
    assert "q_value:" in (skills_dir / "git-basics" / "SKILL.md").read_text()
    # Manifest + search script
    assert (skills_dir / "_manifest.json").exists()
    assert (skills_dir / "_search.sh").exists()
    # Instructions
    assert (skills_dir / "PAPER_METHOD_INSTRUCTIONS.md").exists()
    # Mounts
    mounts = event.config.environment.mounts_json
    skills_mount = next(
        (m for m in mounts if m["target"].endswith("/skillq_skills")), None
    )
    assert skills_mount is not None
    assert skills_mount["source"].endswith("/skillq_skills")
    # No PreToolUse hook script mounted
    assert not any(
        m["target"].endswith("skillq_skill_hook.py") for m in mounts
    )


def test_wire_one_trial_agentic_no_claude_md_overwrite(tmp_path: Path):
    """Without user_claude_md_path, the user's CLAUDE.md is NOT
    bind-mounted (i.e. the writer doesn't touch it).
    """
    from skillq.paper_mode.container_wiring import ContainerWiringHandle

    _, _, _ = _seed_state(tmp_path)
    method = MethodConfig(
        library_root=tmp_path / ".skillq_library",
        b_max=10,
        n_explore=5,
        retrieval_mode="agentic",
        # user_claude_md_path is None by default → no merge
    )
    event = _fake_event(tmp_path)
    handle = ContainerWiringHandle(
        embedding={"thread": None, "server": None, "port": 8765, "stop_event": None},
        method=method,
        library_root=method.library_root,
        state_path=method.resolved_state_path(),
    )

    wire_one_trial(handle, event)

    mounts = event.config.environment.mounts_json
    # No mount targeting /CLAUDE.md
    assert not any(
        m["target"].endswith("/CLAUDE.md") for m in mounts
    )


def test_wire_one_trial_agentic_merges_user_claude_md(tmp_path: Path):
    """With user_claude_md_path set, the user's existing CLAUDE.md
    is read, the skillq-method snippet is appended, and the merged
    result is bind-mounted to $CLAUDE_CONFIG_DIR/CLAUDE.md.
    """
    from skillq.paper_mode.container_wiring import ContainerWiringHandle

    _, _, _ = _seed_state(tmp_path)

    # User's existing CLAUDE.md on the host
    user_claude = tmp_path / "user_CLAUDE.md"
    user_claude.write_text(
        "# My project rules\nAlways use tabs.\n",
        encoding="utf-8",
    )

    method = MethodConfig(
        library_root=tmp_path / ".skillq_library",
        b_max=10,
        n_explore=5,
        retrieval_mode="agentic",
        user_claude_md_path=user_claude,
    )
    event = _fake_event(tmp_path)
    handle = ContainerWiringHandle(
        embedding={"thread": None, "server": None, "port": 8765, "stop_event": None},
        method=method,
        library_root=method.library_root,
        state_path=method.resolved_state_path(),
    )

    wire_one_trial(handle, event)

    # User's original file is NOT modified
    assert user_claude.read_text() == "# My project rules\nAlways use tabs.\n"

    # The merged file exists and contains both
    trial_dir = tmp_path / "sample-task__abcd123"
    merged = trial_dir / "CLAUDE.md.merged"
    assert merged.exists()
    text = merged.read_text()
    assert "My project rules" in text
    assert "Always use tabs." in text
    assert "appended by mg skillq-method bridge" in text
    assert "_search.sh" in text

    # The merged file is bind-mounted to $CLAUDE_CONFIG_DIR/CLAUDE.md
    mounts = event.config.environment.mounts_json
    claude_mount = next(
        (m for m in mounts if m["target"].endswith("/CLAUDE.md")), None
    )
    assert claude_mount is not None
    assert claude_mount["source"].endswith("CLAUDE.md.merged")
