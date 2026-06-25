"""``SkillQClaudeCodeAgent`` — direct subclass of Harbor's
:class:`harbor.agents.installed.claude_code.ClaudeCode` for paper mode.

This agent does **not** inherit from the vendored
``skills_vote.harbor.claude_code.SkillsVoteClaudeCode`` — it
deliberately drops the recommend-step (the SkillQ method uses a
container-side PreToolUse hook for ranking instead of in-prompt
recommendation). All the per-subtask hook wiring (embed daemon
lifecycle, state dump, ``SKILLQ_*`` env injection, bind mounts)
is owned by the bridge in :mod:`skillq.skillq_runtime.container_wiring`.
The agent class only exists because Harbor's :class:`Job` looks
up the agent by ``import_path`` (e.g.
``skillq.skillq_runtime.agent:SkillQClaudeCodeAgent``).

The legacy alias :class:`PaperClaudeCodeAgent` is kept for
backwards compatibility with experiment YAML configs that still
reference the old name.

This module also hosts the **container-side hook helpers**
(``hook_env`` / ``hook_settings_json`` / ``hook_script_path``) that
both the bridge and the container-wiring module import.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harbor.agents.installed.claude_code import ClaudeCode

if TYPE_CHECKING:  # pragma: no cover
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext

logger = logging.getLogger("skillq.skillq_runtime.agent")


# Where the hook source script lives on the host. The container
# bind-mounts this file into ``$CLAUDE_CONFIG_DIR/hooks/`` and
# references it from settings.json.
_HOOK_SCRIPT_HOST_PATH = Path(__file__).parent / "hook.py"


class SkillQClaudeCodeAgent(ClaudeCode):
    """Direct Harbor ``ClaudeCode`` subclass for ``skillq paper run``.

    All per-trial wiring happens in
    :func:`skillq.skillq_runtime.container_wiring.wire_one_trial` (env
    vars, bind mounts, settings.json) before this agent's run loop
    is invoked. This class is intentionally minimal: it adds no
    recommend step, no skill whitelisting, no plugin-dir handling
    — the PreToolUse hook in :mod:`skillq.skillq_runtime.hook` does
    the retrieval ranking instead.

    The :meth:`setup` override mirrors
    ``skills_vote.harbor.claude_code.SkillsVoteClaudeCode.setup``:
    it skips Harbor's default ``curl https://claude.ai/install.sh``
    install path (which fails for offline / prebuilt images) and
    instead just verifies the preinstalled CLI with
    ``claude --version``. Required because every
    ``skills_vote/<task>:<tag>`` prebuilt image already has the
    Claude Code CLI baked in.
    """

    @staticmethod
    def name() -> str:
        return "SkillQClaudeCodeAgent"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Inject the SKILLQ_* env vars that the hook reads into
        # ``self._extra_env`` so they actually reach the agent's
        # process. The bridge updates ``cfg.agent.env`` at
        # ``on_trial_started`` time, but Harbor's ``AgentFactory``
        # already snapshotted ``config.env`` into ``extra_env`` at
        # agent-construction time (which happens BEFORE
        # ``on_trial_started`` fires), so the bridge's later
        # update is invisible to the base class. By writing to
        # ``self._extra_env`` here at __init__ time we go through
        # the standard ``BaseInstalledAgent._exec`` merge path so
        # every ``exec_as_agent`` call carries the SKILLQ_* vars
        # to the agent's bash.
        #
        # The container-side paths are FIXED — they are bind-mount
        # targets set by ``_wire_hook_trial`` — so we can hardcode
        # them here. The container import is deferred to avoid a
        # circular import (container_wiring imports back from this
        # module for the hook helpers).
        from skillq.skillq_runtime.container_wiring import (
            CONTAINER_CALLS_LOG_PATH,
            CONTAINER_EMB_CACHE_PATH,
            CONTAINER_LIB_PATH,
            CONTAINER_Q_TABLE_PATH,
        )

        super().__init__(*args, **kwargs)

        # Merge SKILLQ_* into ``self._extra_env`` (created by
        # BaseInstalledAgent.__init__). Don't clobber anything
        # already in there (e.g. from the bridge's late updates).
        #
        # 2026-06-25: the 5 ``SKILLQ_HOOK_SCORE_MODE`` /
        # ``SKILLQ_HOOK_MULT_*`` / ``SKILLQ_HOOK_Q_CLIP_*`` keys
        # were previously only written by ``hook_env()`` from
        # ``container_wiring.on_trial_started`` — but that runs
        # AFTER the agent is already constructed (Trial.create
        # snapshots config.env into extra_env at construction
        # time, see harbor/agents/factory.py:46). Result: the
        # container-side hook silently fell back to its hardcoded
        # default of ``"additive"`` even when MethodConfig set
        # ``hook_score_mode: "multiplicative"``. We now seed the
        # 5 new keys here at __init__ time so the agent's
        # ``_extra_env`` carries them into the container. The
        # bridge in ``run_paper_job`` will OVERWRITE these with
        # method-config-derived values BEFORE Trial.create, so
        # the values seen at runtime are the method-config ones;
        # the defaults below are a defense-in-depth safety net
        # for direct-import call sites that don't go through
        # the paper CLI.
        skillq_hook_env = {
            "SKILLQ_LIB": str(CONTAINER_LIB_PATH),
            "SKILLQ_Q_TABLE": str(CONTAINER_Q_TABLE_PATH),
            "SKILLQ_EMB_CACHE": str(CONTAINER_EMB_CACHE_PATH),
            "SKILLQ_CALLS_LOG": str(CONTAINER_CALLS_LOG_PATH),
            "SKILLQ_EMBED_HOST": "host.docker.internal",
            "SKILLQ_EMBED_PORT": "8765",
            "SKILLQ_USER_TASK": "",  # filled in at run() time if available
            "SKILLQ_HOOK_TOP_K": "3",
            "SKILLQ_HOOK_LAMBDA": "0.500000",
            "SKILLQ_HOOK_C_UCB": "0.500000",
            # 2026-06-25: 5 new keys, defaults mirror hook.py fallback
            # AND MethodConfig defaults (so the two never disagree
            # silently).
            "SKILLQ_HOOK_SCORE_MODE": "multiplicative",
            "SKILLQ_HOOK_MULT_BETA": "0.500000",
            "SKILLQ_HOOK_MULT_GAMMA": "0.200000",
            "SKILLQ_HOOK_Q_CLIP_MIN": "0.000000",
            "SKILLQ_HOOK_Q_CLIP_MAX": "1.000000",
        }
        # 2026-06-25: removed the ``paper_retrieval`` block. It was
        # dead code — the agent kwarg was read into a private dict
        # that was never propagated to the container env, so the
        # container-side hook ignored it. The bridge now writes
        # SKILLQ_HOOK_* env vars from method-config (see
        # ``run_paper_job`` in bridge.py). All three yaml configs
        # (``tb2_skillq_full.yaml``, ``tb2_skillq_full_v3.yaml``,
        # ``swebenchpro_skillq.yaml``) have dropped the
        # ``paper_retrieval:`` block.

        # Pull-mode (2026-06-23): if the caller passes pull_top_k kwarg,
        # set SKILLQ_PULL_TOP_K so the hook's SessionStart branch uses
        # that K. Absent kwarg → falls back to SKILLQ_HOOK_TOP_K inside
        # hook.py so existing runs are unaffected.
        pull_top_k = self._flag_kwargs.get("pull_top_k")
        if pull_top_k is not None:
            skillq_hook_env["SKILLQ_PULL_TOP_K"] = str(int(pull_top_k))

        # Merge into _extra_env (created by super().__init__).
        # We can't access self._extra_env before super().__init__,
        # so the merge happens after super() above.
        self._extra_env.update(skillq_hook_env)

    async def setup(self, environment: "BaseEnvironment") -> None:
        """Skip Harbor's install path; verify the preinstalled CLI."""
        await environment.exec(command="mkdir -p /installed-agent", user="root")

        setup_dir = self.logs_dir / "setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        (setup_dir / "mode.txt").write_text(
            "skip install script; use preinstalled claude CLI in image\n",
            encoding="utf-8",
        )

        # Claude Code creates ``$CLAUDE_CONFIG_DIR/CLAUDE.md/`` as a
        # directory at startup for project-level memory (it expects
        # the file ``CLAUDE.md`` to not already exist as a dir).
        # When the paper method bind-mounts a merged
        # ``CLAUDE.md.merged`` onto ``CLAUDE.md``, the runtime
        # directory shadows the bind mount and the snippet never
        # reaches the agent's system prompt. Clearing the path
        # before Claude Code starts lets the bind mount take
        # precedence (the mount creates a file at that path; we
        # then never re-create the dir because we don't use
        # project memory). Idempotent — no-op when the path does
        # not exist.
        await environment.exec(
            command='rm -rf "${CLAUDE_CONFIG_DIR:-/root/.claude}/CLAUDE.md" 2>/dev/null || true',
            user="root",
        )

        if self._version is not None:
            return

        version_command = self.get_version_command()
        if version_command is None:
            return

        try:
            result = await environment.exec(command=version_command)
        except Exception as exc:
            (setup_dir / "version-error.txt").write_text(str(exc), encoding="utf-8")
            return

        (setup_dir / "version-return-code.txt").write_text(
            str(result.return_code),
            encoding="utf-8",
        )
        if result.stdout:
            (setup_dir / "version-stdout.txt").write_text(
                result.stdout,
                encoding="utf-8",
            )
        if result.stderr:
            (setup_dir / "version-stderr.txt").write_text(
                result.stderr,
                encoding="utf-8",
            )
        if result.return_code == 0 and result.stdout:
            self._version = self.parse_version(result.stdout)

    async def run(
        self,
        instruction: str,
        environment: "BaseEnvironment",
        context: "AgentContext",
    ) -> None:
        """Run the agent in the container (no in-prompt UCB header).

        All retrieval ranking happens at the container-side
        PreToolUse hook (see :mod:`skillq.skillq_runtime.hook`); we do
        not pre-pend a UCB breakdown to the instruction.
        """
        await super().run(instruction, environment, context)


