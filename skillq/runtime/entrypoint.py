"""Top-level ``paper paper`` entrypoint — Step 4 (2026-06-26) refactor.

The :mod:`skillq.cli` dispatch points here. Identical surface to
:mod:`skillq.runtime.entrypoint`; only the *implementation*
changes (orchestrator → :mod:`skillq.runtime.orchestrator`).

The contract (per §8 of the plan):

- ``main(argv)`` parses ``paper paper <subcommand>`` and runs
  the matching handler. Returns the integer exit code.
- ``run_paper_job_sync(path, method)`` is the programmatic
  entrypoint — used by ``runtime.cli._run_command``.

Both names are re-exported by :mod:`skillq.runtime.__init__` for
convenience.
"""

from __future__ import annotations

from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """Programmatic entrypoint; equivalent to ``paper paper <argv>``.

    Builds the parser via :func:`skillq.runtime.cli.build_parser`,
    dispatches to the registered handler.
    """
    import argparse

    from skillq.runtime.cli import build_parser

    parser = argparse.ArgumentParser(prog="paper paper")
    build_parser(parser)
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


# Re-exported for ``runtime.cli._run_command``.
from skillq.runtime.orchestrator import run_paper_job_sync  # noqa: E402

__all__ = ["main", "run_paper_job_sync"]