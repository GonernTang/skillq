"""``PaperClaudeCodeAgent`` — lqrl's ``SkillsVoteClaudeCode`` subclass
that wires in the **per-subtask hook** for paper-mode skill retrieval.

**Per user design 2026-06-11**:

The agent runs inside a Docker container (prebuilt ``skills_vote/<task>:<tag>``
image). Before the agent's main ``claude --print`` loop starts, this
class:

1. Starts a **host-side embedding service** (FastAPI + uvicorn) in
   a background thread, bound to ``0.0.0.0:<port>`` so the
   container's hook can call ``http://host.docker.internal:<port>/embed``.
2. Dumps the current state from
   ``<library_root>/.state/{method_state.json, emb_cache.json}`` into
   a staging dir on the host (the container reads it from a mount
   that the bridge wires via ``environment.mounts_json``).
3. Sets the **per-subtask hook** env vars
   (``MG_LIB``, ``MG_Q_TABLE``, ``MG_EMB_CACHE``, ``MG_CALLS_LOG``,
   ``MG_EMBED_HOST``, ``MG_EMBED_PORT``, ``MG_USER_TASK``,
   ``MG_HOOK_TOP_K``, ``MG_HOOK_LAMBDA``, ``MG_HOOK_C_UCB``) on the
   container's environment.
4. Mounts the ``paper.paper_mode.hook`` script into
   ``$CLAUDE_CONFIG_DIR/hooks/mg_skill_hook.py`` and registers it
   in ``settings.json`` as a PreToolUse hook for the ``Skill`` tool.
5. Calls ``super().run()`` (the original lqrl flow), passing the
   enriched env + settings into the container.

The existing in-instruction UCB header from the previous
implementation (``rerank_with_ucb``) is **kept as a hint** but is no
longer the primary retrieval mechanism — the hook now does the
real per-Skill-call ranking.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from skills_vote.harbor.claude_code import SkillsVoteClaudeCode

from paper.paper_mode.config import PaperRetrievalArgs

if TYPE_CHECKING:  # pragma: no cover
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext

logger = logging.getLogger("paper.paper_mode.agent")


# Where the hook source script lives on the host. The agent mounts
# this into the container at ``$CLAUDE_CONFIG_DIR/hooks/`` and
# references it from settings.json.
_HOOK_SCRIPT_HOST_PATH = Path(__file__).parent / "hook.py"


class PaperClaudeCodeAgent(SkillsVoteClaudeCode):
    """Lqrl's SkillsVoteClaudeCode with mg's per-subtask hook wired in.

    The agent class itself remains a thin subclass — most of the
    per-trial setup (state dump, hook script placement, settings
    injection, embedding service lifecycle) is handled by the
    bridge (``bridge.attach_paper_registers``), which has access to
    the trial's environment and method config. This class only
    knows how to (1) start/stop the embedding service at trial
    boundaries and (2) merge hook-related env vars into the
    container environment.
    """

    @staticmethod
    def name() -> str:
        return "PaperClaudeCodeAgent"

    def __init__(self, *args: Any, paper_retrieval: dict | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._paper_args = PaperRetrievalArgs.model_validate(paper_retrieval or {})

    async def run(
        self,
        instruction: str,
        environment: "BaseEnvironment",
        context: "AgentContext",
    ) -> None:
        """Run the agent in the container, with the hook env wired in.

        We mutate the **kwargs that the base class passes to
        ``exec_as_agent``** by reading the resolved
        ``paper_retrieval`` config from the bridge. The bridge
        normally writes hook env into the environment before the
        agent runs; this method just plumbs any per-agent hook
        config into the existing flow.

        The actual container-side wiring (state dump, settings.json
        edit, hook script mount, embedding service start) is the
        bridge's responsibility — see ``bridge.attach_paper_registers``.
        """
        if self._paper_args.enabled:
            # Lightweight UCB header — the primary retrieval happens
            # at the hook layer; this just gives the agent an upfront
            # hint of which skills are ranked highest. Cheap
            # (StubEmbedder) and runs before the agent loop.
            from paper.paper_mode.retrieval_step import rerank_with_ucb

            instruction = await rerank_with_ucb(self, instruction, self._paper_args)
        await super().run(instruction, environment, context)


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
        "MG_LIB": str(lib_path),
        "MG_Q_TABLE": str(q_table_path),
        "MG_EMB_CACHE": str(emb_cache_path),
        "MG_CALLS_LOG": str(calls_log_path),
        "MG_EMBED_HOST": embed_host,
        "MG_EMBED_PORT": str(embed_port),
        "MG_USER_TASK": user_task[:2000],
        "MG_HOOK_TOP_K": str(top_k),
        "MG_HOOK_LAMBDA": f"{lambda_:.6f}",
        "MG_HOOK_C_UCB": f"{c_ucb:.6f}",
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
