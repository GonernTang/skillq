"""Entrypoint for ``mg skillsvote`` — pure pass-through to upstream SkillsVote.

This module deliberately contains **no** implementation logic. The
agent, hook, prompt, and evolve pipeline are all provided by the
upstream ``skills_vote`` package. ``mg.skillsvote_mode`` exists
only to:

1. Expose the ``mg skillsvote ...`` command-line surface in a uniform
   way with ``mg paper ...``.
2. Anchor a maintainer expectation: ``mg skillsvote`` runs the
   SkillsVote **baseline** (the comparison method); ``mg paper`` runs
   the **LQRL paper's** method (the user's own contribution).
"""

from __future__ import annotations

from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Programmatic entrypoint; equivalent to ``mg skillsvote <argv>``."""
    from mg.skillsvote_mode.cli import build_parser

    # ``main()`` is normally reached through ``mg.cli.build_parser`` which
    # has already constructed a top-level parser. For programmatic use we
    # rebuild the same parser here, but the path through ``mg.cli`` is
    # the canonical one.
    import argparse

    parser = argparse.ArgumentParser(prog="mg skillsvote")
    build_parser(parser)
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)
