"""Test-suite fixtures and environment priming.

Step 7 (2026-06-27) added this file because the new container-side
``skillq.runtime.hook`` module asserts the presence of
``SKILLQ_RANK_ENDPOINT`` at import time (fail-loud contract — the
hook has no sensible default and would silently misbehave without
the daemon URL). Several tests import the hook module to call its
helper functions; without priming the env var those imports raise
``KeyError`` and abort test collection.

We also prime ``SKILLQ_CALLS_LOG_PATH`` because the hook module reads
it at import time too (it's a per-trial path written by the wiring
layer). The hook's container-side main() never runs in unit tests;
the imports below only test the helper functions.
"""

from __future__ import annotations

import os

# Must run BEFORE any test module imports skillq.runtime.hook.
os.environ.setdefault(
    "SKILLQ_RANK_ENDPOINT", "http://127.0.0.1:8765",
)
os.environ.setdefault(
    "SKILLQ_CALLS_LOG_PATH", "/tmp/skillq_test_calls.jsonl",
)
