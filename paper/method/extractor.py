"""SkillExtractor — create new skills via a ``claude --print`` subprocess.

Per design decision B2: the extractor uses the same subprocess shape
as lqrl's ``evolve/claude_code.py:step_evolve`` — a ``claude --print
--permission-mode=bypassPermissions`` invocation that has Write /
Edit file tools, with a sandboxed working directory. The LLM is told
to write a single ``SKILL.md`` (and optional ``scripts/``) under the
sandbox. The bridge then reads the resulting file, validates the
path is under the sandbox (security: matches lqrl's
``resolve_created_skill_dir``), and returns a :class:`Skill`.

The extractor is a *per-trial* LLM call, not a batched evolve like
lqrl. Each successful trial that the bridge decides should trigger
extraction (i.e., ``overall_attribution`` is
``SUCCESS_VIEWED_SKILL_BUT_NOT_USED`` or ``SUCCESS_NO_SKILL_SEEN``)
spawns at most one subprocess. The subprocess has a hard timeout
(``timeout_sec``) and is wrapped in :func:`asyncio.to_thread` to keep
the bridge's event loop responsive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from paper.method.hash import qhash
from paper.method.prompts import EXTRACT_SKILL_PROMPT
from paper.method.types import Skill

logger = logging.getLogger("paper.method.extractor")


@dataclass
class SkillExtractor:
    """Spawns a ``claude --print`` subprocess to materialize a SKILL.md.

    Parameters
    ----------
    claude_cli : str
        Path / name of the Claude Code CLI. Default ``claude`` — the
        user's installed binary.
    model : str
        Model name passed to the CLI as ``--model``. Empty string
        falls back to whatever the CLI default is.
    timeout_sec : int
        Hard wall-clock timeout for the subprocess.
    name_min_words / name_max_words :
        Skill name length constraints (defaults 1 / 4 to mirror
        lqrl's "skill name ≤ 4 words" rule).
    body_min_tokens / body_max_tokens :
        Soft token-count guard rails for the SKILL.md body.
    """

    claude_cli: str = "claude"
    model: str = ""
    timeout_sec: int = 600
    name_min_words: int = 1
    name_max_words: int = 4
    body_min_tokens: int = 50
    body_max_tokens: int = 2000

    async def extract(
        self,
        *,
        task: str,
        knowledge: str,
        intent_hash: int,
        available_skill_names: list[str] | None = None,
        sandbox_root: Path | None = None,
    ) -> Skill | None:
        """Materialize a new SKILL.md and return a :class:`Skill`.

        Returns ``None`` on any failure (timeout, parse error, security
        check failed, LLM did not write a file, etc.). The bridge
        treats ``None`` as "extract skipped" and moves on.
        """
        sandbox = self._make_sandbox(sandbox_root)
        system_prompt = EXTRACT_SKILL_PROMPT.format(
            task=task,
            knowledge=knowledge,
            intent_hash=f"{intent_hash:016x}",
            available_skills=json.dumps(available_skill_names or []),
            sandbox_dir=str(sandbox),
            name_min_words=self.name_min_words,
            name_max_words=self.name_max_words,
            body_min_tokens=self.body_min_tokens,
            body_max_tokens=self.body_max_tokens,
        )

        cmd = [
            self.claude_cli,
            "--print",
            "--permission-mode=bypassPermissions",
            "--output-format",
            "json",
            *(["--model", self.model] if self.model else []),
            "--append-system-prompt",
            system_prompt,
        ]

        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                cmd,
                cwd=str(sandbox),
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning(
                "extractor subprocess timed out after %s s", self.timeout_sec
            )
            shutil.rmtree(sandbox, ignore_errors=True)
            return None
        except FileNotFoundError:
            logger.warning("claude CLI not found at %s", self.claude_cli)
            shutil.rmtree(sandbox, ignore_errors=True)
            return None

        if proc.returncode != 0:
            logger.warning(
                "extractor subprocess returned %s: stderr=%s",
                proc.returncode,
                proc.stderr[:500] if proc.stderr else "",
            )
            shutil.rmtree(sandbox, ignore_errors=True)
            return None

        skill = self._collect_skill(sandbox, intent_hash, task)
        shutil.rmtree(sandbox, ignore_errors=True)
        return skill

    # ------------------------------------------------------------------
    # Sandbox + collection
    # ------------------------------------------------------------------
    def _make_sandbox(self, root: Path | None) -> Path:
        import tempfile

        base = root or Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        sandbox = base / f"mg_extract_{qhash(str(base)):016x}"[:24]
        sandbox.mkdir(parents=True, exist_ok=True)
        # The LLM is told to write into a `create/` subdirectory so
        # we can apply the lqrl-style "path must be a direct child
        # of create_dir" security check.
        (sandbox / "create").mkdir(exist_ok=True)
        return sandbox

    def _collect_skill(
        self,
        sandbox: Path,
        intent_hash: int,
        task: str,
    ) -> Skill | None:
        """Find the SKILL.md the LLM wrote, validate it, return a Skill.

        Mirrors lqrl's :func:`skills_vote.evolve.utils.resolve_created_skill_dir`:
        the file must be a direct child of ``<sandbox>/create/<name>/SKILL.md``.
        """
        create_dir = sandbox / "create"
        if not create_dir.is_dir():
            return None

        candidates = sorted(p for p in create_dir.iterdir() if p.is_dir())
        if len(candidates) != 1:
            # LLM wrote zero or multiple; in both cases we discard to
            # keep the contract "one skill per extract call".
            return None

        skill_dir = candidates[0]
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            return None

        body = skill_md.read_text(encoding="utf-8", errors="replace").strip()
        if not body:
            return None

        # Token guard (soft — warn, don't reject)
        body_tokens = len(re.findall(r"\S+", body))
        if body_tokens < self.body_min_tokens:
            logger.warning(
                "extractor produced %d body tokens (< min %d), rejecting",
                body_tokens,
                self.body_min_tokens,
            )
            return None
        if body_tokens > self.body_max_tokens:
            logger.warning(
                "extractor produced %d body tokens (> max %d), rejecting",
                body_tokens,
                self.body_max_tokens,
            )
            return None

        # Derive the skill name from the directory name. The LLM is
        # told to use kebab-case; we keep the directory name verbatim.
        skill_id = skill_dir.name
        words = skill_id.replace("-", " ").split()
        if not (self.name_min_words <= len(words) <= self.name_max_words):
            logger.warning(
                "extractor produced skill name with %d words (need %d..%d): %s",
                len(words),
                self.name_min_words,
                self.name_max_words,
                skill_id,
            )
            return None

        # Also copy any sibling scripts/ subdirectory the LLM might
        # have created, so the new skill is fully self-contained.
        scripts_dir = skill_dir / "scripts"
        if scripts_dir.is_dir():
            # The bridge is responsible for placing the new skill in
            # the working skills dir; the scripts subdir is preserved
            # by QlibState since we serialise the body only. The
            # bridge can opt to copy the dir separately if needed.
            logger.debug("extractor: %s has scripts/ subdir", skill_id)

        return Skill(
            skill_id=skill_id,
            body=body,
            n_retrievals=0,
            n_uses=0,
            n_success=0,
            metadata={
                "source": "mg_paper_extract",
                "intent_hash": f"{intent_hash:016x}",
                "task_description": task[:500],
                "has_scripts": scripts_dir.is_dir(),
            },
        )
