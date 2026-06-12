"""Pydantic configuration for ``paper paper`` mode.

Fields map 1:1 to the symbols in the LQRL paper (Sec. 3.1-3.4). Defaults
differ from the implementation_guide skeleton (e.g. ``n_explore=8`` vs 10)
to make the mg defaults not a verbatim copy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PaperRetrievalArgs(BaseModel):
    """Agent-side retrieval toggle passed to :class:`PaperClaudeCodeAgent`."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    k1: int = 10
    k2: int = 3
    c_ucb: float = 0.5
    lambda_: float = 0.5
    embedder_model: str = "openai/text-embedding-3-large"


class MethodConfig(BaseModel):
    """Hyperparameters and runtime paths for the four-layer method."""

    model_config = ConfigDict(extra="forbid")

    # Layered-Q learning (Layer 2, Eq. 6)
    alpha: float = Field(default=0.3, ge=0.0, le=1.0)
    beta: float = Field(default=0.5, ge=0.0, le=1.0)
    increment_clip: float = Field(default=1.0, ge=0.0)

    # Two-stage retrieval (Layer 1, Eq. 4)
    lambda_: float = Field(default=0.5, ge=0.0, le=1.0)
    c_ucb: float = Field(default=0.5, ge=0.0)
    k1: int = Field(default=10, ge=1)
    k2: int = Field(default=3, ge=1)

    # Library management (Layer 3)
    theta_admit: float = Field(default=0.25, ge=0.0, le=1.0)
    theta_evict: float = Field(default=0.15, ge=0.0, le=1.0)
    b_max: int = Field(default=50, ge=1)
    n_explore: int = Field(default=8, ge=1)
    n_stale: int = Field(default=80, ge=1)

    # Near-miss (Layer 4)
    # Note: the previous ``edit_token_cap`` field (default 0.20) has
    # been removed. The LLM is now free to rewrite as much or as
    # little as it judges necessary. Quality control falls on the
    # verifier's r_learning signal feeding back into Eq. 6.
    theta_near_miss: float = Field(default=0.5, ge=0.0, le=1.0)

    # LLM models
    verifier_model: str = "openai/gpt-4o"
    editor_model: str = "openai/gpt-4o"
    embedder_model: str = "openai/text-embedding-3-small"
    embedder_dim: int = 1536
    attribution_model: str = "openai/gpt-4o"
    extractor_claude_cli: str = "claude"  # the CLI binary invoked for extract

    # === Per-subtask hook (refactor 2026-06-11) ===
    # The PreToolUse hook runs inside the agent container, fires
    # before every Skill tool call, ranks skills by
    #     score = (1-λ) sim_z + λ q_z + c_ucb sqrt(log N / (n+1))
    # and either approves the agent's call (if it's in the top-k)
    # or blocks + suggests the top-k + "or skip if none fit".
    hook_enabled: bool = True
    hook_top_k: int = Field(default=3, ge=1, le=10)
    hook_lambda: float = Field(default=0.5, ge=0.0, le=1.0)
    hook_c_ucb: float = Field(default=0.5, ge=0.0)
    hook_embedding_service_host: str = "host.docker.internal"
    hook_embedding_service_port: int = Field(default=8765, ge=1, le=65535)
    hook_embed_timeout_sec: float = Field(default=5.0, ge=0.1)

    # === Q-value update (per-subtask + trial) ===
    # Q(skill) += alpha * (w_subtask * r_subtask_mean
    #                   + w_task    * r_task
    #                   - Q(skill))
    # where r_subtask_mean is the mean of sub-task verdicts over
    # all calls to this skill in this trial, and r_task is the
    # trial-level reward from the main verifier. Soft constraint
    # on w_subtask + w_task (not enforced).
    q_alpha: float = Field(default=0.3, ge=0.0, le=1.0)
    q_w_subtask: float = Field(default=0.7, ge=0.0, le=1.0)
    q_w_task: float = Field(default=0.3, ge=0.0, le=1.0)
    q_r_subtask_success: float = Field(default=1.0)
    q_r_subtask_failure: float = Field(default=-1.0)
    q_subtask_verifier_model: str = "openai/gpt-4o"
    debug_keep_subtask_log: bool = True

    # Auto-extract (create_skill path) — opt-in, see bridge.py
    enable_auto_extract: bool = False
    extract_every_n_trials: int = Field(
        default=4, ge=1,
        description=(
            "Batched-evolve flush cadence. Every N qualifying successful "
            "trials (those whose attribution ∈ {SUCCESS_NO_SKILL_SEEN, "
            "SUCCESS_VIEWED_SKILL_BUT_NOT_USED} and where no retrieved "
            "skill has Q > theta_consider_used), spawn ONE claude "
            "--print subprocess that aggregates the N (task, knowledge) "
            "records into a single new SKILL.md. Default 4 mirrors "
            "SkillsVote's evolve_every_n_trials=1 default offset by the "
            "extra LLM call cost in the paper's per-trial attribution step."
        ),
    )
    extract_max_new_per_trial: int = Field(default=1, ge=0, le=10)
    extract_timeout_sec: int = Field(default=600, ge=10)
    theta_consider_used: float = Field(
        default=0.30, ge=0.0,
        description=(
            "If any retrieved skill has Q > theta_consider_used, we treat the "
            "trial as 'used a skill' and skip the extract trigger (even when "
            "the attribution says VIEWED_BUT_NOT_USED)."
        ),
    )
    new_skill_initial_q: float = Field(
        default=0.5, ge=-1.0, le=1.0,
        description=(
            "Initial Q-value assigned to a freshly created or seed skill, "
            "on the current trial's intent_hash (or on the (0, skill_id) "
            "sentinel for seed skills). Set 0.5 for an optimistic prior; "
            "0.0 for cautious; negative for an initial penalty."
        ),
    )
    seed_initial_q: float = Field(
        default=0.5, ge=-1.0, le=1.0,
        description=(
            "Q-value assigned to a skill loaded from the saved state "
            "that has no existing Q-table entry. Same semantics as "
            "new_skill_initial_q. Set 0.0 to disable seeding (skills "
            "start with the Q-table default of 0.0)."
        ),
    )

    # Persistence
    library_root: Path = Field(default=Path("./.mg_library"))
    state_path: Optional[Path] = None  # defaults to <library_root>/.state/method_state.json

    # Optional: agent-side retrieval step
    paper_retrieval: PaperRetrievalArgs | None = None

    def resolved_state_path(self) -> Path:
        if self.state_path is not None:
            return self.state_path
        return self.library_root / ".state" / "method_state.json"
