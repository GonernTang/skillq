"""Pydantic configuration for ``paper paper`` mode.

Fields map 1:1 to the symbols in the SkillQ paper (Sec. 3.1-3.4). Defaults
differ from the implementation_guide skeleton (e.g. ``n_explore=8`` vs 10)
to make the mg defaults not a verbatim copy.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


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

    # === Q-value update (per-subtask reward is THE paper's r) ===
    # Q(skill) += alpha * (w_subtask * r_subtask_mean
    #                   + w_task    * r_task_bin
    #                   - Q(skill))
    #
    # The paper defines r as "the reward of the task in which the
    # skill was just called" — i.e. the **sub-task** reward (LLM
    # judge's per-Skill-call verdict), not the trial-level reward.
    # We expose both as config knobs for experimental flexibility,
    # but the default ``q_w_task = 0`` disables the trial-level
    # signal so the Q-update reduces to the paper's formula::
    #
    #     Q(skill) += alpha * (r_subtask_mean - Q(skill))
    #
    # - ``r_subtask_mean`` ∈ [0, 1]: mean of binary per-Skill-call
    #   LLM-judge verdicts within the trial (per-skill success rate).
    # - ``r_task_bin`` ∈ {0, 1}: binarized trial-level reward
    #   (1 if the raw reward > 0.5, else 0). Default weight 0 →
    #   ignored. Set non-zero if you want trial-level signal mixed in.
    q_alpha: float = Field(default=0.3, ge=0.0, le=1.0)
    q_w_subtask: float = Field(default=1.0, ge=0.0, le=1.0)
    q_w_task: float = Field(default=0.0, ge=0.0, le=1.0)
    q_subtask_verifier_model: str = "openai/gpt-4o"
    debug_keep_subtask_log: bool = True

    # Auto-extract (create_skill path) — opt-in, see bridge.py
    enable_auto_extract: bool = False
    extract_every_n_trials: int = Field(
        default=4, ge=1,
        description=(
            "Batched-evolve flush cadence. Every N qualifying successful "
            "trials (those whose attribution ∈ {SUCCESS_NO_SKILL_SEEN, "
            "SUCCESS_VIEWED_SKILL_BUT_NOT_USED}), spawn ONE claude "
            "--print subprocess that aggregates the N (task, knowledge) "
            "records into a single new SKILL.md. Default 4 mirrors "
            "SkillsVote's evolve_every_n_trials=1 default offset by the "
            "extra LLM call cost in the paper's per-trial attribution step."
        ),
    )
    extract_max_new_per_trial: int = Field(default=1, ge=0, le=10)
    extract_timeout_sec: int = Field(default=600, ge=10)
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

    # === Retrieval mode (Method A vs Method B) ===
    # Method A ("agentic") — paper's small-library design: SKILL.md
    # files are bind-mounted into the container with Q values in
    # frontmatter, plus a bash search script. The agent uses
    # ``bash _search.sh "query"`` to find relevant skills and picks
    # the top-1 itself. No PreToolUse hook gating.
    # Method B ("hook") — paper's large-library design: PreToolUse
    # hook intercepts every Skill() call, computes Eq.4 score, and
    # allow/denies.
    # "auto" picks agentic when ``len(lib) < library_size_threshold``,
    # else hook. Decided at on_trial_started time.
    retrieval_mode: str = Field(
        default="auto",
        description=(
            'Retrieval mode: "auto" (switch on lib size), '
            '"agentic" (Method A), or "hook" (Method B).'
        ),
    )
    library_size_threshold: int = Field(
        default=100, ge=1,
        description=(
            "When retrieval_mode='auto': use 'agentic' if the lib has "
            "fewer skills than this at on_trial_started time, else 'hook'."
        ),
    )
    # Method-A-specific tunables (used only in agentic mode)
    agentic_search_k_rrf: int = Field(default=60, ge=1)
    agentic_search_top_k: int = Field(default=3, ge=1, le=10)
    agentic_skill_dir_name: str = Field(
        default="skillq_skills",
        description=(
            "Subdirectory name under $CLAUDE_CONFIG_DIR where Method A "
            "writes SKILL.md / _manifest.json / _search.sh. Defaults to "
            "'skillq_skills' to avoid colliding with Claude Code's default "
            "skills/ directory."
        ),
    )
    # Optional path to the user's existing CLAUDE.md on the host. If
    # set, the bridge will APPEND the skillq-method instructions to
    # this file (creating it if missing) and bind-mount the result
    # at $CLAUDE_CONFIG_DIR/CLAUDE.md in the container. If unset
    # (default), the snippet is *only* written to
    # ``<agentic_skill_dir_name>/PAPER_METHOD_INSTRUCTIONS.md`` and
    # the user must include it manually.
    user_claude_md_path: Optional[Path] = Field(
        default=None,
        description=(
            "Host path to the user's existing CLAUDE.md. If set, the "
            "bridge appends the skillq-method instructions to this file "
            "and bind-mounts the merged result at "
            "$CLAUDE_CONFIG_DIR/CLAUDE.md. Default None: do not touch "
            "the user's CLAUDE.md."
        ),
    )

    # Benchmark data location. Terminal-Bench / SWE-Bench Pro / TB Pro
    # task definitions live under this root. Replaces the old
    # hard-coded ``$SkillQ_INPUT=/home/gonern/workspace/lqrl/input``
    # (which pointed at the upstream sibling repo). Default None means
    # ``$SkillQ_INPUT`` env var, then ``./input`` (sibling of cwd).
    benchmark_input_path: Optional[Path] = Field(
        default=None,
        description=(
            "Path to the benchmark task-definition root (e.g. "
            "Terminal-Bench's ``input/`` dir). Falls back to "
            "$SkillQ_INPUT then ./input."
        ),
    )

    # Persistence
    library_root: Path = Field(default=Path("./.skillq_library"))
    state_path: Optional[Path] = None  # defaults to <library_root>/.state/method_state.json

    # Plan D: optional on-disk seed library. When the paper method
    # boots and ``library.skills`` is empty, the bridge scans this
    # directory for ``<skill>/SKILL.md`` files and pre-populates the
    # library + Q-table from them (every seed skill gets
    # ``seed_initial_q``). Default None: do nothing on first run.
    # The smoke config sets this to ``experiments/smoke/seed_skills``
    # so the 32 lqrl skills get auto-loaded without the user having
    # to hand-write ``method_state.json``.
    seed_skills_dir: Optional[Path] = Field(
        default=None,
        description=(
            "On-disk seed library path. When the paper method boots "
            "with an empty library, it walks this dir for SKILL.md "
            "files and pre-populates the library. No-op when None "
            "or when library already has skills."
        ),
    )

    def resolved_state_path(self) -> Path:
        if self.state_path is not None:
            return self.state_path
        return self.library_root / ".state" / "method_state.json"

    def resolved_benchmark_input_path(self) -> Path:
        """Resolve the benchmark task-definition root.

        Order:
        1. ``benchmark_input_path`` field (if explicitly set)
        2. ``$SkillQ_INPUT`` env var
        3. ``./input`` (sibling of cwd)

        Replaces the old hard-coded
        ``/home/gonern/workspace/lqrl/input/terminal-bench`` path
        (which pointed at the upstream sibling repo — now vendored
        inside ``./skillsvote/`` and not used as a benchmark data
        source).
        """
        if self.benchmark_input_path is not None:
            return self.benchmark_input_path
        env_val = os.environ.get("SkillQ_INPUT")
        if env_val:
            return Path(env_val)
        return Path("./input")
