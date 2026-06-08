"""Entrypoint for ``mg lqrl`` — pure pass-through to upstream lqrl.

This module deliberately contains **no** implementation logic. The
agent, hook, prompt, and evolve pipeline are all provided by the
upstream ``lqrl`` package. ``mg.lqrl_mode`` exists only to:
1. Expose the ``mg lqrl ...`` command-line surface in a uniform way
   with ``mg paper ...``.
2. Anchor a future maintainer expectation that "lqrl mode" is the
   branch that re-uses lqrl verbatim, and "paper mode" is the branch
   that ships its own implementation.
"""

from __future__ import annotations

from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Programmatic entrypoint; equivalent to ``mg lqrl <argv>``."""
    from mg.lqrl_mode.cli import build_parser

    # ``main()`` is normally reached through ``mg.cli.build_parser`` which
    # has already constructed a top-level parser. For programmatic use we
    # rebuild the same parser here, but the path through ``mg.cli`` is
    # the canonical one.
    import argparse

    parser = argparse.ArgumentParser(prog="mg lqrl")
    build_parser(parser)
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)
