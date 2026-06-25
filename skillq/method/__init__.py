"""skillq/method — the SkillQ paper method, runtime-trimmed.

This package holds the orchestration primitives and embedder backends the
host-side runtime (``skillq/skillq_runtime/``) imports. The algorithmic
truth lives in two places:

  - Retrieval (L1): ``skillq/skillq_runtime/hook.py:_score_skills`` —
    Hard Gate + multiplicative scoring + UCB exploration. Re-implemented
    in pure-Python stdlib because the agent container cannot import
    ``skillq.method.*``.
  - Q-learning (L2): ``skillq/skillq_runtime/bridge.py:_q_update`` —
    plain Eq. 5 with optional cosine-weighted delta. The paper's Eq. 6
    ``BetaLayeredQ`` (β-mixed ``r_task + r_learning``) and the
    information-isolated ``IndependentVerifier`` were removed in the
    2026-06-25 dead-code purge.

Public API — every symbol listed below is imported by something in
``skillq/skillq_runtime/`` (or by ``tests/``).

- :class:`skillq.method.types.Skill` / :class:`Qlib` — core data types.
- :class:`skillq.method.library.LibManager` — Q-table + lowest-Q eviction
  (Sec. 3.3).
- :class:`skillq.method.state.QlibState` — ``method_state.json``
  serialisation.
- :class:`skillq.method.vector_table.VectorTable` + helpers —
  ``emb_cache.json`` description-embedding cache.
- :class:`skillq.method.extractor.SkillExtractor` — Layer 4 batched
  skill extraction (batched ``claude --print`` subprocess).
- :class:`skillq.method.edit.EditRefiner` — Layer 3 in-place edit.
- :class:`skillq.method.attribution.AttributionAnalyzer` — per-trial
  outcome attribution.
- :class:`skillq.method.retrieval.Embedder` / :class:`StubEmbedder` /
  :class:`LiteLLMEmbedder` — embedder backends used by the bridge.
- :func:`skillq.method.skill_mirror.mirror_skill_to_host_dir` — write
  an extracted skill back to ``seed_skills_dir`` so subsequent trial
  containers can see it via the bind-mount.
- :mod:`skillq.method.embedding_service` — FastAPI daemon that exposes
  the host embedder to the container-side hook over HTTP.
- :class:`skillq.method.editor_backend.LiteLLMEditBackend` — LiteLLM
  generative-mode edit backend.
- :func:`skillq.method.hash.qhash` — deterministic intent key.
- :mod:`skillq.method.prompts` — own-wording prompt strings used by the
  above modules.
"""

from skillq.method.attribution import (
    Attribution,
    AttributionAnalyzer,
    AttributionBackend,
    LiteLLMAttributionBackend,
    StubAttributionBackend,
    TrialAttribution,
)
from skillq.method.editor_backend import LiteLLMEditBackend
from skillq.method.embedding_service import (
    EmbeddingServiceHandle,
    build_fastapi_app,
    start_embedding_service_background,
    stop_embedding_service,
    sync_embed,
)
from skillq.method.extractor import SkillExtractor
from skillq.method.hash import qhash
from skillq.method.library import LibManager
from skillq.method.edit import (
    EditProposalBackend,
    EditRefiner,
    StubEditBackend,
)
from skillq.method.prompts import (
    ATTRIBUTION_PROMPT,
    BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT,
    BATCHED_EXTRACT_SKILL_PROMPT,
    EDIT_PROMPT,
)
from skillq.method.retrieval import (
    Embedder,
    LiteLLMEmbedder,
    StubEmbedder,
)
from skillq.method.skill_mirror import mirror_skill_to_host_dir
from skillq.method.state import QlibState
from skillq.method.types import Qlib, Skill
from skillq.method.vector_table import (
    VectorTable,
    _description_of,
    json_payload_to_vector_table,
    sync_lib_to_vector_table,
    vector_table_to_json_payload,
)

__all__ = [
    # types
    "Skill",
    "Qlib",
    # retrieval (embedder backends only — the runtime algorithm lives
    # in skillq_runtime/hook.py)
    "Embedder",
    "StubEmbedder",
    "LiteLLMEmbedder",
    # library
    "LibManager",
    # state + emb cache
    "QlibState",
    "VectorTable",
    "sync_lib_to_vector_table",
    "vector_table_to_json_payload",
    "json_payload_to_vector_table",
    # L4 (extraction) + L3 (edit)
    "SkillExtractor",
    "EditRefiner",
    "EditProposalBackend",
    "StubEditBackend",
    # attribution
    "Attribution",
    "TrialAttribution",
    "AttributionAnalyzer",
    "AttributionBackend",
    "StubAttributionBackend",
    "LiteLLMAttributionBackend",
    # skill mirror (host ↔ container sync)
    "mirror_skill_to_host_dir",
    # embedding service daemon
    "EmbeddingServiceHandle",
    "build_fastapi_app",
    "start_embedding_service_background",
    "stop_embedding_service",
    "sync_embed",
    # editor backend
    "LiteLLMEditBackend",
    # hashing
    "qhash",
    # prompts
    "EDIT_PROMPT",
    "ATTRIBUTION_PROMPT",
    "BATCHED_EXTRACT_SKILL_PROMPT",
    "BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT",
]