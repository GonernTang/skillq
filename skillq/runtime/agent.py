"""SkillQClaudeCodeAgent — Step 5 (2026-06-26) refactor.

From-scratch subclass of Harbor's
:class:`harbor.agents.installed.claude_code.ClaudeCode` that
**drops** all the obsolete env-var defaults Step 5's container
hook no longer reads:

- ``SKILLQ_LIB`` (host owns via ``MethodServices``)
- ``SKILLQ_Q_TABLE`` (host owns)
- ``SKILLQ_EMB_CACHE`` (host owns)
- ``SKILLQ_CALLS_LOG`` → renamed to ``SKILLQ_CALLS_LOG_PATH`` (Step 5)
- ``SKILLQ_EMBED_HOST`` → merged into ``SKILLQ_RANK_ENDPOINT``
- ``SKILLQ_EMBED_PORT`` → merged into ``SKILLQ_RANK_ENDPOINT``

The new env-var surface is **3 defaults** (down from 14):

- ``SKILLQ_RANK_ENDPOINT`` — required, default ``http://host.docker.internal:8765``
- ``SKILLQ_CALLS_LOG_PATH`` — optional, default empty
- ``SKILLQ_USER_TASK`` — optional, default empty (filled in at wire time)

Everything else (``SKILLQ_HOOK_*``, ``SKILLQ_SIM_GATE_*``,
``SKILLQ_HOOK_RANK_TIMEOUT_SEC``, ``SKILLQ_PULL_TOP_K``) is
seeded by the host's :func:`skillq.runtime.env_seed.seed_agent_env`
BEFORE :func:`harbor.Job.create`. If the seed didn't run, the
container-side hook fails loud at module-load time
(``KeyError: SKILLQ_RANK_ENDPOINT``).

The agent class itself is intentionally minimal:

- Same hookable lifecycle as the legacy implementation.
- ``name()`` returns ``"SkillQClaudeCodeAgent"``.
- ``setup()`` skips Harbor's install path (mirrors
  ``skills_vote.harbor.claude_code.SkillsVoteClaudeCode.setup``)
  and clears the CLAUDE.md runtime dir so the bind-mount takes
  precedence.
- ``run()`` is a pass-through to ``super().run()`` — no in-prompt
  UCB header (the L1 ranking happens at the PreToolUse hook via
  ``/rank``).
- ``PaperClaudeCodeAgent`` alias kept for v1 YAML configs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from harbor.agents.installed.claude_code import ClaudeCode

if TYPE_CHECKING:
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext


logger = logging.getLogger("skillq.runtime.agent")


# Where the new hook source script lives on the host. The
# container bind-mounts this file into ``$CLAUDE_CONFIG_DIR/hooks/``
# and references it from ``settings.json``. **Step 5**: this is
# the new minimal ``runtime/hook.py`` (~150 lines, /rank client),
# NOT the legacy 547-line stdlib Eq.4 implementation.
_HOOK_SCRIPT_HOST_PATH = Path(__file__).parent / "hook.py"


class SkillQClaudeCodeAgent(ClaudeCode):
    """Direct Harbor ``ClaudeCode`` subclass for ``skillq paper run``.

    Step 5 changes (vs the legacy implementation):

    - 14 obsolete env-var defaults removed. The 3 remaining
      defaults (``SKILLQ_RANK_ENDPOINT``,
      ``SKILLQ_CALLS_LOG_PATH``, ``SKILLQ_USER_TASK``) are
      defense-in-depth — the host bridge seeds all 14
      ``SKILLQ_*`` vars (including 9 tunables the hook reads)
      before ``Job.create`` via
      :func:`skillq.runtime.env_seed.seed_agent_env`.
    - ``hook_script_path()`` / ``hook_settings_json()`` /
      ``hook_env()`` helpers moved into this module (Step 5
      needs them here so the new container_wiring can import
      from one place).
    """

    @staticmethod
    def name() -> str:
        return "SkillQClaudeCodeAgent"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Inject the **3 minimum** SKILLQ_* env vars the hook
        # reads into ``self._extra_env`` so they actually reach
        # the agent's process. The host bridge will OVERWRITE
        # SKILLQ_RANK_ENDPOINT with the ranking daemon's actual
        # host:port BEFORE Trial.create, so the value seen at
        # runtime is the host-side one; the defaults below are a
        # defense-in-depth safety net for direct-import call
        # sites that don't go through the paper CLI.
        skillq_hook_env = {
            "SKILLQ_RANK_ENDPOINT": "http://host.docker.internal:8765",
            "SKILLQ_CALLS_LOG_PATH": "",  # host fills at trial start
            "SKILLQ_USER_TASK": "",        # host fills at trial start
        }
        super().__init__(*args, **kwargs)
        # Merge into ``self._extra_env`` (created by
        # BaseInstalledAgent.__init__). Use ``setdefault`` for the
        # empty default placeholders so the host wiring (which runs
        # later via ``_wire_hook_trial``) does NOT get clobbered.
        # 2026-06-29 (Phase 10 Bug 5 v2): the previous
        # ``self._extra_env.update(skillq_hook_env)`` overwrote the
        # host's SKILLQ_CALLS_LOG_PATH with ``""`` (the default
        # placeholder), making the hook silently skip writing the
        # calls log (its ``_append_jsonl`` early-returns on empty
        # path).
        for _k, _v in skillq_hook_env.items():
            self._extra_env.setdefault(_k, _v)

    async def setup(self, environment: "BaseEnvironment") -> None:
        """Skip Harbor's install path; verify the preinstalled CLI.

        Mirrors
        ``skills_vote.harbor.claude_code.SkillsVoteClaudeCode.setup``:
        skips Harbor's default
        ``curl https://claude.ai/install.sh`` install path
        (which fails for offline / prebuilt images) and instead
        just verifies the preinstalled CLI with
        ``claude --version``. Required because every
        ``skills_vote/<task>:<tag>`` prebuilt image already has
        the Claude Code CLI baked in.
        """
        await environment.exec(command="mkdir -p /installed-agent", user="root")

        setup_dir = self.logs_dir / "setup"
        setup_dir.mkdir(parents=True, exist_ok=True)
        (setup_dir / "mode.txt").write_text(
            "skip install script; use preinstalled claude CLI in image\n",
            encoding="utf-8",
        )

        # Claude Code creates ``$CLAUDE_CONFIG_DIR/CLAUDE.md/`` as
        # a directory at startup for project-level memory. When
        # the paper method bind-mounts a merged ``CLAUDE.md.merged``
        # onto ``CLAUDE.md``, the runtime directory shadows the
        # bind mount. Clear the path before Claude Code starts so
        # the bind mount takes precedence.
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
            str(result.return_code), encoding="utf-8",
        )
        if result.stdout:
            (setup_dir / "version-stdout.txt").write_text(
                result.stdout, encoding="utf-8",
            )
        if result.stderr:
            (setup_dir / "version-stderr.txt").write_text(
                result.stderr, encoding="utf-8",
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
        PreToolUse hook (see :mod:`skillq.runtime.hook`) which
        calls ``POST /rank`` against the host's ranking
        daemon. We do not pre-pend a UCB breakdown to the
        instruction.
        """
        await super().run(instruction, environment, context)


