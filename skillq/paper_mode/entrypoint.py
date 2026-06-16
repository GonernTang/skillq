"""Entrypoint for ``paper paper`` — runs the four-layer SkillQ paper method."""

from __future__ import annotations

from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Programmatic entrypoint; equivalent to ``paper paper <argv>``."""
    import argparse

    from skillq.paper_mode.cli import build_parser

    parser = argparse.ArgumentParser(prog="paper paper")
    build_parser(parser)
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)
