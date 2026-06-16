"""Entrypoint for ``paper skillsvote`` — pure pass-through to upstream SkillsVote.

This module deliberately contains **no** implementation logic. The
agent, hook, prompt, and evolve pipeline are all provided by the
upstream ``skills_vote`` package. ``paper.skillsvote_mode`` exists
only to:

1. Expose the ``paper skillsvote ...`` command-line surface in a uniform
   way with ``paper paper ...``.
2. Anchor a maintainer expectation: ``paper skillsvote`` runs the
   SkillsVote **baseline** (the comparison method); ``paper paper`` runs
   the **SkillQ paper's** method (the user's own contribution).
"""

from __future__ import annotations

from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Programmatic entrypoint; equivalent to ``paper skillsvote <argv>``."""
    from skillq.skillsvote_mode.cli import build_parser

    # ``main()`` is normally reached through ``paper.cli.build_parser`` which
    # has already constructed a top-level parser. For programmatic use we
    # rebuild the same parser here, but the path through ``paper.cli`` is
    # the canonical one.
    import argparse

    parser = argparse.ArgumentParser(prog="paper skillsvote")
    build_parser(parser)
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)
