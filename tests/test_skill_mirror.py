"""Unit tests for ``skillq.shared.mirror.mirror_skill_to_host_dir``.

The mirror function is invoked by the paper method's bridge after
``extract_batch`` returns a freshly-spawned skill, so that the new
``SKILL.md`` lands in the same host directory the YAML's bind-mount
sources (making the new skill visible to subsequent trials' agent
containers).

Contract under test:

- Happy path: a fresh mirror writes ``<target>/<id>/SKILL.md`` with
  the body verbatim and returns True.
- Idempotency: if the file already exists, it is left untouched
  (so a human-edited SKILL.md is never clobbered by auto-extract).
- ``None`` target: returns False, no raise.
- I/O failure: any ``OSError`` is caught and returns False, no raise.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from skillq.shared.mirror import mirror_skill_to_host_dir  # noqa: E402
from skillq.shared.types import Skill  # noqa: E402


def test_mirror_writes_skill_md(tmp_path: Path) -> None:
    """A fresh mirror writes <target>/<id>/SKILL.md with the body verbatim."""
    target = tmp_path / "host_skills"
    body = "---\nname: parse-cobol\n---\n# parse-cobol\n\nUse awk.\n"
    skill = Skill(skill_id="parse-cobol", body=body)

    written = mirror_skill_to_host_dir(skill, target)

    assert written is True
    out = target / "parse-cobol" / "SKILL.md"
    assert out.is_file()
    assert out.read_text(encoding="utf-8") == body


def test_mirror_is_idempotent_does_not_overwrite(tmp_path: Path) -> None:
    """If SKILL.md already exists, leave it untouched."""
    target = tmp_path / "host_skills"
    skill_dir = target / "edit-me"
    skill_dir.mkdir(parents=True)
    user_path = skill_dir / "SKILL.md"
    user_path.write_text("# human-edited body\n", encoding="utf-8")

    skill = Skill(skill_id="edit-me", body="# LLM-clobber attempt\n")
    written = mirror_skill_to_host_dir(skill, target)

    assert written is False
    assert user_path.read_text(encoding="utf-8") == "# human-edited body\n"


def test_mirror_force_overwrites_existing(tmp_path: Path) -> None:
    """Phase 10 Bug 3: force=True opts out of idempotency.

    L3 :class:`~skillq.layers.l3_attribution.edit.EditRefiner` writes
    an in-place body edit. The default ``force=False`` would silently
    skip the second (and later) edits — once the first edit has landed,
    the file L3 itself wrote blocks every subsequent L3 mirror. L3 calls
    ``mirror_skill_to_host_dir(skill, target, force=True)`` to opt in to
    overwriting. L4 keeps ``force=False`` (default) to preserve the
    "don't clobber human-edited SKILL.md" guarantee.
    """
    target = tmp_path / "host_skills"
    skill_dir = target / "chess-image-to-move"
    skill_dir.mkdir(parents=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("# ORIGINAL seed body\n", encoding="utf-8")

    # Default (force=False): idempotent skip — preserves existing file.
    skill_attempt = Skill(skill_id="chess-image-to-move", body="# LLM clobber\n")
    assert mirror_skill_to_host_dir(skill_attempt, target) is False
    assert skill_md.read_text(encoding="utf-8") == "# ORIGINAL seed body\n"

    # force=True (L3 path): overwrites with the new body.
    edited = Skill(skill_id="chess-image-to-move", body="# EDITED L3 body\n")
    assert mirror_skill_to_host_dir(edited, target, force=True) is True
    assert skill_md.read_text(encoding="utf-8") == "# EDITED L3 body\n"

    # Second L3 edit (force=True): overwrites again — round-trip
    # sanity that the mirror's force path is repeatable.
    edited_again = Skill(skill_id="chess-image-to-move", body="# EDITED L3 body v2\n")
    assert mirror_skill_to_host_dir(edited_again, target, force=True) is True
    assert skill_md.read_text(encoding="utf-8") == "# EDITED L3 body v2\n"


def test_mirror_target_none_is_noop() -> None:
    """Passing target_dir=None returns False without raising."""
    skill = Skill(skill_id="x", body="y")
    assert mirror_skill_to_host_dir(skill, None) is False


def test_mirror_handles_write_failure(tmp_path: Path) -> None:
    """An OSError during write is caught; returns False; no raise."""
    # Force mkdir to fail: the parent of the target is a regular file,
    # so mkdir(parents=True) raises NotADirectoryError (a subclass of OSError).
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    target = blocker / "skills"  # parent is a file → mkdir will fail

    skill = Skill(skill_id="oops", body="x")
    assert mirror_skill_to_host_dir(skill, target) is False
