"""Container-side wiring for the per-subtask hook (issue #2) and
Method A (agentic) artifacts.

This module is the glue between:

- the **host-side bridge** (`bridge.attach_paper_registers`,
  `bridge.run_paper_job`),
- the **embed daemon** (`paper.method.embedding_service`),
- the **per-subtask hook** running inside the agent container
  (`paper.paper_mode.hook`), and
- Harbor's per-trial lifecycle hooks (`on_trial_started`).

At Job start we spin up one host-side FastAPI daemon that serves
``POST /embed`` for the duration of the run. For each trial the
mode is resolved (see ``paper.paper_mode.bridge.resolve_retrieval_mode``)
and the wiring branches:

- **Method A (agentic)** — write the SKILL.md/manifest/search.sh
  artifact tree, bind-mount it into
  ``$CLAUDE_CONFIG_DIR/<agentic_skill_dir_name>/``, inject
  ``SKILLQ_AGENTIC_*`` env vars. No PreToolUse hook is installed.
- **Method B (hook)** — re-dump the live Q-table, library, and
  emb-cache to the trial directory so the container can read them
  via a bind mount. Push the ``SKILLQ_*`` env vars (paths, host:port,
  tunables) into ``event.config.agent.env`` so the hook script
  picks them up. Bind-mount the hook script + a generated
  ``settings.json`` + the state files + the calls log into the
  container at the paths ``paper.paper_mode.hook`` reads from.
  Reset the ``skillq_skill_calls.jsonl`` for the new trial.

The TrialHookEvent's config is a Pydantic model — we mutate it in
place, which is fine because Harbor copies the config when
constructing each ``Trial``.

See ``paper/paper_mode/bridge.py:run_paper_job`` for the entry
point.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from skillq.method.embedding_service import (
    EmbeddingServiceHandle,
    start_embedding_service_background,
    stop_embedding_service,
)
from skillq.method.library import LibManager
from skillq.method.state import QlibState
from skillq.method.types import Qlib
from skillq.method.vector_table import VectorTable
from skillq.paper_mode.agent import (
    hook_env,
    hook_script_path,
    hook_settings_json,
)
from skillq.paper_mode.config import MethodConfig

logger = logging.getLogger("paper.paper_mode.container_wiring")

# Container-side paths (resolved against the agent's $CLAUDE_CONFIG_DIR,
# which SkillsVoteClaudeCode sets to /logs/agent/sessions inside the
# prebuilt image).
CONTAINER_CLAUDE_CONFIG_DIR = "/logs/agent/sessions"
CONTAINER_HOOK_PATH = f"{CONTAINER_CLAUDE_CONFIG_DIR}/hooks/skillq_skill_hook.py"
CONTAINER_SETTINGS_PATH = f"{CONTAINER_CLAUDE_CONFIG_DIR}/settings.json"
CONTAINER_LIB_PATH = f"{CONTAINER_CLAUDE_CONFIG_DIR}/skillq_lib.json"
CONTAINER_Q_TABLE_PATH = f"{CONTAINER_CLAUDE_CONFIG_DIR}/skillq_q_table.json"
CONTAINER_EMB_CACHE_PATH = f"{CONTAINER_CLAUDE_CONFIG_DIR}/skillq_emb_cache.json"
CONTAINER_CALLS_LOG_PATH = f"{CONTAINER_CLAUDE_CONFIG_DIR}/skillq_skill_calls.jsonl"
# Where Claude Code looks for Skill() tool registrations. We re-bind
# the host's seed_skills/ tree here so the base ClaudeCode agent's
# ``_build_register_skills_command`` (which does
# ``cp -r $skills_dir/* $CLAUDE_CONFIG_DIR/skills/`` at setup time)
# picks them up. The Skill tool's "available skills" list consumes
# exactly this path. Without this, the 32 seed skills sit at /skills
# in the container but are invisible to the agent.
CONTAINER_SKILLS_DIR = f"{CONTAINER_CLAUDE_CONFIG_DIR}/skills"
# Where the host's seed_skills/ tree is mounted in the container
# (the smoke config sets ``mounts_json`` source: <host>/seed_skills,
# target: /skills). The Plan A fix re-exposes the same host source at
# CONTAINER_SKILLS_DIR so the base ClaudeCode picks the skills up via
# its standard register-skills path.
CONTAINER_SEED_SKILLS_MOUNT = "/skills"
CONTAINER_HOST_GATEWAY = "host.docker.internal"


@dataclass
class ContainerWiringHandle:
    """Bookkeeping returned by :func:`start_container_wiring`.

    Pass to :func:`wire_one_trial` on each ``on_trial_started`` event.
    Call :func:`stop_container_wiring` after ``job.run`` returns.
    """

    embedding: EmbeddingServiceHandle
    method: MethodConfig
    # Snapshot of (lib, mgr) the bridge maintains — we re-read
    # from disk on each trial (in case a previous on_ended updated
    # them), so we don't carry mutable references here.
    library_root: Path
    state_path: Path


def start_container_wiring(method: MethodConfig) -> ContainerWiringHandle | None:
    """Spin up the host-side embed daemon and return the wiring handle.

    Returns ``None`` if ``EMBEDDING_API_KEY`` is not set in the
    environment — the smoke / unit tests can run with the hook
    installed (and the container's hook will fall back to
    Q+UCB-only ranking when the embedding service is unreachable).
    Production runs should always set the API key.

    The daemon is started eagerly (not lazily on first request) so
    that the host:port is known by the time we wire the first
    trial.
    """
    import os

    if not os.environ.get("EMBEDDING_API_KEY"):
        logger.warning(
            "EMBEDDING_API_KEY not set; skipping embedding daemon. "
            "The per-subtask hook will fall back to Q+UCB-only ranking "
            "(no cosine similarity). Set EMBEDDING_API_KEY in .env to "
            "enable the full pipeline."
        )
        return None

    port = method.hook_embedding_service_port
    host = method.hook_embedding_service_host or CONTAINER_HOST_GATEWAY
    embedding = start_embedding_service_background(port=port, host="0.0.0.0")
    logger.info(
        "Started mg embedding service on 0.0.0.0:%d (container will reach it as %s:%d)",
        embedding["port"],
        host,
        port,
    )
    return ContainerWiringHandle(
        embedding=embedding,
        method=method,
        library_root=method.library_root,
        state_path=method.resolved_state_path(),
    )


def stop_container_wiring(handle: ContainerWiringHandle | None) -> None:
    """Stop the embed daemon and release resources.

    Safe to call with ``None`` (no-op).
    """
    if handle is None:
        return
    try:
        stop_embedding_service(handle.embedding)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to stop embedding service cleanly; continuing.")
    logger.info("Stopped mg embedding service")


# ---------------------------------------------------------------------------
# Per-trial setup
# ---------------------------------------------------------------------------
def _write_state_files(
    trial_dir: Path,
    lib: Qlib,
    mgr: LibManager,
    emb_cache: VectorTable,
) -> tuple[Path, Path, Path, Path]:
    """Write lib / q-table / emb-cache to a staging dir for this trial.

    Returns the four paths (host-side) the bridge should bind-mount
    into the container.

    Layout under ``<trial_dir>/skillq_state/``:

    - ``lib.json``        — list of {skill_id, description, body, n_*}
    - ``q_table.json``    — {skill_id: q}
    - ``emb_cache.json``  — {skill_id: [vec]}
    - ``calls_log.jsonl`` — empty (reset for this trial); the hook appends
    """
    staging = trial_dir / "skillq_state"
    staging.mkdir(parents=True, exist_ok=True)

    lib_path = staging / "lib.json"
    q_path = staging / "q_table.json"
    emb_path = staging / "emb_cache.json"

    # lib.json — list of skills with description (the hook only
    # needs the body and id, but we include description for
    # debuggability).
    lib_path.write_text(
        json.dumps(
            {
                "skills": [
                    {
                        "skill_id": s.skill_id,
                        "body": s.body,
                        "n_retrievals": s.n_retrievals,
                    }
                    for s in lib.skills.values()
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # q_table.json
    q_path.write_text(
        json.dumps(dict(mgr.q_table), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # emb_cache.json
    emb_path.write_text(
        json.dumps(
            {"embeddings": {sid: vec.tolist() for sid, vec in emb_cache.embeddings.items()}},
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    # calls_log.jsonl — we no longer stage this file ourselves.
    # The hook writes directly to
    # ``/logs/agent/sessions/skillq_skill_calls.jsonl`` inside the
    # container, and Harbor's auto-injected ``agent_dir`` bind
    # mount (``trial_dir/agent`` → ``/logs/agent``) makes the
    # write visible on the host at the same path with no extra
    # mount. This sidesteps Bug 2: the old approach used a custom
    # ``read_only=False`` bind mount that violated Harbor's
    # ``ServiceVolumeConfig.read_only: Literal[True]`` TypedDict,
    # so any path that re-validated the saved ``result.json``
    # (e.g. ``--resume``) crashed on Pydantic ``literal_error``.
    calls_log_path = (trial_dir / "agent" / "sessions"
                      / "skillq_skill_calls.jsonl")

    return lib_path, q_path, emb_path, calls_log_path


def _settings_json_path(staging: Path) -> Path:
    """Write a settings.json that registers the PreToolUse hook.

    The container runs the hook via the same Python binary the agent
    uses; we point at the bound-mount location of the script.
    """
    settings = hook_settings_json(hook_container_path=CONTAINER_HOOK_PATH)
    path = staging / "settings.json"
    path.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def wire_one_trial(handle: ContainerWiringHandle, event: Any) -> None:
    """Run at ``on_trial_started`` to wire the trial.

    Dispatches based on the resolved retrieval mode
    (see :func:`paper.paper_mode.bridge.resolve_retrieval_mode`):

    - ``"agentic"`` (Method A) — write the SKILL.md/manifest/search.sh
      artifact tree into a staging dir, bind-mount it into the
      container at ``$CLAUDE_CONFIG_DIR/<agentic_skill_dir_name>/``,
      and add a CLAUDE.md snippet that teaches the agent how to use
      ``_search.sh``. **No PreToolUse hook is installed.**

    - ``"hook"`` (Method B) — write the lib/q-table/emb-cache JSONs,
      bind-mount the hook script + settings.json, inject SKILLQ_*
      env vars. The PreToolUse hook is registered on the agent's
      settings.json.

    Mutates ``event.config`` in place to add the env vars and bind
    mounts the agent container needs. Re-dumps state fresh from
    disk so the trial reads the latest Q-table.
    """
    method = handle.method
    trial_dir = _resolve_trial_dir(event)

    # 1. Reload state from disk — on_ended may have updated it
    #    since attach_paper_registers was first called.
    lib = Qlib(b_max=method.b_max)
    mgr = LibManager(
        b_max=method.b_max,
        q_clip_floor=method.q_clip_floor,
        q_clip_ceiling=method.q_clip_ceiling,
    )
    QlibState(handle.state_path).load_into(lib, mgr, lib_root=method.library_root)
    emb_cache = VectorTable(handle.state_path.parent / "emb_cache.json")
    emb_cache.load()

    # 2. Resolve the retrieval mode based on the lib size at this
    #    moment. (avoid an import cycle by doing the resolve inline
    #    rather than calling back into bridge.)
    from skillq.paper_mode.bridge import resolve_retrieval_mode  # late import
    n_lib = len(lib.skills)
    mode = resolve_retrieval_mode(method, n_lib)

    if mode == "agentic":
        _wire_agentic_trial(
            handle=handle,
            event=event,
            trial_dir=trial_dir,
            lib=lib,
            mgr=mgr,
        )
    else:
        _wire_hook_trial(
            handle=handle,
            event=event,
            trial_dir=trial_dir,
            lib=lib,
            mgr=mgr,
        )


# ---------------------------------------------------------------------------
# Method A (agentic) — write skill files, no hook
# ---------------------------------------------------------------------------
def _wire_agentic_trial(
    *,
    handle: ContainerWiringHandle,
    event: Any,
    trial_dir: Path,
    lib: Qlib,
    mgr: LibManager,
) -> None:
    method = handle.method
    from skillq.paper_mode.agentic_search import (
        AgenticSearchWriter,
        render_instructions,
    )

    writer = AgenticSearchWriter(
        skills_dir_name=method.agentic_skill_dir_name,
        top_k=method.agentic_search_top_k,
        k_rrf=method.agentic_search_k_rrf,
    )
    staging = trial_dir / method.agentic_skill_dir_name
    writer.write(staging_dir=staging, lib=lib, q_for=mgr.q_for)

    cfg = event.config
    if cfg.environment.mounts_json is None:
        cfg.environment.mounts_json = []
    mounts = cfg.environment.mounts_json

    # Skills dir at $CLAUDE_CONFIG_DIR/<agentic_skill_dir_name>/
    skills_target = f"{CONTAINER_CLAUDE_CONFIG_DIR}/{method.agentic_skill_dir_name}"
    mounts.append(
        _bind_mount(str(staging), skills_target, read_only=True)
    )

    # Plan A fix: also bind-mount the host's seed_skills/ tree at the
    # base ClaudeCode ``$CLAUDE_CONFIG_DIR/skills`` path so the
    # ``Skill`` tool sees the curated skills. The base class's
    # ``_build_register_skills_command`` does
    # ``cp -r $skills_dir/* $CLAUDE_CONFIG_DIR/skills/`` at agent
    # setup time; with this mount, that cp picks up the same 32
    # skills the paper method's library already knows about.
    seed_host_src = _seed_skills_host_source(cfg)
    if seed_host_src is not None:
        mounts.append(
            _bind_mount(
                str(seed_host_src),
                CONTAINER_SKILLS_DIR,
                read_only=True,
            )
        )

    # Inject env vars the search script can use (path, host:port).
    cfg.agent.env.update(
        {
            "SKILLQ_AGENTIC_SKILLS_DIR": skills_target,
            "SKILLQ_AGENTIC_SEARCH_SCRIPT": f"{skills_target}/_search.sh",
            "SKILLQ_AGENTIC_MANIFEST": f"{skills_target}/_manifest.json",
            "SKILLQ_EMBED_HOST": method.hook_embedding_service_host or CONTAINER_HOST_GATEWAY,
            "SKILLQ_EMBED_PORT": str(handle.embedding["port"]),
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
        len(lib.skills),
        len(mounts),
        claude_md_merged,
    )


def _maybe_merge_user_claude_md(
    *,
    method: "MethodConfig",
    snippet: str,
    trial_dir: Path,
) -> Path | None:
    """If ``method.user_claude_md_path`` is set, append the snippet to
    the user's CLAUDE.md and return the path of the merged file.
    Returns ``None`` when no merge was performed.
    """
    from skillq.paper_mode.config import MethodConfig

    if not isinstance(method, MethodConfig):
        return None
    user_path = method.user_claude_md_path
    if user_path is None:
        return None

    # Read existing content (if any). If the user's file doesn't
    # exist, treat the merge as a clean write.
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
    logger.info(
        "Merged skillq-method snippet into user CLAUDE.md (%d chars → %d chars)",
        len(existing),
        len(merged),
    )
    return merged_path


def _mount_merged_claude_md(
    *,
    method: "MethodConfig",
    snippet: str,
    trial_dir: Path,
    cfg: Any,
) -> bool:
    """Merge ``snippet`` into the user's CLAUDE.md and bind-mount the
    merged result at ``$CONTAINER_CLAUDE_CONFIG_DIR/CLAUDE.md``.

    Shared helper for both ``_wire_agentic_trial`` and
    ``_wire_hook_trial`` — without it, hook mode silently fails
    because the agent has no awareness that curated skills or the
    Skill tool exist (the hook is installed and ready to intercept,
    but no ``Skill()`` call ever arrives).

    Returns True if a mount was added. The merged file is written
    to ``<trial_dir>/CLAUDE.md.merged``; if the user already had a
    CLAUDE.md at ``method.user_claude_md_path``, the snippet is
    appended under a "--- appended by mg skillq-method bridge ---"
    header. When ``user_claude_md_path`` is None the function is a
    no-op (the snippet remains discoverable in
    ``<skills_dir>/PAPER_METHOD_INSTRUCTIONS.md``).
    """
    merged = _maybe_merge_user_claude_md(
        method=method, snippet=snippet, trial_dir=trial_dir
    )
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


# ---------------------------------------------------------------------------
# Method B (hook) — write state files, install hook
# ---------------------------------------------------------------------------
def _wire_hook_trial(
    *,
    handle: ContainerWiringHandle,
    event: Any,
    trial_dir: Path,
    lib: Qlib,
    mgr: LibManager,
) -> None:
    method = handle.method

    # 1. Reload the emb_cache (we already reloaded in wire_one_trial,
    #    but this function is the only one that uses it for the hook
    #    JSON write; redo it here for clarity).
    emb_cache = VectorTable(handle.state_path.parent / "emb_cache.json")
    emb_cache.load()

    # 2. Write the state files for this trial.
    lib_path, q_path, emb_path, calls_log_path = _write_state_files(
        trial_dir, lib, mgr, emb_cache
    )
    settings_path = _settings_json_path(lib_path.parent)

    # 2. Build the hook env (read every tunable from MethodConfig).
    port = handle.embedding["port"]
    task_name = event.task_name or trial_dir.name
    env = hook_env(
        lib_path=lib_path,
        q_table_path=q_path,
        emb_cache_path=emb_path,
        calls_log_path=calls_log_path,
        embed_host=method.hook_embedding_service_host or CONTAINER_HOST_GATEWAY,
        embed_port=port,
        user_task=task_name,
        top_k=method.hook_top_k,
        lambda_=method.hook_lambda,
        c_ucb=method.hook_c_ucb,
    )

    # 3. Inject env into the trial's agent config.
    cfg = event.config
    cfg.agent.env.update(env)

    # 4. Add bind mounts for the state files + hook script + settings.
    if cfg.environment.mounts_json is None:
        cfg.environment.mounts_json = []
    mounts = cfg.environment.mounts_json
    # State files
    mounts.append(_bind_mount(str(lib_path), CONTAINER_LIB_PATH, read_only=True))
    mounts.append(_bind_mount(str(q_path), CONTAINER_Q_TABLE_PATH, read_only=True))
    mounts.append(_bind_mount(str(emb_path), CONTAINER_EMB_CACHE_PATH, read_only=True))
    # calls_log is intentionally NOT mounted here. Harbor's
    # ``agent_dir`` bind mount (``trial_dir/agent`` → ``/logs/agent``,
    # see harbor/trial/trial.py:_agent_env_mounts) already exposes
    # ``/logs/agent/sessions/`` as a read-write directory inside the
    # container. The hook writes to
    # ``$CONTAINER_CALLS_LOG_PATH`` (i.e.
    # ``/logs/agent/sessions/skillq_skill_calls.jsonl``) and the write
    # shows up on the host at
    # ``trial_dir/agent/sessions/skillq_skill_calls.jsonl`` with no
    # extra mount. This sidesteps Bug 2: the previous
    # ``read_only=False`` mount violated Harbor's
    # ``ServiceVolumeConfig.read_only: Literal[True]`` TypedDict and
    # broke ``--resume`` (Pydantic re-validated the saved
    # ``result.json`` and crashed on ``literal_error``).
    # Settings.json (the container's settings.json — mounted over the
    # prebuilt image's default).
    mounts.append(_bind_mount(str(settings_path), CONTAINER_SETTINGS_PATH, read_only=True))
    # Hook script (the Python file the PreToolUse will exec).
    hook_host_path = str(hook_script_path())
    mounts.append(_bind_mount(hook_host_path, CONTAINER_HOOK_PATH, read_only=True))
    # Plan A fix: bind-mount the host's seed_skills/ tree at the base
    # ClaudeCode ``$CLAUDE_CONFIG_DIR/skills`` path. Without this, the
    # base class's ``_build_register_skills_command`` cp has nothing
    # to copy and the agent's ``Skill`` tool sees no curated skills —
    # so the agent never makes any Skill() calls and the hook never
    # fires. We use the same host source as the smoke config's
    # ``/skills`` mount, just re-exposed at the ClaudeCode-standard
    # path inside the container.
    seed_host_src = _seed_skills_host_source(cfg)
    if seed_host_src is not None:
        mounts.append(
            _bind_mount(
                str(seed_host_src),
                CONTAINER_SKILLS_DIR,
                read_only=True,
            )
        )

    # Inject the same skillq-method CLAUDE.md snippet the agentic
    # path uses, so the agent knows it can call Skill(...). Without
    # this, hook mode silently fails because the agent has no
    # awareness that curated skills or the Skill tool exist (the
    # hook is installed and ready to intercept, but no Skill() call
    # ever arrives). The merged file is appended to the user's
    # existing CLAUDE.md via user_claude_md_path, or written fresh
    # to trial_dir/CLAUDE.md.merged if that path is unset (the
    # helper falls back gracefully).
    from skillq.paper_mode.agentic_search import render_hook_instructions

    _mount_merged_claude_md(
        method=method,
        snippet=render_hook_instructions(),
        trial_dir=trial_dir,
        cfg=cfg,
    )

    logger.info(
        "Wired hook (Method B) for trial %s (env: %d vars, mounts: %d entries)",
        event.trial_id,
        len(env),
        len(mounts),
    )


def _resolve_trial_dir(event: Any) -> Path:
    """Return the host path to the trial_dir for this trial.

    Tries the trial config's ``trials_dir`` first, then falls back to
    ``output/<job_name>/<trial_name>`` matching the harbor convention.

    The returned path is resolved to an absolute path so docker
    compose's mount-source resolution always finds the file (compose
    resolves relative ``source`` paths against the compose file's
    own directory, which is not the cwd the bridge ran from).
    """
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
    """Return the host source path of the seed_skills/ mount, or None.

    The Plan A fix needs to re-bind the *same* host directory (where
    the curated 32 SKILL.md files live) at a different container path
    (``$CLAUDE_CONFIG_DIR/skills``). Detection rule: any mount with
    container target == ``/skills``; we return its source verbatim so
    the host can resolve it as a real path. We deliberately do NOT
    re-use ``/skills`` as the source — docker compose interprets a
    ``source`` as a host path, not a container path, so a container
    path would resolve to ``/skills`` on the host (likely empty or
    non-existent), which is the bug we hit on the first attempt.
    """
    mounts = getattr(getattr(cfg, "environment", None), "mounts_json", None) or []
    for m in mounts:
        if not isinstance(m, dict):
            continue
        if m.get("target") == CONTAINER_SEED_SKILLS_MOUNT:
            src = m.get("source")
            if src:
                return str(src)
    return None


__all__ = [
    "ContainerWiringHandle",
    "start_container_wiring",
    "stop_container_wiring",
    "wire_one_trial",
    "CONTAINER_CLAUDE_CONFIG_DIR",
    "CONTAINER_HOOK_PATH",
    "CONTAINER_SETTINGS_PATH",
    "CONTAINER_LIB_PATH",
    "CONTAINER_Q_TABLE_PATH",
    "CONTAINER_EMB_CACHE_PATH",
    "CONTAINER_CALLS_LOG_PATH",
    "CONTAINER_HOST_GATEWAY",
]
