"""Top-level ``mg`` CLI dispatch.

Subcommands:

- ``mg lqrl ...``     — pass-through to upstream lqrl (see :mod:`mg.lqrl_mode.cli`).
- ``mg paper ...``    — run the LQRL paper's four-layer method
  (see :mod:`mg.paper_mode.cli`).
- ``mg prebuild ...`` — pre-build the per-task Docker images that
  benchmark trials need (TB 2.0 / TB Pro / SWE-Bench Pro).
  Thin wrapper around lqrl's ``scripts/prebuild_images.py``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mg",
        description=(
            "Branch-style entrypoint: mg lqrl re-uses the upstream lqrl "
            "lifecycle; mg paper runs the LQRL paper's four-layer method."
        ),
    )
    sub = parser.add_subparsers(dest="mode", required=True, metavar="MODE")

    # Defer imports so that, e.g., ``mg lqrl --help`` does not need to
    # import the paper-side modules (or vice-versa).
    from mg.lqrl_mode.cli import build_parser as build_lqrl
    from mg.paper_mode.cli import build_parser as build_paper
    from mg.prebuild_cli import build_parser as build_prebuild

    lqrl_sub = sub.add_parser(
        "lqrl",
        help="Run the upstream lqrl lifecycle (recommend → feedback → evolve).",
    )
    build_lqrl(lqrl_sub)

    paper_sub = sub.add_parser(
        "paper",
        help=(
            "Run the LQRL paper's four-layer method "
            "(UCB retrieval → β-Q → lib mgmt → near-miss edit)."
        ),
    )
    build_paper(paper_sub)

    prebuild_sub = sub.add_parser(
        "prebuild",
        help=(
            "Pre-build per-task Docker images (TB 2.0 / TB Pro / SWE-Bench Pro). "
            "Wraps lqrl's prebuild_images.py."
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