# Backwards-compatible alias. Older experiment YAML configs still
# reference ``skillq.runtime.agent:PaperClaudeCodeAgent`` — keep
# the name pointing at the same class so old configs keep
# working.
PaperClaudeCodeAgent = SkillQClaudeCodeAgent


# ---------------------------------------------------------------------------
# Hook helpers — used by runtime/container_wiring.py to mount the
# hook script + generate settings.json + build the per-trial env.
# ---------------------------------------------------------------------------
def hook_script_path() -> Path:
    """Absolute path to the container-side hook script on the host.

    Returns the new minimal ``runtime/hook.py`` (~150 lines,
    /rank client), **not** the legacy 547-line stdlib Eq.4
    implementation.
    """
    return _HOOK_SCRIPT_HOST_PATH.resolve()


def hook_env(
    *,
    user_task: str,
    calls_log_path: str | None = None,
) -> dict[str, str]:
    """Build the per-trial env dict the hook reads.

    Step 5 reduced this from the legacy 17-key dict to just the
    per-trial path vars. The 9 tunables (``SKILLQ_HOOK_*`` /
    ``SKILLQ_SIM_GATE_*`` / ``SKILLQ_HOOK_RANK_TIMEOUT_SEC`` /
    ``SKILLQ_PULL_TOP_K``) are seeded once at job start by
    :func:`skillq.runtime.env_seed.seed_agent_env` and are NOT
    re-applied here.
    """
    env: dict[str, str] = {
        "SKILLQ_USER_TASK": user_task[:2000],
    }
    if calls_log_path:
        env["SKILLQ_CALLS_LOG_PATH"] = str(calls_log_path)
    return env


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
    """
    settings: dict[str, Any] = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Skill",
                    "hooks": [
                        {"type": "command", "command": f"python3 {hook_container_path}"},
                    ],
                },
            ],
        },
    }
    if include_pull:
        # Pull-mode (retrieval_mode='pull'): also register a
        # UserPromptSubmit hook so the agent sees a Top-K skills
        # reminder on every user prompt. The new
        # runtime/hook.py handles UserPromptSubmit via /rank.
        settings["hooks"]["UserPromptSubmit"] = [
            {
                "hooks": [
                    {"type": "command", "command": f"python3 {hook_container_path}"},
                ],
            },
        ]
    return settings


__all__ = [
    "SkillQClaudeCodeAgent",
    "PaperClaudeCodeAgent",
    "hook_script_path",
    "hook_env",
    "hook_settings_json",
]