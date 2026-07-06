"""Test-suite fixtures and environment priming.

Step 7 (2026-06-27) added this file because the new container-side
``skillq.runtime.hook`` module asserts the presence of
``SKILLQ_RANK_ENDPOINT`` at import time (fail-loud contract — the
hook has no sensible default and would silently misbehave without
the daemon URL). Several tests import the hook module to call its
helper functions; without priming the env var those imports raise
``KeyError`` and abort test collection.

2026-07-01 (Bug #51/#52 fix): ``SKILLQ_CALLS_LOG_PATH`` is no
longer read by the hook at import time (per-trial state now lives
in the bind-mounted settings.json). We drop the priming here.
The hook's ``CALLS_LOG_PATH`` module-level read still works
via ``os.environ.get(..., "")`` for back-compat, but the test
suite doesn't need to seed it.
"""

from __future__ import annotations

import os

# Must run BEFORE any test module imports skillq.runtime.hook.
os.environ.setdefault(
    "SKILLQ_RANK_ENDPOINT", "http://127.0.0.1:8765",
)
