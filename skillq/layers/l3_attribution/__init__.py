"""L3 attribution — paper Layer 3 implementation (read-only analysis).

Public surface:

- :class:`Attribution` (5-enum), :class:`TrialAttribution`,
  :class:`SubtaskOutcome` — data models.
- :class:`AttributionBackend`, :class:`StubAttributionBackend`,
  :class:`LiteLLMAttributionBackend` — LLM backend protocol + impls.
- :func:`summarize_for_log` — log-line formatter.
- :class:`AttributionAnalyzer` — the per-trial attribution runner.
- :data:`ATTRIBUTION_PROMPT` — own-wording attribution prompt.

EditRefiner and EDIT_PROMPT moved to ``layers/l4_evolve/``
(2026-07-20 refactor: all skill-mutation actions belong in L4).
"""

from skillq.layers.l3_attribution.models import (  # noqa: F401
    Attribution,
    SubtaskOutcome,
    TrialAttribution,
    AttributionBackend,
    StubAttributionBackend,
    LiteLLMAttributionBackend,
    summarize_for_log,
)
from skillq.layers.l3_attribution.analyzer import AttributionAnalyzer  # noqa: F401
from skillq.layers.l3_attribution.prompts import ATTRIBUTION_PROMPT  # noqa: F401

__all__ = [
    "Attribution",
    "SubtaskOutcome",
    "TrialAttribution",
    "AttributionBackend",
    "StubAttributionBackend",
    "LiteLLMAttributionBackend",
    "summarize_for_log",
    "AttributionAnalyzer",
    "ATTRIBUTION_PROMPT",
]