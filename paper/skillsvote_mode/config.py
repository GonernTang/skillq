"""Pydantic configuration for ``paper skillsvote`` mode.

The skillsvote_mode is a **pass-through** to the upstream
``skills_vote`` package (the SkillsVote paper's lifecycle
governance system — recommend / feedback / evolve). It is the
**baseline** that the LQRL paper compares against, not the LQRL
paper's method itself (see ``paper.paper_mode`` for the LQRL method).

This module exists primarily to host the ``SkillsVoteModeConfig``
marker class so that downstream code can
``isinstance(cfg, SkillsVoteModeConfig)``-style type-check the
pass-through layer if it wants to.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class SkillsVoteModeConfig(BaseModel):
    """Pass-through marker. ``extra='allow'`` because the upstream
    ``SkillsVoteConfig`` has fields we don't enumerate here.
    """

    model_config = ConfigDict(extra="allow")
