"""L4 evolve — paper Layer 4 (auto-extract new skills) implementation.

Public surface:

- :class:`SkillExtractor` — ``claude --print`` subprocess that
  materialises a new SKILL.md from aggregated (task, knowledge)
  records (Rule 2 success path + Rule 5 failure path).
- :class:`ExtractBuffer` — accumulates (task, knowledge, mode)
  records and flushes them in batches when the threshold is hit.
- :data:`BATCHED_EXTRACT_SKILL_PROMPT` /
  :data:`BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT` — own-wording
  prompts.
"""

from skillq.layers.l4_evolve.create import SkillExtractor  # noqa: F401
from skillq.layers.l4_evolve.extract_buffer import ExtractBuffer  # noqa: F401
from skillq.layers.l4_evolve.prompts import (  # noqa: F401
    BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT,
    BATCHED_EXTRACT_SKILL_PROMPT,
)

__all__ = [
    "SkillExtractor",
    "ExtractBuffer",
    "BATCHED_EXTRACT_SKILL_PROMPT",
    "BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT",
]
