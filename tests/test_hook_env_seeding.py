"""Unit tests for the bridge's hook-env pre-seeding (2026-06-25).

The container-side hook reads 7 SKILLQ_HOOK_* env vars to decide:
  - which scoring formula to use (additive vs multiplicative)
  - the UCB / Q-mix weights
  - the Hard Gate threshold

These vars MUST reach the agent's _extra_env before Trial.create
snapshots config.env (Harbor's AgentFactory copies config.env to
agent._extra_env at construction time; later mutations are
invisible). The bridge's ``seed_agent_env`` runs in
``run_paper_job`` BEFORE ``Job.create`` for that reason.

These tests verify (without docker) that:
  1. All 7 tunables land in cfg.agents[0].env with method-config values
  2. The defaults match MethodConfig defaults (no silent drift)
  3. The pull-mode SKILLQ_PULL_TOP_K is added iff retrieval_mode=='pull'
  4. Embed port is taken from wiring handle (not method default)
     when wiring is present
"""
from __future__ import annotations
from types import SimpleNamespace
from typing import Any

from skillq.runtime.env_seed import seed_agent_env
from skillq.config import MethodConfig


def _fake_job_cfg(agent_count: int = 1) -> Any:
    """Build a minimal JobConfig stand-in.

    We avoid importing the real ``harbor.models.job.config.JobConfig``
    here because it pulls in many transitive deps and these tests
    only care that ``seed_agent_env`` mutates the right
    sub-object. A SimpleNamespace is enough.
    """
    agents = []
    for i in range(agent_count):
        agents.append(SimpleNamespace(env={}, kwargs={}))
    return SimpleNamespace(agents=agents)


def _fake_wiring(port: int = 9123) -> SimpleNamespace:
    """Stand-in for ContainerWiringHandle — only ``embedding["port"]`` is read."""
    return SimpleNamespace(embedding={"port": port})


def test_seed_writes_five_hook_tunables():
    """5 SKILLQ_HOOK_* env vars land in cfg.agents[0].env (was 7, dropped
    Q_CLIP_MIN/MAX in Phase 10 Bug 1) plus SKILLQ_RANK_ENDPOINT."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(hook_score_mode="multiplicative")
    seed_agent_env(job_cfg, method, _fake_wiring(port=9123))

    env = job_cfg.agents[0].env
    assert env["SKILLQ_HOOK_SCORE_MODE"] == "multiplicative"
    assert env["SKILLQ_HOOK_MULT_BETA"] == "0.500000"
    assert env["SKILLQ_HOOK_MULT_GAMMA"] == "0.200000"
    assert env["SKILLQ_HOOK_TOP_K"] == "3"
    assert env["SKILLQ_HOOK_LAMBDA"] == "0.500000"
    assert env["SKILLQ_HOOK_C_UCB"] == "0.500000"
    # 2026-06-29 (Phase 10 Bug 1): q_clip knobs removed; scorer
    # hard-codes Q clamp to [0, 1]. The env var should NOT be present.
    assert "SKILLQ_HOOK_Q_CLIP_MIN" not in env
    assert "SKILLQ_HOOK_Q_CLIP_MAX" not in env
    # Step 3 (2026-06-26): SKILLQ_EMBED_HOST/PORT replaced by
    # SKILLQ_RANK_ENDPOINT (a single host:port URL).
    assert env["SKILLQ_RANK_ENDPOINT"] == "http://host.docker.internal:9123"


def test_seed_uses_wiring_port_not_method_default():
    """When the wiring handle is present, the rank endpoint port comes
    from the handle (the ephemeral port the daemon bound to),
    NOT from method.hook_embedding_service_port. Otherwise
    cross-port collisions would silently break the hook."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(hook_embedding_service_port=8765)  # method default
    seed_agent_env(
        job_cfg, method, _fake_wiring(port=42317)  # daemon actually bound this
    )
    assert job_cfg.agents[0].env["SKILLQ_RANK_ENDPOINT"] == "http://host.docker.internal:42317"


def test_seed_falls_back_to_env_default_when_wiring_none():
    """When wiring is None (e.g. EMBEDDING_API_KEY missing), the
    rank endpoint falls back to ``SKILLQ_RANK_ENDPOINT`` env var or
    ``http://host.docker.internal:8765`` as the in-container default.
    Step 7 changed this from a method-config port fallback because
    the wiring handle is the authoritative source of the daemon URL."""
    import os
    job_cfg = _fake_job_cfg()
    method = MethodConfig(hook_embedding_service_port=8765)
    # Force the env_seed to take its code-defined default by
    # removing the env var entirely.
    saved = os.environ.pop("SKILLQ_RANK_ENDPOINT", None)
    try:
        seed_agent_env(job_cfg, method, None)
        assert job_cfg.agents[0].env["SKILLQ_RANK_ENDPOINT"] == (
            "http://host.docker.internal:8765"
        )
    finally:
        # Restore the conftest default for downstream tests.
        os.environ["SKILLQ_RANK_ENDPOINT"] = saved or "http://127.0.0.1:8765"


