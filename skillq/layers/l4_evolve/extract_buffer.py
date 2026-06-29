"""L4 evolve — batched-extract buffer (Step 2 of the 2026-06-26 refactor).

Extracted from :mod:`skillq.layers.l4_evolve.extract_buffer.ExtractBuffer`.
Mirrors lqrl's ``evolve_every_n_trials`` shape: accumulate
(task, knowledge) records across N trials, flush when the buffer
hits ``n_trials_threshold``.

``mode`` per record:

- ``"success"`` — knowledge came from a successful trajectory
  (Rule 2: unused + success → new skill). Uses
  :data:`skillq.layers.l4_evolve.prompts.BATCHED_EXTRACT_SKILL_PROMPT`.
- ``"failure"`` — knowledge came from a failure attribution
  (Rule 5: unused + failure → new skill). Uses
  :data:`skillq.layers.l4_evolve.prompts.BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT`.

Records with different modes are flushed into separate batches so
each ``claude --print`` invocation gets the right prompt.

The previous legacy version had a duplicated ``__len__`` (line 494
+ 497 in the old bridge.py); that bug is fixed here (single
implementation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractBuffer:
    """Buffer of (task, knowledge, mode) records awaiting a batched-extract flush.

    See module docstring for the mode semantics. The buffer holds
    up to ``n_trials_threshold`` records before :meth:`add` signals
    the caller to flush; the actual flush calls
    :class:`skillq.layers.l4_evolve.create.SkillExtractor.extract_batch`.
    """

    n_trials_threshold: int
    pending: list[dict[str, Any]] = field(default_factory=list)

    def add(
        self,
        *,
        task: str,
        knowledge: str,
        mode: str = "success",
        gap_description: str = "",
    ) -> bool:
        """Add a record. Returns ``True`` when the buffer has hit its
        threshold (caller should then call :meth:`flush`).

        ``gap_description`` (2026-06-25, refined 2026-06-26) is the
        explicit "what skill the library should have contained"
        string from the attribution step. Empty for the
        no-action paths; populated when the verdict is one of
        the two gap-signaling enums:
        ``Attribution.FAILURE_SKILL_NOT_USED`` (failure path,
        library gap) or ``Attribution.SUCCESS_NO_SKILL_SEEN``
        (success path, no relevant skill available). The
        failure-path extract prompt uses this as the primary
        seed.
        """
        if not knowledge.strip():
            return False
        self.pending.append({
            "task": task,
            "knowledge": knowledge,
            "gap_description": gap_description,
            "mode": mode,
        })
        return len(self.pending) >= self.n_trials_threshold

    def flush(self) -> list[tuple[str, list[dict[str, Any]]]]:
        """Drain everything, grouped by mode.

        Returns a list of ``(mode, records)`` tuples; one tuple per
        mode that had at least one record. The caller feeds each
        tuple into a separate ``SkillExtractor.extract_batch`` call.
        """
        if not self.pending:
            return []
        return self._drain_by_mode()

    def _drain_by_mode(self) -> list[tuple[str, list[dict[str, Any]]]]:
        out: list[tuple[str, list[dict[str, Any]]]] = []
        for mode in ("success", "failure"):
            batch = [r for r in self.pending if r.get("mode", "success") == mode]
            if batch:
                # Strip the internal "mode" key from the records that go
                # to the extractor (it doesn't read it).
                out.append(
                    (mode, [{k: v for k, v in r.items() if k != "mode"} for r in batch])
                )
        self.pending = []
        return out

    def __len__(self) -> int:
        return len(self.pending)


__all__ = ["ExtractBuffer"]