# Backwards-compatible alias. Older experiment YAML configs still
# reference ``skillq.skillq_runtime.agent:PaperClaudeCodeAgent`` — keep
# the name pointing at the same class so old configs keep working.
PaperClaudeCodeAgent = SkillQClaudeCodeAgent


# ---------------------------------------------------------------------------
# Helpers used by the bridge (kept here so all agent-side wiring lives
# in one module)
# ---------------------------------------------------------------------------
def hook_script_path() -> Path:
    """Absolute path to the container-side hook script on the host."""
    return _HOOK_SCRIPT_HOST_PATH.resolve()


def hook_env(
    *,
    lib_path: Path,
    q_table_path: Path,
    emb_cache_path: Path,
    calls_log_path: Path,
    embed_host: str,
    embed_port: int,
    user_task: str,
    top_k: int,
    lambda_: float,
    c_ucb: float,
    # 2026-06-24 additions: scoring mode + multiplicative params + Hard Gate
    score_mode: str = "additive",
    mult_beta: float = 0.5,
    mult_gamma: float = 0.2,
    q_clip_min: float = 0.0,
    q_clip_max: float = 1.0,
    sim_gate_min_score: float = 0.05,
    sim_gate_floor: int = 1,
) -> dict[str, str]:
    """Build the env dict the agent container needs for the hook."""
    # The hook runs INSIDE the agent container, so all of these
    # paths must be the in-container bind-mount targets, not the
    # host-side paths the bridge wrote them to. The earlier revision
    # passed host paths for ``SKILLQ_LIB`` / ``SKILLQ_Q_TABLE`` /
    # ``SKILLQ_EMB_CACHE`` (and only the calls_log got fixed
    # first) — the hook's ``_read_json`` then FileNotFoundErrored
    # on those host paths, the try/except returned 0 (pass-through)
    # *before* the log call, and the host's calls_log stayed empty
    # for the second-order reason. Import the constants lazily to
    # avoid a circular import (container_wiring imports back from
    # this module for the hook helpers).
    from skillq.skillq_runtime.container_wiring import (
        CONTAINER_CALLS_LOG_PATH,
        CONTAINER_EMB_CACHE_PATH,
        CONTAINER_LIB_PATH,
        CONTAINER_Q_TABLE_PATH,
    )

    return {
        "SKILLQ_LIB": str(CONTAINER_LIB_PATH),
        "SKILLQ_Q_TABLE": str(CONTAINER_Q_TABLE_PATH),
        "SKILLQ_EMB_CACHE": str(CONTAINER_EMB_CACHE_PATH),
        "SKILLQ_CALLS_LOG": str(CONTAINER_CALLS_LOG_PATH),
        "SKILLQ_EMBED_HOST": embed_host,
        "SKILLQ_EMBED_PORT": str(embed_port),
        "SKILLQ_USER_TASK": user_task[:2000],
        "SKILLQ_HOOK_TOP_K": str(top_k),
        "SKILLQ_HOOK_LAMBDA": f"{lambda_:.6f}",
        "SKILLQ_HOOK_C_UCB": f"{c_ucb:.6f}",
        # 2026-06-24: scoring mode + multiplicative params + Hard Gate.
        # Container-side hook reads these via ``os.environ.get`` at
        # module-load (see hook.py top-of-file constants).
        "SKILLQ_HOOK_SCORE_MODE": str(score_mode),
        "SKILLQ_HOOK_MULT_BETA": f"{mult_beta:.6f}",
        "SKILLQ_HOOK_MULT_GAMMA": f"{mult_gamma:.6f}",
        "SKILLQ_HOOK_Q_CLIP_MIN": f"{q_clip_min:.6f}",
        "SKILLQ_HOOK_Q_CLIP_MAX": f"{q_clip_max:.6f}",
        "SKILLQ_SIM_GATE_MIN_SCORE": f"{sim_gate_min_score:.6f}",
        "SKILLQ_SIM_GATE_FLOOR": str(sim_gate_floor),
    }


