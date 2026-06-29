"""Mirror an auto-extracted skill to the host's shared skill directory.

When the paper method's L4 :class:`~skillq.layers.l4_evolve.create.SkillExtractor`
materializes a new skill via a ``claude --print`` subprocess, the
generated ``SKILL.md`` is written into a per-call ``/tmp/skillq_extract_*``
sandbox and the sandbox is ``shutil.rmtree``'d immediately after
``_collect_skill`` returns. The :class:`~skillq.shared.types.Skill`
dataclass's ``body`` field is the only survivor.

For the new skill to become visible to subsequent trials' agent
containers (which read the host skill library via a ``read_only: true``
bind-mount at ``/skills``), the body must also be written back to the
host directory the YAMLs declare in ``mounts_json[*].source``. The
:func:`mirror_skill_to_host_dir` function does exactly that:

- Writes ``<target_dir>/<skill.skill_id>/SKILL.md`` with the body verbatim.
- Is **idempotent by default**: if the file already exists, leave it alone
  (so a human-edited SKILL.md is never clobbered by auto-extract).
  Callers that need to overwrite an existing SKILL.md (e.g. L3
  :class:`~skillq.layers.l3_attribution.edit.EditRefiner` writing
  an in-place body edit) can opt in via ``force=True``. L4 Create
  keeps the default ``force=False`` to preserve the human-edit
  guarantee.
- Is **best-effort**: any ``OSError`` is caught and logged; never raises.
  A mirror failure must not abort the trial.
- Uses an **atomic write** (``tmp`` + ``os.replace``) so the agent
  cannot pick up a half-written file via the bind-mount mid-write.
- Treats ``target_dir=None`` as a no-op (some ``MethodConfig``s do not
  set ``seed_skills_dir``; the call is silently skipped).

Concurrency: with ``n_concurrent_trials=5`` (or higher), multiple
trials may flush simultaneously. Each flush writes to a distinct
``<skill_id>/`` directory, so there is no shared-path race. The
``exists()`` check is technically racy but the underlying
``write_text`` is not (a single trial owns one skill_id for one flush).

Step 1 of the 2026-06-26 refactor renamed and moved this module from
``skillq.shared.skill_mirror`` to ``skillq.shared.mirror``.
The function name is unchanged; only the file path / module name
changed. The old import path is kept as a thin re-export shim
until Step 7.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from skillq.shared.types import Skill

logger = logging.getLogger("skillq.shared.mirror")


def mirror_skill_to_host_dir(
    skill: Skill,
    target_dir: Path | None,
    *,
    force: bool = False,
) -> bool:
    """Write ``<target_dir>/<skill.skill_id>/SKILL.md`` from ``skill.body``.

    Parameters
    ----------
    skill : Skill
        The skill to write. ``skill.skill_id`` becomes the directory
        name; ``skill.body`` becomes ``SKILL.md``.
    target_dir : Path | None
        Host directory that the container bind-mounts at the
        agent's skills path (typically ``cfg.seed_skills_dir``).
        Created if missing. No-op when None.
    force : bool, default False
        Overwrite an existing SKILL.md at the target. The default
        ``False`` preserves the idempotent-skip contract for L4
        auto-extract (so a human-edited SKILL.md is never clobbered).
        L3 :class:`~skillq.layers.l3_attribution.edit.EditRefiner`
        passes ``force=True`` because the file L3 wrote on a prior
        trial is precisely the file L3 needs to overwrite now —
        without this, the L3 edit path is a silent no-op once the
        first edit has landed. See ``runtime/steps.py:step_incremental_edit``.

    Returns
    -------
    bool
        True iff a file was written (new or overwritten). False on
        idempotent skip (when ``force=False`` and the file exists),
        on any error, or when ``target_dir`` is None.
    """
    if target_dir is None:
        return False
    target_dir = Path(target_dir)
    skill_dir = target_dir / skill.skill_id
    target = skill_dir / "SKILL.md"
    try:
        if target.exists() and not force:
            logger.info(
                "mirror_skill_to_host_dir: SKILL.md already exists at %s; "
                "skipping (idempotent).",
                target,
            )
            return False
        skill_dir.mkdir(parents=True, exist_ok=True)
        # Atomic write: tmp + os.replace, so a half-written file
        # never appears at the bind-mount target.
        tmp = skill_dir / "SKILL.md.tmp"
        tmp.write_text(skill.body, encoding="utf-8")
        os.replace(tmp, target)
        logger.info(
            "mirrored skill %s -> %s (force=%s)",
            skill.skill_id,
            target,
            force,
        )
        return True
    except OSError as exc:
        logger.error(
            "Failed to mirror skill %s to %s: %s",
            skill.skill_id,
            target,
            exc,
        )
        return False


__all__ = ["mirror_skill_to_host_dir"]