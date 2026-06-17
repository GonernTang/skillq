"""``SkillQClaudeCodeAgent`` — direct subclass of Harbor's
:class:`harbor.agents.installed.claude_code.ClaudeCode` for paper mode.

This agent does **not** inherit from the vendored
``skills_vote.harbor.claude_code.SkillsVoteClaudeCode`` — it
deliberately drops the recommend-step (the SkillQ method uses a
container-side PreToolUse hook for ranking instead of in-prompt
recommendation). All the per-subtask hook wiring (embed daemon
lifecycle, state dump, ``SKILLQ_*`` env injection, bind mounts)
is owned by the bridge in :mod:`skillq.paper_mode.container_wiring`.
The agent class only exists because Harbor's :class:`Job` looks
up the agent by ``import_path`` (e.g.
``skillq.paper_mode.agent:SkillQClaudeCodeAgent``).

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

logger = logging.getLogger("paper.paper_mode.agent")


# Where the hook source script lives on the host. The container
# bind-mounts this file into ``$CLAUDE_CONFIG_DIR/hooks/`` and
# references it from settings.json.
_HOOK_SCRIPT_HOST_PATH = Path(__file__).parent / "hook.py"


class SkillQClaudeCodeAgent(ClaudeCode):
    """Direct Harbor ``ClaudeCode`` subclass for ``skillq paper run``.

    All per-trial wiring happens in
    :func:`skillq.paper_mode.container_wiring.wire_one_trial` (env
    vars, bind mounts, settings.json) before this agent's run loop
    is invoked. This class is intentionally minimal: it adds no
    recommend step, no skill whitelisting, no plugin-dir handling
    — the PreToolUse hook in :mod:`skillq.paper_mode.hook` does
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
        from skillq.paper_mode.container_wiring import (
            CONTAINER_CALLS_LOG_PATH,
            CONTAINER_EMB_CACHE_PATH,
            CONTAINER_LIB_PATH,
            CONTAINER_Q_TABLE_PATH,
        )

        super().__init__(*args, **kwargs)

        # Merge SKILLQ_* into ``self._extra_env`` (created by
        # BaseInstalledAgent.__init__). Don't clobber anything
        # already in there (e.g. from the bridge's late updates).
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
        }
        # Read paper_retrieval kwargs if present so the dynamic
        # values (lambda, c_ucb, top_k) match the trial.
        paper = self._flag_kwargs.get("paper_retrieval") or {}
        if isinstance(paper, dict):
            if "k2" in paper:
                skillq_hook_env["SKILLQ_HOOK_TOP_K"] = str(paper["k2"])
            if "lambda_" in paper:
                skillq_hook_env["SKILLQ_HOOK_LAMBDA"] = f"{float(paper['lambda_']):.6f}"
            if "c_ucb" in paper:
                skillq_hook_env["SKILLQ_HOOK_C_UCB"] = f"{float(paper['c_ucb']):.6f}"

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
        PreToolUse hook (see :mod:`skillq.paper_mode.hook`); we do
        not pre-pend a UCB breakdown to the instruction.
        """
        await super().run(instruction, environment, context)


# Backwards-compatible alias. Older experiment YAML configs still
# reference ``skillq.paper_mode.agent:PaperClaudeCodeAgent`` — keep
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
    from skillq.paper_mode.container_wiring import (
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
    }


def hook_settings_json(
    *, hook_container_path: str, script_inline: str | None = None
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
    """
    cmd = f"python3 {hook_container_path}"
    return {
        "hooks": {
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
            ]
        }
    }
