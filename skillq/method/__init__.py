"""paper/method — the four layers of the SkillQ paper.

Public API:

- :class:`paper.method.types.Skill` / :class:`Qlib` / :class:`Verdict` /
  :class:`RetrievalResult` — core data types.
- :class:`paper.method.retrieval.TwoStageRanker` — Phase-A cosine recall +
  Phase-B UCB re-rank (Eq. 4).
- :class:`paper.method.layered_q.BetaLayeredQ` — Eq. 6 reference
  implementation (the bridge uses a generalised weighted target).
- :class:`paper.method.library.LibManager` — admission / eviction /
  rejuvenation (Sec. 3.3).
- :class:`paper.method.near_miss.NearMissRefiner` — Layer 4.
- :class:`paper.method.verifier.IndependentVerifier` — Sec. 3.2 information
  isolation, 4-axis scoring.
- :class:`paper.method.editor_backend.LiteLLMEditBackend` — LiteLLM
  generative-mode edit backend.
- :func:`paper.method.hash.qhash` — intent (state) key for the Q-table.
- :mod:`paper.method.prompts` — own-wording prompt strings.
- :mod:`paper.method.state` — ``QlibState`` JSON serialisation.
"""

from skillq.method.editor_backend import LiteLLMEditBackend
from skillq.method.hash import qhash
from skillq.method.layered_q import (
    BetaLayeredQ,
    check_improvement_penalty_resolution,
    expected_variance,
    improvement_penalty_threshold,
    variance_bound,
)
from skillq.method.library import (
    LibManager,
    forgetting_rate_upper_bound,
)
from skillq.method.near_miss import (
    EditProposalBackend,
    NearMissRefiner,
    StubEditBackend,
)
from skillq.method.prompts import (
    ATTRIBUTION_PROMPT,
    BATCHED_EXTRACT_SKILL_PROMPT,
    EDIT_PROMPT,
    VERIFIER_PROMPT,
)
from skillq.method.retrieval import (
    Embedder,
    LiteLLMEmbedder,
    QValueLookup,
    StubEmbedder,
    TwoStageRanker,
    cosine,
    zscore,
)
from skillq.method.types import Qlib, RetrievalResult, Skill, Verdict
from skillq.method.verifier import (
    IndependentVerifier,
    LiteLLMVerifierBackend,
    StubVerifierBackend,
    VerifierBackend,
    batch_score,
)

__all__ = [
    # types
    "Skill",
    "Qlib",
    "Verdict",
    "RetrievalResult",
    # retrieval
    "Embedder",
    "StubEmbedder",
    "LiteLLMEmbedder",
    "TwoStageRanker",
    "QValueLookup",
    "zscore",
    "cosine",
    # layered Q
    "BetaLayeredQ",
    "check_improvement_penalty_resolution",
    "expected_variance",
    "variance_bound",
    "improvement_penalty_threshold",
    # library
    "LibManager",
    "forgetting_rate_upper_bound",
    # near-miss
    "EditProposalBackend",
    "NearMissRefiner",
    "StubEditBackend",
    # verifier
    "VerifierBackend",
    "StubVerifierBackend",
    "LiteLLMVerifierBackend",
    "IndependentVerifier",
    "batch_score",
    # editor backend
    "LiteLLMEditBackend",
    # hashing
    "qhash",
    # prompts
    "VERIFIER_PROMPT",
    "EDIT_PROMPT",
    "ATTRIBUTION_PROMPT",
    "BATCHED_EXTRACT_SKILL_PROMPT",
]
