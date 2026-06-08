"""Pydantic configuration for ``mg lqrl`` mode.

The lqrl_mode does **not** re-define any of lqrl's own config schema
(SkillsVoteConfig). We pass the entire YAML dict (minus the ``job:``
subtree) through to ``skills_vote.harbor.cli.run_job`` and let lqrl
itself validate it.

This module exists primarily to host the ``LqrlModeConfig`` marker class
so that downstream code can ``isinstance(cfg, LqrlModeConfig)``-style
type-check the pass-through layer if it wants to.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LqrlModeConfig(BaseModel):
    """Pass-through marker. ``extra='allow'`` because lqrl's
    ``SkillsVoteConfig`` has fields we don't enumerate here.
    """

    model_config = ConfigDict(extra="allow")
