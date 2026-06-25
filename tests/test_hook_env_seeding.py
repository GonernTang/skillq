"""Unit tests for the bridge's hook-env pre-seeding (2026-06-25).

The container-side hook reads 7 SKILLQ_HOOK_* env vars to decide:
  - which scoring formula to use (additive vs multiplicative)
  - the UCB / Q-mix weights
  - the Hard Gate threshold

These vars MUST reach the agent's _extra_env before Trial.create
snapshots config.env (Harbor's AgentFactory copies config.env to
agent._extra_env at construction time; later mutations are
invisible). The bridge's ``_seed_agent_hook_env`` runs in
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

from skillq.skillq_runtime.bridge import _seed_agent_hook_env
from skillq.skillq_runtime.config import MethodConfig


def _fake_job_cfg(agent_count: int = 1) -> Any:
    """Build a minimal JobConfig stand-in.

    We avoid importing the real ``harbor.models.job.config.JobConfig``
    here because it pulls in many transitive deps and these tests
    only care that ``_seed_agent_hook_env`` mutates the right
    sub-object. A SimpleNamespace is enough.
    """
    agents = []
    for i in range(agent_count):
        agents.append(SimpleNamespace(env={}, kwargs={}))
    return SimpleNamespace(agents=agents)


def _fake_wiring(port: int = 9123) -> SimpleNamespace:
    """Stand-in for ContainerWiringHandle — only ``embedding["port"]`` is read."""
    return SimpleNamespace(embedding={"port": port})


def test_seed_writes_seven_hook_tunables():
    """All 7 SKILLQ_HOOK_* env vars land in cfg.agents[0].env with
    the method-config values, plus SKILLQ_EMBED_HOST/PORT."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(hook_score_mode="multiplicative")
    _seed_agent_hook_env(job_cfg, method, _fake_wiring(port=9123))

    env = job_cfg.agents[0].env
    assert env["SKILLQ_HOOK_SCORE_MODE"] == "multiplicative"
    assert env["SKILLQ_HOOK_MULT_BETA"] == "0.500000"
    assert env["SKILLQ_HOOK_MULT_GAMMA"] == "0.200000"
    assert env["SKILLQ_HOOK_Q_CLIP_MIN"] == "0.000000"
    assert env["SKILLQ_HOOK_Q_CLIP_MAX"] == "1.000000"
    assert env["SKILLQ_HOOK_TOP_K"] == "3"
    assert env["SKILLQ_HOOK_LAMBDA"] == "0.500000"
    assert env["SKILLQ_HOOK_C_UCB"] == "0.500000"
    assert env["SKILLQ_EMBED_HOST"] == "host.docker.internal"
    assert env["SKILLQ_EMBED_PORT"] == "9123"


def test_seed_uses_wiring_port_not_method_default():
    """When the wiring handle is present, the embed port comes
    from the handle (the ephemeral port the daemon bound to),
    NOT from method.hook_embedding_service_port. Otherwise
    cross-port collisions would silently break the hook."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(hook_embedding_service_port=8765)  # method default
    _seed_agent_hook_env(
        job_cfg, method, _fake_wiring(port=42317)  # daemon actually bound this
    )
    assert job_cfg.agents[0].env["SKILLQ_EMBED_PORT"] == "42317"


def test_seed_falls_back_to_method_port_when_wiring_none():
    """When wiring is None (e.g. EMBEDDING_API_KEY missing), the
    embed port falls back to the method-config-declared port."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(hook_embedding_service_port=8765)
    _seed_agent_hook_env(job_cfg, method, None)
    assert job_cfg.agents[0].env["SKILLQ_EMBED_PORT"] == "8765"


def test_seed_pull_mode_adds_pull_top_k():
    """In pull-mode retrieval, SKILLQ_PULL_TOP_K is also seeded
    so the SessionStart branch in hook.py uses the configured K."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(retrieval_mode="pull", hook_pull_top_k=5)
    _seed_agent_hook_env(job_cfg, method, _fake_wiring())
    assert job_cfg.agents[0].env["SKILLQ_PULL_TOP_K"] == "5"


def test_seed_hook_mode_omits_pull_top_k():
    """In hook-mode (the default), SKILLQ_PULL_TOP_K is NOT set;
    the hook's SessionStart branch falls back to SKILLQ_HOOK_TOP_K."""
    job_cfg = _fake_job_cfg()
    method = MethodConfig(retrieval_mode="hook", hook_pull_top_k=5)
    _seed_agent_hook_env(job_cfg, method, _fake_wiring())
    assert "SKILLQ_PULL_TOP_K" not in job_cfg.agents[0].env


def test_seed_with_no_agents_is_noop():
    """Defensive: a future Harbor release that allows zero agents
    should not crash the seeder."""
    job_cfg = _fake_job_cfg(agent_count=0)
    method = MethodConfig()
    _seed_agent_hook_env(job_cfg, method, _fake_wiring())
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
    _seed_agent_hook_env(job_cfg, method, _fake_wiring())
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
    from skillq.skillq_runtime.agent import SkillQClaudeCodeAgent
    import inspect
    src = inspect.getsource(SkillQClaudeCodeAgent.__init__)
    assert '"SKILLQ_HOOK_SCORE_MODE": "multiplicative"' in src

    # hook.py fallback (used when SKILLQ_HOOK_SCORE_MODE env var
    # is unset; the file is module-loaded inside the container).
    hook_src = (
        __import__("pathlib").Path(__file__).resolve().parent.parent
        / "skillq" / "skillq_runtime" / "hook.py"
    ).read_text()
    assert (
        'os.environ.get("SKILLQ_HOOK_SCORE_MODE", "multiplicative")'
        in hook_src
    )
