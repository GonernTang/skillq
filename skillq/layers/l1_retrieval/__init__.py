"""L1 retrieval — Eq. 4 scoring + Hard Gate (single source of truth).

Public surface:

- :func:`skillq.layers.l1_retrieval.scoring.score_skills` — the
  Eq. 4 scoring pipeline (Hard Gate → multiplicative / additive →
  top-k). Used by ``services.ranking_service`` (host-side ``/rank``)
  and by the parity test that pins bit-exact equivalence with the
  legacy container-side inline implementation.
- :func:`skillq.layers.l1_retrieval.scoring.apply_hard_gate` —
  the gating rule, callable in isolation for unit tests.
- :func:`skillq.layers.l1_retrieval.force_use_text.format_top_k` /
  :func:`format_pull_context` — the user-facing reminder text.
- :func:`skillq.layers.l1_retrieval.transcript_query.build_query_text` —
  the query string the embedder sees.

The container-side hook (``runtime/hook.py`` in Step 5) will call
``/rank`` over HTTP rather than re-implementing Eq. 4 locally.
"""

from skillq.layers.l1_retrieval.scoring import (  # noqa: F401
    cosine,
    zscore,
    apply_hard_gate,
    score_skills,
)
from skillq.layers.l1_retrieval.force_use_text import (  # noqa: F401
    format_top_k,
    format_pull_context,
    NO_RELEVANT_SKILLS_DENY,
    NO_RELEVANT_SKILLS_PULL,
)
from skillq.layers.l1_retrieval.transcript_query import (  # noqa: F401
    read_recent_assistant_messages,
    build_query_text,
    QUERY_MAX_CHARS,
)
from skillq.layers.l1_retrieval.hard_gate import (  # noqa: F401
    apply_hard_gate as apply_hard_gate_alias,  # same object, alias import
)

__all__ = [
    "cosine",
    "zscore",
    "apply_hard_gate",
    "score_skills",
    "format_top_k",
    "format_pull_context",
    "NO_RELEVANT_SKILLS_DENY",
    "NO_RELEVANT_SKILLS_PULL",
    "read_recent_assistant_messages",
    "build_query_text",
    "QUERY_MAX_CHARS",
]