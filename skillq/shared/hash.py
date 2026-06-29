"""Hashing utilities for intent (state) keys in the Q-table.

Matches the convention used by the ``implementation_guide`` skeleton
(sha1 of the text, take the first 16 hex chars, parse as int). Centralised
here so the Q-table key format is consistent across modules.

Step 1 of the 2026-06-26 refactor moved this module from
``skillq.shared.hash`` to ``skillq.shared.hash``. The old
import path is kept as a thin re-export shim until Step 7.
"""

from __future__ import annotations

import hashlib


def qhash(text: str) -> int:
    """Return an ``int`` Q-table key derived from the input text.

    The :class:`skillq.shared.q_table.LibManager` uses ``(intent_hash, skill_id)``
    pairs as Q-table keys; this function produces the ``intent_hash``.
    """
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return int(digest, 16)