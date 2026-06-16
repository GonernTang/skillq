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
    """

    @staticmethod
    def name() -> str:
        return "SkillQClaudeCodeAgent"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

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
    return {
        "SKILLQ_LIB": str(lib_path),
        "SKILLQ_Q_TABLE": str(q_table_path),
        "SKILLQ_EMB_CACHE": str(emb_cache_path),
        "SKILLQ_CALLS_LOG": str(calls_log_path),
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
