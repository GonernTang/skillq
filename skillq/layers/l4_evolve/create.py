"""SkillExtractor — create new skills via a ``claude --print`` subprocess.

Step 2 of the 2026-06-26 refactor relocated this from the legacy
``skillq/method/extractor.py`` to ``skillq/layers/l4_evolve/create.py``.
The implementation is unchanged in Step 2; only the import paths and
logger name moved.

The extractor uses the same subprocess shape as lqrl's
``evolve/claude_code.py:step_evolve`` — a ``claude --print
--permission-mode=bypassPermissions`` invocation that has Write /
Edit file tools, with a sandboxed working directory. The LLM is told
to write a single ``SKILL.md`` (and optional ``scripts/``) under the
sandbox. The bridge then reads the resulting file, validates the
path is under the sandbox (security: matches lqrl's
``resolve_created_skill_dir``), and returns a :class:`Skill`.

The bridge **always** uses :meth:`SkillExtractor.extract_batch`: the
buffer accumulates (task, knowledge) records from N successful
trials and a single ``claude --print`` subprocess consumes them
all. This is the batched-evolve shape (mirroring SkillsVote's
``evolve_every_n_trials``); the per-trial ``extract()`` variant was
removed because it produced too task-specific skills.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from skillq.shared.hash import qhash
from skillq.layers.l4_evolve.prompts import (
    BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT,
    BATCHED_EXTRACT_SKILL_PROMPT,
    PER_TRIAL_EXTRACT_SKILL_FROM_FAILURE_PROMPT,
    PER_TRIAL_EXTRACT_SKILL_PROMPT,
)
from skillq.shared.types import Skill

logger = logging.getLogger("skillq.layers.l4_evolve.create")


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
    prompt_mode : str
        ``"success"`` (default) uses
        :data:`paper.method.prompts.BATCHED_EXTRACT_SKILL_PROMPT` (Rule
        2 path — synthesize a reusable procedure from successful
        trajectories). ``"failure"`` uses
        :data:`paper.method.prompts.BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT`
        (Rule 5 path — synthesize a guard-rail from failure
        attributions).
    """

    claude_cli: str = "claude"
    model: str = ""
    timeout_sec: int = 600
    name_min_words: int = 1
    name_max_words: int = 4
    body_min_tokens: int = 50
    body_max_tokens: int = 2000
    prompt_mode: str = "success"
    # 2026-06-25: when True (default), ``_collect_skill`` rejects
    # failure-prompt skills that omit the required "Diagnostic
    # checklist" / "Stop signal" sections. The
    # BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT instructs the LLM that
    # "a skill missing either section is incomplete and will be
    # rejected by the bridge" — this flag is the enforcement.
    enforce_failure_skill_structure: bool = True

    async def extract_batch(
        self,
        *,
        trials: list[dict[str, Any]],
        sandbox_root: Path | None = None,
        aggregated_intent_hash: int = 0,
    ) -> tuple[Skill | None, Path | None]:
        """Materialize a new SKILL.md from N aggregated (task, knowledge)
        records. Spawns ONE ``claude --print`` subprocess.

        Each entry in ``trials`` is a dict with keys:
            ``task`` (str), ``knowledge`` (str), ``intent_hash`` (int).

        Mirrors lqrl's ``step_evolve`` ``_CREATE_SYSTEM_PROMPT`` shape
        (aggregate reusable exploration → decide create or skip →
        synthesize), but in our own wording and with skillq-method
        constraints. When ``prompt_mode="failure"``, the prompt is
        reframed for the Rule 5 (failure → new skill) path.

        2026-06-30: ``available_skill_names`` removed — the L4
        extract prompt no longer injects the library's skill-id list
        (the cosine-based semantic dedup that depended on this is
        gone). Name-collision dedup at the bridge boundary remains.

        Returns ``(skill, sandbox)`` where ``sandbox`` is the Path the
        LLM wrote into. The caller is responsible for ``shutil.rmtree``
        of the sandbox (after copying any aux files via
        :meth:`copy_aux_files`). ``sandbox`` is ``None`` only when
        ``trials`` is empty.
        """
        if not trials:
            return None, None
        # N=1 → per-trial prompt (2026-07-03).
        # The batch prompt's "find common patterns across N trials"
        # framing is vacuous for N=1 and harmful for heterogeneous
        # trials grouped only by mode. Per-trial prompt distills one
        # trial's knowledge without the spurious cross-task comparison.
        if len(trials) == 1:
            return await self._extract_single(
                task=trials[0].get("task", ""),
                knowledge=trials[0].get("knowledge", ""),
                gap_description=trials[0].get("gap_description", ""),
                intent_hash=aggregated_intent_hash,
                sandbox_root=sandbox_root,
            )

        # N>1 — existing batch path unchanged.
        per_trial_lines = []
        for i, t in enumerate(trials, start=1):
            # 2026-06-25: include library_gap_skill_description when
            # present. The failure-path prompt prefers the gap
            # description as the seed for the synthesized skill body.
            # We still always emit the reusable_knowledge line so the
            # prompt has both fields to choose from.
            line = (
                f"[Trial {i}]\n"
                f"  intent_hash: {t.get('intent_hash', 0):016x}\n"
                f"  task: {t.get('task', '')!r}\n"
                f"  reusable_knowledge: {t.get('knowledge', '')!r}\n"
            )
            gap = t.get("gap_description", "")
            if gap:
                line += f"  library_gap_skill_description: {gap!r}\n"
            per_trial_lines.append(line)
        aggregated = "\n".join(per_trial_lines)

        # Use the first non-empty task as the "representative" task
        representative_task = next(
            (t["task"] for t in trials if t.get("task")), "aggregate"
        )

        if self.prompt_mode == "failure":
            prompt_template = BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT
        else:
            prompt_template = BATCHED_EXTRACT_SKILL_PROMPT
        return await self._extract_with_prompt(
            prompt_template=prompt_template,
            format_kwargs={
                "n_trials": len(trials),
                "aggregated_trials": aggregated,
                "representative_task": representative_task,
            },
            task=representative_task,
            intent_hash=aggregated_intent_hash,
            sandbox_root=sandbox_root,
        )

    async def _extract_single(
        self,
        *,
        task: str,
        knowledge: str,
        gap_description: str,
        intent_hash: int,
        sandbox_root: Path | None,
    ) -> tuple[Skill | None, Path | None]:
        """Per-trial extract — N=1 fast path (2026-07-03).

        Uses :data:`PER_TRIAL_EXTRACT_SKILL_PROMPT` (success) or
        :data:`PER_TRIAL_EXTRACT_SKILL_FROM_FAILURE_PROMPT` (failure)
        instead of the batch prompt. The prompt instructs the LLM to
        distill one trial's knowledge into a SKILL.md, with an explicit
        skip gate for knowledge that is too task-specific.
        """
        if self.prompt_mode == "failure":
            prompt_template = PER_TRIAL_EXTRACT_SKILL_FROM_FAILURE_PROMPT
        else:
            prompt_template = PER_TRIAL_EXTRACT_SKILL_PROMPT
        return await self._extract_with_prompt(
            prompt_template=prompt_template,
            format_kwargs={
                "task": task,
                "knowledge": knowledge,
            },
            task=task,
            intent_hash=intent_hash,
            sandbox_root=sandbox_root,
        )

    async def _extract_with_prompt(
        self,
        *,
        prompt_template: str,
        format_kwargs: dict[str, Any],
        task: str,
        intent_hash: int,
        sandbox_root: Path | None,
    ) -> tuple[Skill | None, Path | None]:
        """Subprocess + sandbox + collect plumbing for :meth:`extract_batch`.

        Returns ``(skill, sandbox)``. The caller owns sandbox cleanup
        (``shutil.rmtree``) so it can copy aux files first via
        :meth:`copy_aux_files`.
        """
        sandbox = self._make_sandbox(sandbox_root)
        system_prompt = prompt_template.format(
            sandbox_dir=str(sandbox),
            name_min_words=self.name_min_words,
            name_max_words=self.name_max_words,
            body_min_tokens=self.body_min_tokens,
            body_max_tokens=self.body_max_tokens,
            **format_kwargs,
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
            # Bug 4 fix: ``claude --print`` requires a user prompt
            # (from stdin or as the ``-p`` argument); the system
            # prompt alone is rejected with "Input must be provided
            # either through stdin or as a prompt argument when
            # using --print". The user prompt is the trigger
            # instruction — the system prompt carries the format
            # and constraints.
            "-p",
            f"Task: {task}\n\n"
            f"Synthesize a reusable SKILL.md into "
            f"{sandbox}/create/<your-skill-name>/SKILL.md.",
        ]

        logger.info(
            "extract_batch invoking: claude_cli=%s model=%s timeout=%ss",
            self.claude_cli,
            self.model or "(claude CLI default)",
            self.timeout_sec,
        )

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
            return None, sandbox
        except FileNotFoundError:
            logger.warning("claude CLI not found at %s", self.claude_cli)
            return None, sandbox

        if proc.returncode != 0:
            logger.warning(
                "extractor subprocess returned %s: stderr=%s",
                proc.returncode,
                proc.stderr[:500] if proc.stderr else "",
            )
            return None, sandbox

        skill = self._collect_skill(sandbox, intent_hash, task)
        return skill, sandbox

    # ------------------------------------------------------------------
    # Sandbox + collection
    # ------------------------------------------------------------------
    def _make_sandbox(self, root: Path | None) -> Path:
        import tempfile

        base = root or Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        # Bug fix (2026-06-22): the previous deterministic name
        # (hash of base only) collided across concurrent
        # ``extract_batch`` calls — when ``on_ended`` callbacks fire
        # for trials run with ``n_concurrent_trials >= 2``, every
        # call landed in the SAME sandbox path. The first call's
        # post-subprocess ``shutil.rmtree`` then deleted the cwd of
        # the second call's still-running ``claude --print``, which
        # failed with ``error: The current working directory was
        # deleted, so that command didn't work``. Fix: include
        # ``os.getpid()`` + ``time.time_ns()`` so each call gets a
        # unique sandbox path. The hash of base is kept (last 16
        # hex chars) as a stable, human-readable prefix.
        unique = f"{os.getpid()}_{time.time_ns()}_{qhash(str(base)):016x}"
        sandbox = base / f"skillq_extract_{unique}"[:48]
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

        # 2026-06-25: structural validation for failure-mode skills.
        # BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT requires both a
        # "Diagnostic checklist" section and a "Stop signal" section
        # in the body. Without these, the skill lacks the guard-rail
        # semantics the prompt is trying to enforce, so we reject.
        # Only checked for failure-prompt extraction; success-prompt
        # skills have no such requirement.
        if (
            self.prompt_mode == "failure"
            and self.enforce_failure_skill_structure
        ):
            body_lower = body.lower()
            if "diagnostic checklist" not in body_lower:
                logger.warning(
                    "_collect_skill: failure-mode skill %s missing "
                    "'Diagnostic checklist' section; rejected.",
                    skill_dir.name,
                )
                return None
            if "stop signal" not in body_lower:
                logger.warning(
                    "_collect_skill: failure-mode skill %s missing "
                    "'Stop signal' section; rejected.",
                    skill_dir.name,
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
                "source": "skillq_extract",
                "extract_mode": self.prompt_mode,
                "intent_hash": f"{intent_hash:016x}",
                "task_description": task[:500],
                "has_scripts": scripts_dir.is_dir(),
            },
        )

    def copy_aux_files(self, skill_dir: Path, target_dir: Path) -> int:
        """Copy scripts/, references/, assets/ from skill_dir to target_dir.

        Returns number of files copied. Preserves subdirectory structure.
        Uses shutil.copytree with dirs_exist_ok=True for each aux dir found.
        Does NOT copy SKILL.md (mirror_skill_to_host_dir handles that).
        """
        count = 0
        for subdir in ("scripts", "references", "assets"):
            src = skill_dir / subdir
            if src.is_dir():
                dst = target_dir / subdir
                shutil.copytree(src, dst, dirs_exist_ok=True)
                count += sum(1 for _ in src.rglob("*") if _.is_file())
        return count