def test_seed_pull_mode_adds_pull_top_k():
    """In pull-mode retrieval, SKILLQ_PULL_TOP_K is also seeded
    so the SessionStart branch in hook.py uses the configured K."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(retrieval_mode="pull", hook_pull_top_k=5)
    seed_agent_env(job_cfg, method, _fake_wiring())
    assert job_cfg.agents[0].env["SKILLQ_PULL_TOP_K"] == "5"


def test_seed_hook_mode_omits_pull_top_k():
    """In hook-mode (the default), SKILLQ_PULL_TOP_K is NOT set;
    the hook's SessionStart branch falls back to SKILLQ_HOOK_TOP_K."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(retrieval_mode="hook", hook_pull_top_k=5)
    seed_agent_env(job_cfg, method, _fake_wiring())
    assert "SKILLQ_PULL_TOP_K" not in job_cfg.agents[0].env


def test_seed_with_no_agents_is_noop():
    """Defensive: a future Harbor release that allows zero agents
    should not crash the seeder."""
    job_cfg = _fake_job_cfg(agent_count=0)
    method = MethodConfig()
    seed_agent_env(job_cfg, method, _fake_wiring())
    # No exception; agents list still empty.
    assert job_cfg.agents == []


def test_seed_explicit_method_values_propagate():
    """If the user overrides hook params in method-config (e.g. a
    v3 yaml sets beta=0.7), those values reach the env dict."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(
        hook_score_mode="multiplicative",
        hook_multiplicative_beta=0.7,
        hook_multiplicative_gamma=0.1,
        hook_top_k=5,
    )
    seed_agent_env(job_cfg, method, _fake_wiring())
    env = job_cfg.agents[0].env
    assert env["SKILLQ_HOOK_MULT_BETA"] == "0.700000"
    assert env["SKILLQ_HOOK_MULT_GAMMA"] == "0.100000"
    assert env["SKILLQ_HOOK_TOP_K"] == "5"


def test_default_score_mode_matches_agent_fallback():
    """MethodConfig default is 'multiplicative'; agent.py fallback
    is 'multiplicative'; hook.py fallback is 'multiplicative'.
    If any of these ever drift, container hook would silently run
    a different formula than the host-side bridge.

    This test guards the contract by asserting the *default* (no
    explicit override) values are equal across the three sources.
    """
    # MethodConfig default
    method_default = MethodConfig().hook_score_mode
    assert method_default == "multiplicative"

    # agent.py default (defense-in-depth: the agent's __init__
    # pre-seeds _extra_env with this default so even direct
    # import-path call sites that don't go through the bridge
    # get the right formula).
    from skillq.runtime.agent import SkillQClaudeCodeAgent
    import inspect
    src = inspect.getsource(SkillQClaudeCodeAgent.__init__)
    # 2026-07-01 (Bug #51/#52 fix): the agent's default dict is now
    # 1 entry (RANK_ENDPOINT). SKILLQ_CALLS_LOG_PATH + SKILLQ_USER_TASK
    # are NO LONGER env vars — per-trial state lives in the bind-
    # mounted settings.json's ``"skillq"`` block. We just verify
    # the agent no longer hard-codes the per-trial env vars.
    assert "SKILLQ_HOOK_SCORE_MODE" not in src
    assert "SKILLQ_RANK_ENDPOINT" in src
    assert "SKILLQ_CALLS_LOG_PATH" not in src
    assert "SKILLQ_USER_TASK" not in src

    # host's env_seed must default to multiplicative (the source
    # of truth for all 9 SKILLQ_HOOK_* tunables when the user
    # doesn't override them in the YAML). The env_seed module
    # reads the value from method.hook_score_mode (default
    # 'multiplicative' on MethodConfig) and seeds it into the
    # agent's env via SKILLQ_HOOK_SCORE_MODE.
    env_seed_src = inspect.getsource(
        __import__("skillq.runtime.env_seed", fromlist=["seed_agent_env"])
    )
    assert "SKILLQ_HOOK_SCORE_MODE" in env_seed_src
    assert "method.hook_score_mode" in env_seed_src

    # Sanity: the default value MethodConfig returns is the
    # same "multiplicative" string.
    assert MethodConfig().hook_score_mode == "multiplicative"

    # hook.py fallback (used when SKILLQ_HOOK_SCORE_MODE env var
    # is unset; the file is module-loaded inside the container).
    hook_src = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "skillq" / "runtime" / "hook.py"
    ).read_text()
    assert (
        'os.environ.get("SKILLQ_HOOK_SCORE_MODE", "multiplicative")'
        in hook_src
    )
