"""Hashing utilities for intent (state) keys in the Q-table.

Matches the convention used by the ``implementation_guide`` skeleton
(sha1 of the text, take the first 16 hex chars, parse as int). Centralised
here so the Q-table key format is consistent across modules.
"""

from __future__ import annotations

import hashlib


def qhash(text: str) -> int:
    """Return an ``int`` Q-table key derived from the input text.

    The :class:`paper.method.library.LibManager` uses ``(intent_hash, skill_id)``
    pairs as Q-table keys; this function produces the ``intent_hash``.
    """
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return int(digest, 16)