def hook_settings_json(
    *,
    hook_container_path: str,
    script_inline: str | None = None,
    include_pull: bool = False,
) -> dict[str, Any]:
    """Build the ``settings.json`` dict that registers the PreToolUse hook.

    Claude Code's settings.json schema (PreToolUse hook):

    .. code-block:: json

        {
          "hooks": {
            "PreToolUse": [
              {
                "matcher": "Skill",
                "hooks": [
                  {"type": "command", "command": "python3 <path>"}
                ]
              }
            ]
          }
        }

    The hook script receives the tool call's JSON on stdin and
    returns its decision on stdout.

    When ``include_pull=True`` (used by retrieval_mode='pull'), also
    registers a ``UserPromptSubmit`` hook under the same ``hooks`` key.
    The script dispatches on ``hook_event_name`` (see
    ``skillq/skillq_runtime/hook.py:main``), so a single command covers
    both events.

    Why ``UserPromptSubmit`` and not ``SessionStart``: smoke test on
    2026-06-23 showed SessionStart fires with an empty ``prompt`` field
    (the user prompt hasn't been injected yet on session startup), so
    the pull-mode handler early-returned with empty stdout. UserPromptSubmit
    fires after each user turn with the prompt text populated, which is
    what the pull-mode handler actually needs.
    """
    cmd = f"python3 {hook_container_path}"
    hooks_block: dict[str, Any] = {
        "PreToolUse": [
            {
                "matcher": "Skill",
                "hooks": [
                    {
                        "type": "command",
                        "command": cmd,
                    }
                ],
            }
        ],
    }
    if include_pull:
        # UserPromptSubmit: no matcher (fires unconditionally on every
        # user prompt). Same command — hook.py dispatches by event name.
        hooks_block["UserPromptSubmit"] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": cmd,
                    }
                ],
            }
        ]
    return {"hooks": hooks_block}


def pull_env(*, top_k: int) -> dict[str, str]:
    """Env vars consumed by ``hook.py`` UserPromptSubmit branch.

    Returned dict is merged into the agent container's env so the
    hook script picks them up at startup (constants in hook.py are
    read once at module load).
    """
    return {"SKILLQ_PULL_TOP_K": str(top_k)}
