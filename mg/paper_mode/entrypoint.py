"""Entrypoint for ``mg paper`` — runs the four-layer LQRL paper method."""

from __future__ import annotations

from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Programmatic entrypoint; equivalent to ``mg paper <argv>``."""
    import argparse

    from mg.paper_mode.cli import build_parser

    parser = argparse.ArgumentParser(prog="mg paper")
    build_parser(parser)
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)
