"""Top-level ``paper`` CLI dispatch.

Subcommands:

- ``paper skillsvote ...`` — pass-through to the upstream ``skills_vote``
  package (the SkillsVote baseline; the comparison method for the
  SkillQ paper). See :mod:`paper.skillsvote_mode.cli`.
- ``paper paper ...``      — run the SkillQ paper's four-layer method
  (the user's own contribution). See :mod:`paper.paper_mode.cli`.
- ``paper prebuild ...``   — pre-build the per-task Docker images that
  benchmark trials need (TB 2.0 / TB Pro / SWE-Bench Pro). Thin
  wrapper around the upstream prebuild script.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skillq",
        description=(
            "Branch-style entrypoint: `skillq skillsvote` runs the upstream "
            "SkillsVote baseline (comparison method); `skillq paper` runs the "
            "SkillQ paper's four-layer method (the user's own contribution)."
        ),
    )
    sub = parser.add_subparsers(dest="mode", required=True, metavar="MODE")

    # Defer imports so that, e.g., ``paper skillsvote --help`` does not need
    # to import the paper-side modules (or vice-versa).
    from skillq.skillsvote_mode.cli import build_parser as build_skillsvote
    from skillq.paper_mode.cli import build_parser as build_paper
    from skillq.prebuild_cli import build_parser as build_prebuild

    sv_sub = sub.add_parser(
        "skillsvote",
        help=(
            "Run the SkillsVote baseline (recommend → feedback → evolve). "
            "This is the *comparison method* for the SkillQ paper."
        ),
    )
    build_skillsvote(sv_sub)

    paper_sub = sub.add_parser(
        "paper",
        help=(
            "Run the SkillQ paper's four-layer method "
            "(UCB retrieval → β-Q → lib mgmt → near-miss edit). "
            "This is the *user's own contribution*."
        ),
    )
    build_paper(paper_sub)

    prebuild_sub = sub.add_parser(
        "prebuild",
        help=(
            "Pre-build per-task Docker images (TB 2.0 / TB Pro / SWE-Bench Pro). "
            "Wraps the upstream prebuild_images.py."
        ),
    )
    build_prebuild(prebuild_sub)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
