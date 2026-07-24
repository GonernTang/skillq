"""L4 evolve — paper Layer 4 (all skill-mutation actions) implementation.

Public surface:

- :class:`SkillExtractor` — ``claude --print`` subprocess that
  materialises a new SKILL.md from aggregated (task, knowledge)
  records (Rule 2 success path + Rule 5 failure path).
- :class:`EditRefiner` — incremental in-place editing of existing
  skills on failure (moved from l3_attribution, 2026-07-20).
- :class:`ExtractBuffer` — accumulates (task, knowledge, mode)
  records and flushes them in batches when the threshold is hit.
- :data:`BATCHED_EXTRACT_SKILL_PROMPT` /
  :data:`BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT` /
  :data:`EDIT_PROMPT` — own-wording prompts.
"""

from skillq.layers.l4_evolve.create import SkillExtractor  # noqa: F401
from skillq.layers.l4_evolve.edit import (  # noqa: F401
    EditProposalBackend,
    EditRefiner,
    StubEditBackend,
    validate_edited_skill,
)
from skillq.layers.l4_evolve.extract_buffer import ExtractBuffer  # noqa: F401
from skillq.layers.l4_evolve.prompts import (  # noqa: F401
    BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT,
    BATCHED_EXTRACT_SKILL_PROMPT,
    EDIT_PROMPT,
)

__all__ = [
    "SkillExtractor",
    "ExtractBuffer",
    "EditRefiner",
    "EditProposalBackend",
    "StubEditBackend",
    "validate_edited_skill",
    "BATCHED_EXTRACT_SKILL_PROMPT",
    "BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT",
    "EDIT_PROMPT",
]
