"""Container-side wiring — Step 5 (2026-06-26) refactor.

Replaces :mod:`skillq.runtime.container_wiring`
(886 lines, 6 bind-mounts, 5 path env vars, 2 host→container
embed host:port env vars). The new version is ~250 lines, 2
bind-mounts, 0 path env vars (host owns everything via
``/rank``), 0 host→container embed host:port env vars (one
endpoint, ``SKILLQ_RANK_ENDPOINT``, replaces the legacy pair).

**What changed in Step 5 (vs the legacy container wiring)**:

- **bind-mounts from 6 → 2**: only the hook script + skills
  tree. ``lib.json`` / ``q_table.json`` / ``emb_cache.json``
  are gone — the host owns those in ``MethodServices`` and
  exposes them via ``/rank``. ``settings.json`` is now
  generated on the container's first call (Step 5 falls back
  to a host-generated ``settings.json`` bind mount for
  compatibility, but the host-side can also write
  ``settings.json`` once and bind-mount it as a second
  mount — for now we keep it as a 3rd mount to minimise
  disruption; Step 6's host-side self-healing closes this).
- **No more ``_write_state_files``**: the trial staging dir
  used to host 4 JSON files (lib.json + q_table.json +
  emb_cache.json + calls_log.jsonl). Now we just write the
  per-trial ``method_state.json`` (already done by
  :func:`skillq.runtime.steps.step_save_state`) and the
  host's ``MethodServices`` carries the live snapshot.
- **No more legacy ``start_container_wiring``**: we now use
  :func:`skillq.services.ranking_service.start_ranking_service_background`
  (Step 3) which exposes ``/rank`` + ``/embed`` (back-compat) +
  ``/healthz``. The ranking daemon's ``app.state`` carries
  ``lib`` + ``mgr`` + ``emb_cache`` + ``method``; the bridge's
  ``on_trial_started`` calls
  :func:`skillq.services.ranking_service.inject_ranking_state`
  to refresh it at each trial boundary.
- **No more 5 path env vars**: ``SKILLQ_LIB`` /
  ``SKILLQ_Q_TABLE`` / ``SKILLQ_EMB_CACHE`` / ``SKILLQ_CALLS_LOG``
  / ``SKILLQ_USER_TASK`` are dropped. The hook only needs
  ``SKILLQ_RANK_ENDPOINT`` + the 9 ``SKILLQ_HOOK_*`` /
  ``SKILLQ_SIM_GATE_*`` tunables (single source: the host
  bridge's :func:`skillq.runtime.env_seed.seed_agent_env`).
- **calls log path drops to 1 mount**: the hook writes to
  ``/logs/agent/sessions/skillq_skill_calls.jsonl`` inside the
  container, and Harbor's auto-injected ``agent_dir`` mount
  (``<trial_dir>/agent`` → ``/logs/agent``) makes the file
  visible on the host at the same path with no extra mount.
  Same as the legacy — preserved verbatim.

**ContainerWiringHandle** is now a thin wrapper around the
ranking service's handle (Step 3's
:class:`RankingServiceHandle`) plus the ``MethodServices``
reference (Step 4). Same name as the legacy dataclass so
Step 6's import-replacement doesn't churn the call sites.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TYPE_CHECKING

from skillq.runtime.context import MethodServices
from skillq.services.ranking_service import (
    RankingServiceHandle,
    start_ranking_service_background,
    stop_ranking_service,
)

if TYPE_CHECKING:
    from skillq.config import MethodConfig


logger = logging.getLogger("skillq.runtime.container_wiring")


# ---------------------------------------------------------------------------
# Container-side paths (resolved against $CLAUDE_CONFIG_DIR inside
# the agent container, which SkillsVoteClaudeCode sets to
# /logs/agent/sessions inside the prebuilt image).
# ---------------------------------------------------------------------------
CONTAINER_CLAUDE_CONFIG_DIR = "/logs/agent/sessions"
CONTAINER_HOOK_PATH = f"{CONTAINER_CLAUDE_CONFIG_DIR}/hooks/skillq_skill_hook.py"
CONTAINER_SETTINGS_PATH = f"{CONTAINER_CLAUDE_CONFIG_DIR}/settings.json"
# 2026-06-29 (Phase 10 Bug 5): CONTAINER_CALLS_LOG_PATH is set
# per-trial in ``_wire_hook_trial`` (alongside the RW bind-mount that
# backs it). The previous global constant pointed at
# ``/logs/agent/sessions/skillq_skill_calls.jsonl`` — but the
# prebuilt image's /logs/agent is a docker volume, so writes there
# disappeared when the container stopped.
# Where Claude Code looks for Skill() tool registrations. The
# smoke config sets ``mounts_json`` source: <host>/seed_skills,
# target: /skills — re-bind at the ClaudeCode-standard path so
# the base ``_build_register_skills_command`` cp picks them up.
CONTAINER_SKILLS_DIR = f"{CONTAINER_CLAUDE_CONFIG_DIR}/skills"
CONTAINER_SEED_SKILLS_MOUNT = "/skills"
CONTAINER_HOST_GATEWAY = "host.docker.internal"


@dataclass
class ContainerWiringHandle:
    """Bookkeeping returned by :func:`start_container_wiring`.

    ``ranking`` is the Step-3 ranking daemon handle (carries
    ``thread``, ``server``, ``port``, ``stop_event``). ``method``
    is the parsed MethodConfig. ``services`` is the Step-4
    MethodServices — the host-side live snapshot of lib + mgr
    + emb_cache that the daemon's ``app.state`` mirrors.

    Call :func:`wire_one_trial` on each ``on_trial_started``
    event so the hook script gets re-bind-mounted (the
    per-trial ``settings.json`` may differ). The lib / Q-table
    / emb_cache updates happen via the daemon's
    :func:`inject_ranking_state` call from the bridge's
    ``on_trial_ended`` callback (Step 4's ``step_save_state``).
    """

    ranking: RankingServiceHandle
    method: "MethodConfig"
    services: MethodServices


def start_container_wiring(
    method: "MethodConfig",
    services: MethodServices | None = None,
) -> ContainerWiringHandle | None:
    """Boot the host-side ranking daemon + return the wiring handle.

    Step 5 replaces the legacy ``start_embedding_service_background``
    with the new ranking service (Step 3). The ranking service
    exposes ``/rank`` (the L1 endpoint the container's hook calls)
    + ``/embed`` (backward compat) + ``/healthz`` (ready-wait).

    Returns ``None`` if ``EMBEDDING_API_KEY`` is unset — the
    trial still runs but the per-subtask hook isn't installed
    (Q+UCB-only ranking, no cosine). Production runs always
    set the API key.
    """
    import os

    if not os.environ.get("EMBEDDING_API_KEY"):
        logger.warning(
            "EMBEDDING_API_KEY not set; skipping ranking daemon. "
            "The per-subtask hook will fall back to Q+UCB-only ranking "
            "(no cosine similarity). Set EMBEDDING_API_KEY in .env to "
            "enable the full pipeline."
        )
        return None

    port = method.hook_embedding_service_port
    # Step 5: ranking daemon replaces embed daemon. Same port
    # contract — ``hook_embedding_service_port`` is the legacy
    # name, kept for backward compat with existing method YAMLs.
    ranking = start_ranking_service_background(
        port=port,
        host="0.0.0.0",
        lib=services.lib if services is not None else None,
        mgr=services.mgr if services is not None else None,
        emb_cache=services.emb_cache if services is not None else None,
        method=method if services is not None else None,
    )
    logger.info(
        "Started skillq ranking service on 0.0.0.0:%d (container will "
        "reach it at %s:%d)",
        ranking["port"],
        CONTAINER_HOST_GATEWAY,
        port,
    )
    return ContainerWiringHandle(
        ranking=ranking,
        method=method,
        services=services,  # may be None — caller builds it later
    )


def stop_container_wiring(handle: ContainerWiringHandle | None) -> None:
    """Stop the ranking daemon. Safe to call with None / twice."""
    if handle is None:
        return
    try:
        stop_ranking_service(handle.ranking)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to stop ranking service cleanly; continuing.")
    logger.info("Stopped skillq ranking service")


# ---------------------------------------------------------------------------
# Per-trial setup — drop from 6 mounts to 2 (hook script + skills tree).
# ---------------------------------------------------------------------------
def wire_one_trial(handle: ContainerWiringHandle, event: Any) -> None:
    """Run at ``on_trial_started`` to wire the trial.

    Step 5 behaviour:

    - **Method A (agentic)** — unchanged from legacy: write the
      SKILL.md/manifest/search.sh artifact tree, bind-mount into
      ``$CLAUDE_CONFIG_DIR/<agentic_skill_dir_name>/``. No
      PreToolUse hook installed.
    - **Method B (hook)** — bind-mount ONLY the hook script
      (from ``runtime/hook.py``) + the seed-skills tree at
      the ClaudeCode-standard path. State files (lib.json +
      q_table.json + emb_cache.json) are gone — the host owns
      them via ``MethodServices`` and exposes them via
      ``/rank``. ``settings.json`` is still bind-mounted (the
      host generates it once at job start; we re-use it
      across trials to keep the contract).

    Mutates ``event.config`` in place to add the env vars + bind
    mounts the agent container needs.
    """
    method = handle.method
    trial_dir = _resolve_trial_dir(event)
    cfg = event.config

    # 2026-06-29 (Issue 65): harbor's ``JobConfig.agents[0]`` is a
    # single shared reference across all trials in a job (see
    # ``harbor/job.py:_init_trial_configs``). Mutating
    # ``cfg.agent.env`` in trial N would leak into trial N+1
    # (e.g. SKILLQ_USER_TASK residual pollution). Shallow-copy
    # the env dict here so each trial owns its own. ``cfg.agent``
    # itself stays shared (read-only after Job.create), only the
    # env dict is replaced.
    cfg.agent.env = dict(cfg.agent.env)

    # 1. Resolve the retrieval mode based on the lib size at
    #    this moment. Avoid an import cycle by doing the
    #    resolve inline rather than calling back into bridge.
    n_lib = len(handle.services.lib.skills) if handle.services else 0
    mode = resolve_retrieval_mode(method, n_lib)

    if mode == "agentic":
        _wire_agentic_trial(
            handle=handle,
            event=event,
            trial_dir=trial_dir,
            cfg=cfg,
        )
    else:
        _wire_hook_trial(
            handle=handle,
            event=event,
            trial_dir=trial_dir,
            cfg=cfg,
        )


def resolve_retrieval_mode(method: "MethodConfig", n_lib_skills: int) -> str:
    """Resolve the effective retrieval mode for one trial.

    Copied verbatim from
    :func:`skillq.runtime.bridge.resolve_retrieval_mode`.
    Same semantics so Step 6's import-replacement is a no-op.

    - ``"agentic"`` → Method A. Returned verbatim.
    - ``"hook"``    → Method B (PreToolUse only). Returned verbatim.
    - ``"pull"``    → Method B + SessionStart inject. Returned as
      ``"hook"`` since the wiring is identical except for the
      SessionStart hook in settings.json.
    - ``"auto"``    → picks ``"agentic"`` if the lib is below
      ``method.library_size_threshold``, else ``"hook"``.
    """
    mode = getattr(method, "retrieval_mode", "hook")
    if mode == "auto":
        return "agentic" if n_lib_skills < method.library_size_threshold else "hook"
    if mode == "pull":
        return "hook"
    return mode


# ---------------------------------------------------------------------------
# Method A (agentic) — write skill files, no hook.
# Largely unchanged from the legacy version; the only edit is
# dropping ``SKILLQ_EMBED_HOST`` / ``SKILLQ_EMBED_PORT`` (now
# replaced by ``SKILLQ_RANK_ENDPOINT`` injected by the host's
# env_seed).
# ---------------------------------------------------------------------------
def _wire_agentic_trial(
    *,
    handle: ContainerWiringHandle,
    event: Any,
    trial_dir: Path,
    cfg: Any,
) -> None:
    method = handle.method
    from skillq.runtime.agentic_search import (
        AgenticSearchWriter,
        render_instructions,
    )

    writer = AgenticSearchWriter(
        skills_dir_name=method.agentic_skill_dir_name,
        top_k=method.agentic_search_top_k,
        k_rrf=method.agentic_search_k_rrf,
    )
    staging = trial_dir / method.agentic_skill_dir_name
    writer.write(
        staging_dir=staging,
        lib=handle.services.lib,
        q_for=handle.services.mgr.q_for,
    )

    if cfg.environment.mounts_json is None:
        cfg.environment.mounts_json = []
    mounts = cfg.environment.mounts_json

    skills_target = f"{CONTAINER_CLAUDE_CONFIG_DIR}/{method.agentic_skill_dir_name}"
    mounts.append(_bind_mount(str(staging), skills_target, read_only=True))

    seed_host_src = _seed_skills_host_source(cfg)
    if seed_host_src is not None:
        mounts.append(_bind_mount(seed_host_src, CONTAINER_SKILLS_DIR, read_only=True))

    # uv cache mount (RW) for verifier warm cache — unchanged.
    if method.verifier_uv_cache_path is not None:
        _maybe_mount_uv_cache(cfg, method)

    cfg.agent.env.update(
        {
            "SKILLQ_AGENTIC_SKILLS_DIR": skills_target,
            "SKILLQ_AGENTIC_SEARCH_SCRIPT": f"{skills_target}/_search.sh",
            "SKILLQ_AGENTIC_MANIFEST": f"{skills_target}/_manifest.json",
        }
    )

    claude_md_merged = _mount_merged_claude_md(
        method=method,
        snippet=render_instructions(
            skills_dir_name=method.agentic_skill_dir_name,
            top_k=method.agentic_search_top_k,
        ),
        trial_dir=trial_dir,
        cfg=cfg,
    )
    logger.info(
        "Wired agentic (Method A) for trial %s (lib=%d skills, mounts=%d, "
        "claude_md_merged=%s)",
        event.trial_id,
        len(handle.services.lib.skills),
        len(mounts),
        claude_md_merged,
    )


# ---------------------------------------------------------------------------
# Method B (hook) — bind-mount only the hook script + skills tree.
# State files are gone; the hook talks to /rank instead.
# ---------------------------------------------------------------------------
def _load_task_instruction(method: Any, task_name: str) -> str | None:
    """Read the rich task intent from ``<input_root>/<benchmark>/<task>/instruction.md``.

    The container hook's ``/rank`` query is this string. The previous
    implementation passed just the task slug (e.g. ``"chess-best-move"``,
    ~15 chars) which gave L1 retrieval a very thin query, so even when
    a relevant skill existed in the lib the cosine sim was low
    (~0.4-0.5) and Hard Gate (sim_gate_min_score=0.7) dropped everyone.

    instruction.md is 200-2700 chars and contains the actual task
    description ("The file chess_board.png has an image of a chess
    board...write the best move...") which aligns much better with
    skill descriptions like "given a screenshot of a chess position,
    output the best move". Expected sim boost: 0.4 → 0.7+.

    Returns None when:
    - benchmark_input_path is unset
    - none of the known benchmark subdirs contain the task
    - instruction.md is missing or empty

    In all failure paths, falls back silently to the task slug
    (preserves the previous behavior).
    """
    try:
        input_root = method.resolved_benchmark_input_path()  # bound method
    except Exception:
        return None
    # Common benchmark layouts — try each in turn. We don't know
    # which one this trial belongs to at wiring time.
    for sub in ("terminal-bench", "swebenchpro", "tb-pro", "swebench"):
        candidate = input_root / sub / task_name / "instruction.md"
        try:
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    return text
        except OSError:
            continue
    return None


def _wire_hook_trial(
    *,
    handle: ContainerWiringHandle,
    event: Any,
    trial_dir: Path,
    cfg: Any,
) -> None:
    """Method B wiring: 2 bind-mounts, no state JSONs, no path env vars."""
    method = handle.method

    # 1. Inject path env vars (still per-trial: SKILLQ_USER_TASK +
    #    SKILLQ_CALLS_LOG_PATH are trial-scoped; everything else is
    #    seeded once by env_seed). SKILLQ_CALLS_LOG_PATH is set
    #    further below alongside the RW bind-mount that backs it.
    #
    # 2026-06-29 (Fix A+): SKILLQ_USER_TASK used to be just the task
    # slug (~15 chars like "chess-best-move") which gave L1 sim a
    # very thin query. Now we load the full instruction.md (200-2700
    # chars) when available, falling back to the slug otherwise.
    task_name = event.task_name or trial_dir.name
    intent_text = _load_task_instruction(method, task_name) or task_name
    cfg.agent.env["SKILLQ_USER_TASK"] = intent_text[:2000]

    # 2. Bind mounts: only hook script + skills tree + settings.json.
    if cfg.environment.mounts_json is None:
        cfg.environment.mounts_json = []
    mounts = cfg.environment.mounts_json

    # Settings.json (host-generated once at job start; bind-mounted
    # over the prebuilt image's default).
    settings_path = _settings_json_path(
        trial_dir,
        include_pull=(getattr(method, "retrieval_mode", "hook") == "pull"),
    )
    mounts.append(
        _bind_mount(str(settings_path), CONTAINER_SETTINGS_PATH, read_only=True)
    )

    # Hook script. **Step 5 change**: this points at the new
    # ``skillq/runtime/hook.py`` (~150-line /rank client), not
    # the legacy 547-line stdlib Eq.4 implementation.
    from skillq.runtime.agent import hook_script_path

    hook_host_path = str(hook_script_path())
    mounts.append(_bind_mount(hook_host_path, CONTAINER_HOOK_PATH, read_only=True))

    # Skills tree at the ClaudeCode-standard path.
    seed_host_src = _seed_skills_host_source(cfg)
    if seed_host_src is not None:
        mounts.append(
            _bind_mount(seed_host_src, CONTAINER_SKILLS_DIR, read_only=True)
        )

    # 2026-06-29 (Phase 10 Bug 5): per-trial RW bind-mount for the
    # hook's calls log. The prebuilt image's /logs/agent/sessions/
    # is a docker volume (not host-bound), so writes there disappear
    # when the container stops. /logs/agent/sessions/skills is
    # host-bound but RO. We add a RW mount at a NEW container path
    # — the trial's own log subdir — and point SKILLQ_CALLS_LOG_PATH
    # at it.
    log_mount_host = str(trial_dir / "agent" / "sessions" / "_calls_log")
    log_mount_host_path = Path(log_mount_host)
    log_mount_host_path.mkdir(parents=True, exist_ok=True)
    # The container target is /logs/agent/sessions/_calls_log (a NEW
    # subdir alongside the RO skills/settings/hooks subtree).
    CONTAINER_CALLS_LOG_DIR = f"{CONTAINER_CLAUDE_CONFIG_DIR}/_calls_log"
    CONTAINER_CALLS_LOG_PATH = f"{CONTAINER_CALLS_LOG_DIR}/skillq_skill_calls.jsonl"
    cfg.agent.env["SKILLQ_CALLS_LOG_PATH"] = CONTAINER_CALLS_LOG_PATH
    mounts.append(
        _bind_mount(log_mount_host, CONTAINER_CALLS_LOG_DIR, read_only=False)
    )

    # uv cache mount (RW) for verifier warm cache — unchanged.
    if method.verifier_uv_cache_path is not None:
        _maybe_mount_uv_cache(cfg, method)

    # CLAUDE.md merged snippet (so the agent knows it can call Skill()).
    from skillq.runtime.agentic_search import render_hook_instructions

    snippet = render_hook_instructions()
    if getattr(method, "retrieval_mode", "hook") == "pull":
        # Pull-mode: render Top-K into CLAUDE.md. Re-uses the host
        # ranking daemon (not legacy embed daemon) to score.
        from skillq.runtime.agentic_search import render_pull_recommendation
        from skillq.services.ranking_service import sync_embed

        task_name = event.task_name or trial_dir.name
        try:
            subtask_emb = sync_embed(
                text=task_name, host="127.0.0.1", port=handle.ranking["port"],
            )
        except Exception:
            subtask_emb = None
        # Compute top-k via the host's ranking endpoint instead of
        # importing the legacy scorer inline (the legacy code did
        # ``_score_skills`` in-process; the new code re-uses the
        # same scorer via /rank).
        try:
            import requests
            params = {
                "sim_gate_min_score": method.sim_gate_min_score,
                "sim_gate_floor": method.sim_gate_floor,
                "score_mode": method.hook_score_mode,
                "beta": method.hook_multiplicative_beta,
                "gamma": method.hook_multiplicative_gamma,
                "c_ucb": method.hook_c_ucb,
                "lambda": method.hook_lambda,
                # 2026-06-29 (Phase 10 Bug 1): q_clip_min / q_clip_max
                # removed from the payload; scorer hard-codes Q clamp.
            }
            r = requests.post(
                f"http://127.0.0.1:{handle.ranking['port']}/rank",
                json={
                    "query": task_name,
                    "top_k": method.hook_pull_top_k,
                    "ranking_id": "pull-mode-pre-trial",
                    "params": params,
                },
                timeout=5.0,
            )
            r.raise_for_status()
            top_k = [
                (entry["skill_id"], entry["score"])
                for entry in r.json().get("top_k", [])
            ]
        except Exception:
            top_k = []

        skills_by_id = {
            s.skill_id: {
                "skill_id": s.skill_id,
                "description": "",
                "body": s.body,
            }
            for s in handle.services.lib.skills.values()
        }
        snippet += "\n\n" + render_pull_recommendation(
            task_name=task_name,
            top_k=top_k,
            skills_by_id=skills_by_id,
            lambda_=method.hook_lambda,
            c_ucb=method.hook_c_ucb,
            subtask_emb=subtask_emb,
        )

    _mount_merged_claude_md(method=method, snippet=snippet, trial_dir=trial_dir, cfg=cfg)

    logger.info(
        "Wired hook (Method B) for trial %s (mounts=%d entries, /rank endpoint active)",
        event.trial_id,
        len(mounts),
    )


# ---------------------------------------------------------------------------
# Helpers — extracted from the legacy version, kept identical
# ---------------------------------------------------------------------------
def _settings_json_path(trial_dir: Path, *, include_pull: bool = False) -> Path:
    """Write (or reuse) a settings.json that registers the PreToolUse hook.

    Written once at the first trial's staging dir; reused on
    subsequent trials. The container runs the hook via the same
    Python binary the agent uses.
    """
    from skillq.runtime.agent import hook_settings_json

    settings = hook_settings_json(
        hook_container_path=CONTAINER_HOOK_PATH,
        include_pull=include_pull,
    )
    path = trial_dir / "skillq_state" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def _resolve_trial_dir(event: Any) -> Path:
    """Resolve host path to the trial_dir for this trial."""
    cfg = event.config
    trials_dir = Path(cfg.trials_dir)
    return (trials_dir / cfg.trial_name).resolve()


def _bind_mount(source: str, target: str, read_only: bool) -> dict[str, Any]:
    """Build a mounts_json entry dict."""
    return {
        "type": "bind",
        "source": source,
        "target": target,
        "read_only": read_only,
    }


def _seed_skills_host_source(cfg: Any) -> str | None:
    """Return the host source path of the seed_skills/ mount, or None."""
    mounts = getattr(getattr(cfg, "environment", None), "mounts_json", None) or []
    for m in mounts:
        if not isinstance(m, dict):
            continue
        if m.get("target") == CONTAINER_SEED_SKILLS_MOUNT:
            src = m.get("source")
            if src:
                return str(src)
    return None


def _maybe_mount_uv_cache(cfg: Any, method: Any) -> None:
    """Mount the host uv cache into the container (RW)."""
    if cfg.environment.mounts_json is None:
        cfg.environment.mounts_json = []
    uv_cache_host = Path(method.verifier_uv_cache_path).expanduser().resolve()
    if uv_cache_host.is_dir():
        cfg.environment.mounts_json.append(
            {
                "type": "bind",
                "source": str(uv_cache_host),
                "target": "/root/.cache/uv",
            }
        )
        logger.info(
            "verifier_uv_cache_path mounted: %s -> /root/.cache/uv (RW)",
            uv_cache_host,
        )
    else:
        logger.warning(
            "verifier_uv_cache_path=%s does not exist; skipping mount.",
            uv_cache_host,
        )


def _maybe_merge_user_claude_md(
    *,
    method: Any,
    snippet: str,
    trial_dir: Path,
) -> Path | None:
    """Merge ``snippet`` into the user's CLAUDE.md if set."""
    from skillq.config import MethodConfig

    if not isinstance(method, MethodConfig):
        return None
    user_path = method.user_claude_md_path
    if user_path is None:
        return None
    if user_path.exists():
        existing = user_path.read_text(encoding="utf-8", errors="replace")
    else:
        existing = ""
    separator = "\n\n" if existing and not existing.endswith("\n") else "\n"
    merged = (
        existing
        + (separator if existing else "")
        + "# --- appended by mg skillq-method bridge ---\n"
        + snippet
    )
    merged_path = trial_dir / "CLAUDE.md.merged"
    merged_path.write_text(merged, encoding="utf-8")
    return merged_path


def _mount_merged_claude_md(
    *,
    method: Any,
    snippet: str,
    trial_dir: Path,
    cfg: Any,
) -> bool:
    """Merge ``snippet`` into CLAUDE.md and bind-mount it."""
    merged = _maybe_merge_user_claude_md(method=method, snippet=snippet, trial_dir=trial_dir)
    if merged is None:
        return False
    if cfg.environment.mounts_json is None:
        cfg.environment.mounts_json = []
    cfg.environment.mounts_json.append(
        _bind_mount(
            str(merged),
            f"{CONTAINER_CLAUDE_CONFIG_DIR}/CLAUDE.md",
            read_only=True,
        )
    )
    return True


__all__ = [
    "ContainerWiringHandle",
    "start_container_wiring",
    "stop_container_wiring",
    "wire_one_trial",
    "resolve_retrieval_mode",
    "CONTAINER_CLAUDE_CONFIG_DIR",
    "CONTAINER_HOOK_PATH",
    "CONTAINER_SETTINGS_PATH",
    "CONTAINER_CALLS_LOG_PATH",
    "CONTAINER_HOST_GATEWAY",
]