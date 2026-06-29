"""L1 Hard Gate — re-export shim for the gating helper.

Step 2 of the 2026-06-26 refactor. The Hard Gate logic lives in
:func:`skillq.layers.l1_retrieval.scoring.apply_hard_gate` (kept in
``scoring.py`` so the gate is co-located with the scoring pipeline
that consumes its output). This module exists for two reasons:

1. **Discoverability** — searching ``hard_gate`` in the layers
   directory lands here, with the docstring explaining the design.
2. **Stable import surface** — future code can
   ``from skillq.layers.l1_retrieval.hard_gate import apply_hard_gate``
   without coupling to ``scoring.py``'s internal layout.

The function is the same object — no shadow implementation.
"""

from skillq.layers.l1_retrieval.scoring import apply_hard_gate

__all__ = ["apply_hard_gate"]