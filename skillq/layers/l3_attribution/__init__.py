"""L3 attribution + edit — paper Layer 3 implementation.

Public surface:

- :class:`Attribution` (5-enum), :class:`TrialAttribution`,
  :class:`SubtaskOutcome` — data models.
- :class:`AttributionBackend`, :class:`StubAttributionBackend`,
  :class:`LiteLLMAttributionBackend` — LLM backend protocol + impls.
- :func:`summarize_for_log` — log-line formatter.
- :class:`AttributionAnalyzer` — the per-trial attribution runner.
- :class:`EditRefiner`, :class:`EditProposalBackend`,
  :class:`StubEditBackend` — Layer 3 in-place edit.
- :data:`ATTRIBUTION_PROMPT`, :data:`EDIT_PROMPT` — own-wording prompts.

The 5-class :class:`Attribution` enum is **pinned** by
``tests/test_attribution_rename.py::test_enum_contract.py``;
renaming any of the five breaks the runtime contract.
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
from skillq.layers.l3_attribution.edit import (  # noqa: F401
    EditProposalBackend,
    StubEditBackend,
    EditRefiner,
)
from skillq.layers.l3_attribution.prompts import (  # noqa: F401
    ATTRIBUTION_PROMPT,
    EDIT_PROMPT,
)

__all__ = [
    # models
    "Attribution",
    "SubtaskOutcome",
    "TrialAttribution",
    "AttributionBackend",
    "StubAttributionBackend",
    "LiteLLMAttributionBackend",
    "summarize_for_log",
    # analyzer
    "AttributionAnalyzer",
    # edit
    "EditProposalBackend",
    "StubEditBackend",
    "EditRefiner",
    # prompts
    "ATTRIBUTION_PROMPT",
    "EDIT_PROMPT",
]