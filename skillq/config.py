"""Pydantic configuration for the SkillQ paper method.

Step 7 (2026-06-27) of the 4-layer refactor lifted this module from
the legacy ``skillq.config`` location to its new canonical
home at ``skillq.config``. The class identity (name + module
attributes) is unchanged — every existing import of
``MethodConfig`` must now use ``from skillq.config import MethodConfig``.

Step 8 (2026-06-27) added nested-input support: the merged job+method
YAMLs in ``experiments/configs/`` use ``retrieval:`` and ``evolve:``
subtrees; a ``model_validator(mode="before")`` unpacks those into
the flat fields below. Internal call sites continue to read
``method.hook_top_k`` etc. (no migration needed).

Fields map 1:1 to the symbols in the SkillQ paper (Sec. 3.1-3.4).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# Step 8 (2026-06-27) nested-format → flat-field unpack map.
# The merged YAMLs in experiments/configs/ nest Layer-1 tunables
# under ``retrieval:`` and Layer-4 tunables under ``evolve:`` for
# readability; the internal code (and the in-container hook, which
# reads SKILLQ_HOOK_* env vars written from the flat fields)
# continues to use the flat hook_* / sim_gate_* / evolve_* names.
#
# Adding a new field here: if it lives under ``retrieval:`` in the
# merged YAML, add the key to RETRIEVAL_UNPACK; if it lives under
# ``evolve:``, add to EVOLVE_UNPACK. Otherwise it stays a
# top-level flat field and no entry is needed.
RETRIEVAL_UNPACK: dict[str, str] = {
    "top_k": "hook_top_k",
    "score_mode": "hook_score_mode",
    "beta": "hook_multiplicative_beta",
    "gamma": "hook_multiplicative_gamma",
    "c_ucb": "hook_c_ucb",
    "lambda": "hook_lambda",
    "sim_gate_min_score": "sim_gate_min_score",
    "sim_gate_floor": "sim_gate_floor",
    "pull_top_k": "hook_pull_top_k",
}
EVOLVE_UNPACK: dict[str, str] = {
    "enabled": "enable_auto_extract",
    "extract_every_n_trials": "extract_every_n_trials",
    "enforce_failure_skill_structure": "enforce_failure_skill_structure",
}


def _unpack_nested(data: Any) -> Any:
    """Unpack ``retrieval:`` / ``evolve:`` subtrees into flat fields.

    Step 8: the merged job+method YAMLs use nested subtrees. This
    shim makes the flat MethodConfig fields the source of truth
    while accepting the nested input. Returns the (possibly
    mutated) input dict. No-op for already-flat inputs and for
    non-dict inputs (e.g. programmatic construction).
    """
    if not isinstance(data, dict):
        return data
    retrieval = data.pop("retrieval", None)
    if isinstance(retrieval, dict):
        for k, v in retrieval.items():
            flat_key = RETRIEVAL_UNPACK.get(k, k)
            # Don't clobber a top-level explicit value.
            data.setdefault(flat_key, v)
    evolve = data.pop("evolve", None)
    if isinstance(evolve, dict):
        for k, v in evolve.items():
            flat_key = EVOLVE_UNPACK.get(k, k)
            data.setdefault(flat_key, v)
    return data


class MethodConfig(BaseModel):
    """Hyperparameters and runtime paths for the four-layer method."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _accept_nested_format(cls, data: Any) -> Any:
        """Accept the Step 8 nested ``retrieval:`` / ``evolve:`` format.

        See :data:`RETRIEVAL_UNPACK` / :data:`EVOLVE_UNPACK` for the
        field rename tables. Pydantic applies this validator
        BEFORE the field-level validators and ``extra="forbid"``,
        so any unrecognised top-level keys still error out — only
        the ``retrieval:`` / ``evolve:`` wrappers are unpacked.
        """
        return _unpack_nested(data)

    # 2026-06-25: removed ``alpha`` / ``beta`` / ``increment_clip`` —
    # those were the Eq. 6 ``BetaLayeredQ`` knobs. The runtime uses
    # plain Eq. 5 with cosine-weighted delta (``q_alpha`` below).
    # See CHANGELOG "Dead-code purge" entry.

    # Bug 5: optional bilateral clip on Q-values applied inside
    # ``LibManager.update_q`` / ``set_q``. Default (None, None) =
    # no clip = existing behaviour preserved. Set
    # ``q_clip_floor=0.0`` to forbid negative Q; set
    # ``q_clip_ceiling=1.0`` to forbid Q > 1.0. Mirrors the reference
    # design's ``q_floor`` knob but bilateral.
    q_clip_floor: Optional[float] = Field(
        default=None,
        description=(
            "Optional lower bound for Q-values. update_q / set_q "
            "clip Q to >= this value. Default None: no lower bound."
        ),
    )
    q_clip_ceiling: Optional[float] = Field(
        default=None,
        description=(
            "Optional upper bound for Q-values. update_q / set_q "
            "clip Q to <= this value. Default None: no upper bound."
        ),
    )

    # === Layer 4 extraction quality gates (2026-06-25) ===
    enforce_failure_skill_structure: bool = Field(
        default=True,
        description=(
            "When True (default), ``_collect_skill`` rejects "
            "failure-prompt skills whose body does not contain "
            "both 'Diagnostic checklist' and 'Stop signal' "
            "sections (BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT "
            "requirement). The prompt claims 'will be rejected by "
            "the bridge' — this flag is the enforcement. Set to "
            "False to accept any body within the token-count guard."
        ),
    )

    # Two-stage retrieval (Layer 1, Eq. 4)
    lambda_: float = Field(default=0.5, ge=0.0, le=1.0)
    c_ucb: float = Field(default=0.5, ge=0.0)
    k1: int = Field(default=10, ge=1)
    k2: int = Field(default=3, ge=1)

    # Library management (Layer 3)
    # b_max=1000 default — raised from 50 on 2026-06-23 after the TB2 full
    # run hit 100/100 and started evicting on every auto_extract insertion.
    # Smoke YAMLs that need a lower cap already pin b_max explicitly.
    b_max: int = Field(default=1000, ge=1)

    # LLM models
    # editor_model default is env-driven (ANTHROPIC_MODEL →
    # anthropic/<model>) so hosts without OPENAI_API_KEY don't
    # silently hit the InternalServerError that the bridge swallows
    # (was: editor_model="openai/gpt-4o" — bit us on the 2026-06-25
    # full run because every trial's Layer 3 edit + Layer 4 extract
    # failed). See Task #10 in SKILLQ_RUN_RESULTS_2026-06-25.md.
    editor_model: str = Field(
        default_factory=lambda: (
            f"anthropic/{os.environ.get('ANTHROPIC_MODEL', 'deepseek-v4-flash')}"
        ),
        description=(
            "Layer 3 (Edit) LLM. Default reads $ANTHROPIC_MODEL and "
            "wraps with anthropic/ prefix for litellm."
        ),
    )
    # Same env-driven default for attribution (Layer 2).
    attribution_model: str = Field(
        default_factory=lambda: (
            f"anthropic/{os.environ.get('ANTHROPIC_MODEL', 'deepseek-v4-flash')}"
        ),
        description=(
            "Layer 2 (Attribution) LLM. Default reads $ANTHROPIC_MODEL."
        ),
    )
    embedder_model: str = "openai/text-embedding-3-small"
    embedder_dim: int = 1536
    extractor_claude_cli: str = "claude"  # the CLI binary invoked for extract
    extractor_model: str = Field(
        default="",
        description=(
            "Layer 4 (Extract) LLM model identifier passed as --model to "
            "the claude CLI extract subprocess. When empty, falls back to "
            "attribution_model via the _fill_extractor_model_default "
            "validator."
        ),
    )

    @model_validator(mode="after")
    def _fill_extractor_model_default(self) -> "MethodConfig":
        """Fill extractor_model from attribution_model when empty.

        SkillExtractor historically had no model= param (gap 5/5),
        defaulting to the host's claude CLI default. This ensures
        L4 extract uses the same model as L3 attribution by default,
        while allowing independent tuning when extractor_model is set.
        """
        if not self.extractor_model:
            object.__setattr__(self, "extractor_model", self.attribution_model)
        return self

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
    # === Feature flag (Step 4 refactor) ===
    # Step 7 (2026-06-27) removed the legacy closure-based bridge —
    # the ``"legacy"`` value now raises a friendly migration error
    # from :func:`skillq.runtime.bridge.attach_legacy_registers`.
    # The field is kept for backwards-compat (old YAMLs with
    # ``runtime: legacy`` still parse) but the only safe value is
    # ``"new"`` (the default). Will be removed in v1.5.
    runtime: Literal["new", "legacy"] = Field(
        default="new",
        description=(
            "Pipeline selector. Step 7 (2026-06-27) removed the "
            "``'legacy'`` closure-based bridge; setting "
            "``runtime='legacy'`` raises a migration error at job "
            "start. The only supported value is ``'new'`` (default), "
            "which dispatches to the closure-free 8-step pipeline "
            "at ``skillq.runtime.bridge.attach_layered_registers``."
        ),
    )
    # Pull-mode (Layer 1, on top of hook-mode): registers a Claude Code
    # SessionStart hook in addition to the PreToolUse hook. The
    # SessionStart handler embeds the user's task, runs the same
    # Eq.4 scoring as the PreToolUse branch, and emits a
    # `hookSpecificOutput.additionalContext` block listing the top-K
    # skills available. Enabled when retrieval_mode == "pull".
    # See skillq/runtime/hook.py _handle_session_start for details.
    hook_pull_top_k: int = Field(default=3, ge=1, le=10)

    # === Scoring mode (2026-06-24) ===
    # Two retrieval formulas, switchable at config time:
    #
    # - "additive" (legacy Eq.4): score = (1-λ)·sim_z + λ·q_z + c_ucb·√(log N/(n+1))
    #   where sim_z / q_z are z-scored within each batch. After z-scoring,
    #   a low-sim skill can still rank high if its Q is above mean, so
    #   irrelevant skills occasionally reach Top-K.
    #
    # - "multiplicative" (new, Fix 2): score = sim·(1 + β·Q_norm) + γ·UCB
    #   using RAW (non-z-scored) cosine. Critical property: when sim=0
    #   the entire sim term vanishes and the skill can only rank by
    #   its UCB exploration bonus — Q cannot promote an irrelevant
    #   skill. β=0.5, γ=0.2 are conservative defaults (Q amplification
    #   is modest, UCB is small noise). See plan:
    #   ~/.claude/plans/bug-3-per-trial-q-table-json-hashed-quilt.md
    hook_score_mode: str = Field(
        default="multiplicative",
        description=(
            'Retrieval scoring formula: "additive" (Eq.4 with z-scored '
            'sim + z-scored Q + UCB) or "multiplicative" (sim·(1+β·Q) '
            '+ γ·UCB; sim=0 ⇒ score=γ·UCB only). 2026-06-24: switched '
            'default to "multiplicative" to fix Top-K recommending '
            'irrelevant skills on ML tasks.'
        ),
    )
    hook_multiplicative_beta: float = Field(
        default=0.5, ge=0.0, le=5.0,
        description=(
            "Multiplicative-mode Q amplification factor. The score "
            "term is sim·(1 + β·Q_norm). β=0 means Q has no effect; "
            "β=1 means Q doubles the base sim. Default 0.5 is "
            "conservative — Q amplifies by up to 50%%."
        ),
    )
    hook_multiplicative_gamma: float = Field(
        default=0.2, ge=0.0, le=5.0,
        description=(
            "Multiplicative-mode UCB weight. The score term is "
            "sim·(1 + β·Q) + γ·UCB. Default 0.2 — UCB is a small "
            "exploration bonus that doesn't dominate relevance ranking."
        ),
    )
    # 2026-06-29 (Phase 10 Bug 1): hook_q_clip_min and hook_q_clip_max
    # removed. The multiplicative formula now hard-codes Q clamp to
    # [0, 1] as a numerical guard. Pydantic's extra="forbid" will
    # reject any YAML / programmatic input still carrying these
    # fields (which is the desired fail-fast).

    # === Hard Gate (2026-06-24, Fix 1) ===
    # Drop candidates with raw cosine similarity below ``sim_gate_min_score``
    # BEFORE scoring. Hard cap — irrelevant skills cannot reach Top-K
    # even with high UCB. ``sim_gate_floor`` keeps a minimum number
    # of candidates by descending sim when the gate would otherwise
    # leave the list empty (so early trials with little embedding
    # coverage still get a Top-K to choose from).
    #
    # Default 0.0 = gate disabled. Production runs should opt in via
    # the method YAML (e.g. 0.30 for typical text-embedding-v4 with
    # semantic similarity in the [0.2, 0.8] range). With the default
    # off, the multiplicative scoring formula (Fix 2) still provides
    # soft gating: skills with sim=0 can only rank by their UCB term,
    # so they only appear when truly nothing else is relevant.
    sim_gate_min_score: float = Field(
        default=0.7, ge=0.0, le=1.0,
        description=(
            "Hard Gate: minimum raw cosine similarity to enter the "
            "scoring pool. Candidates with sim < this are dropped "
            "before any z-scoring / additive or multiplicative "
            "formula. Default 0.7 = moderate gate. Set 0.0 to disable "
            "(the multiplicative formula's inherent sim=0 → γ·UCB "
            "behavior still applies). Set 0.99 to effectively keep "
            "only the top-1 by raw sim."
        ),
    )
    sim_gate_floor: int = Field(
        default=0, ge=0,
        description=(
            "Hard Gate: minimum number of candidates to retain when "
            "the gate is active. If the gate would leave fewer than "
            "this many, keep this many by descending raw sim "
            "regardless of the threshold. "
            "Default 0 (2026-06-25, strict mode) = if every candidate "
            "is below sim_gate_min_score, return empty top-k; the hook "
            "emits a 'no relevant skills' deny and the agent is "
            "expected to solve directly without invoking Skill(). "
            "This strictly prevents irrelevant skills from "
            "(a) polluting the agent's context (no 'maybe try one of "
            "these?') and (b) polluting Q-table evolution (no spurious "
            "n_retrievals++ for skills that should never have been "
            "retrieved). "
            "Set 1+ for the legacy 'always keep a fallback candidate' "
            "behavior, useful for very-early trials with poor embedding "
            "coverage where the agent benefits from a 'best of a bad "
            "lot' Top-K to choose from."
        ),
    )

    # === Q-value update (task-level reward only, 2026-06-23) ===
    # Simplified from Eq.6 (per-subtask blend) to standard Eq.5.
    # The pre-2026-06-23 path used an LLM judge to score each Skill()
    # call as r_subtask ∈ {0, 1}, then blended
    #     target = w_subtask * r_subtask_mean + w_task * r_task
    # but with the pull-mode Top-K injection (one skill called per
    # trial), r_subtask collapsed to a binary that was almost always
    # identical to r_task, and the judge call was wasted compute.
    #
    # Q-update is now::
    #
    #     Q(skill) += alpha * (r_task - Q(skill))
    #
    # with ``r_task`` ∈ {0, 1} (binarized trial-level verifier
    # reward). All skills called in the trial share the same r_task.
    q_alpha: float = Field(default=0.3, ge=0.0, le=1.0)

    # === Cosine-weighted Q-update (2026-06-24, Fix 3) ===
    # When enabled, multiply each per-skill Q-update delta by
    # max(cos(φ(q), φ(s)), 0), where:
    #   φ(q) = embedding of calls_log[0].intent_text (re-computed
    #          once per trial; ~50ms via the host embed daemon)
    #   φ(s) = embedding of the skill's description (already in
    #          emb_cache from Layer 1 retrieval)
    # Effect: a skill that is semantically irrelevant to the trial
    # (cos < 0) gets delta clamped to 0 — its Q is NOT polluted by
    # the trial's failure. Relevant skills (cos ≈ 1) get the full
    # Eq.5 delta. Fix 3 is the Q-update-side counterpart to Fix 2's
    # retrieval-side guard.
    q_update_cosine_weight: bool = Field(
        default=True,
        description=(
            "When True, multiply each per-skill Q-update delta by "
            "max(cos(φ(q), φ(s)), 0). Default True (2026-06-24). "
            "Set False for ablation / to fall back to plain Eq.5."
        ),
    )

    # === Fresh-start toggles (2026-06-25) ===
    # By default, every on_trial_started reloads ``method_state.json``
    # (Q-table + library) and ``emb_cache.json`` from disk so the
    # method resumes across runs. Set either flag to ``False`` to
    # force fresh-start semantics for that artifact on this run.
    #
    # - ``reuse_q_table=False`` → ``mgr.q_table`` starts empty (any
    #   skills loaded from state or ``seed_skills_dir`` get Q
    #   ``seed_initial_q``); the on-disk Q-table is overwritten
    #   with the cleared state at end-of-trial.
    # - ``reuse_embedding_cache=False`` → ``emb_cache`` starts empty
    #   (Plan D pre-embed re-derives every skill's description
    #   embedding); the on-disk cache is overwritten.
    #
    # The two flags are independent: keep learned Q values while
    # regenerating embeddings (e.g. after switching ``embedder_model``),
    # or vice versa.
    #
    # Note (2026-06-30): To share emb_cache across runs that use
    # different ``library_root``s (e.g. timestamped output dirs),
    # set ``emb_cache_path`` explicitly instead of relying on the
    # sibling-of-state_path default. Per the fresh-start semantics
    # review, ``reuse_embedding_cache`` does NOT need to flip to
    # ``False`` for fresh-start — emb_cache entries are content-
    # derived and invariant across runs as long as the embedder
    # model and skill bodies are stable.
    reuse_q_table: bool = Field(
        default=True,
        description=(
            "If True (default), load ``method_state.json`` from disk "
            "and resume the Q-table + library. If False, start with "
            "an empty Q-table (skills get ``seed_initial_q``) and "
            "overwrite the state file at end-of-trial."
        ),
    )
    reuse_embedding_cache: bool = Field(
        default=True,
        description=(
            "If True (default), load ``emb_cache.json`` from disk and "
            "reuse the cached description embeddings. If False, "
            "start with an empty emb_cache (Plan D pre-embed "
            "re-derives every skill) and overwrite the cache at "
            "end-of-trial. Prefer leaving this True across runs; "
            "set False only when forcing a rebuild (e.g. embedder "
            "model swap)."
        ),
    )

    # === Verifier uv cache (2026-06-24) ===
    # Path to a host-side uv cache directory that is bind-mounted
    # into the agent container at /root/.cache/uv (read-only).
    # The cache should be pre-populated with the wheels needed by
    # slow task verifiers (e.g. torch for pytorch tasks) so each
    # trial's ``uvx -w torch==2.7.1`` skips the cold ~200 MB
    # download. Default None: no cache mounted, verifier runs as
    # before (cold-downloads every trial).
    #
    # Prime once via:
    #   uv run python -m skillq.runtime.cli prime-uv-cache \
    #       --cache-path /home/gonern/.skillq_cache/uv \
    #       --python-version 3.13 \
    #       --wheels torch==2.7.1 pytest==8.4.1 pytest-json-ctrf==0.3.5
    #
    # The cache must contain wheels tagged for the Python version
    # the container's test.sh uses (3.13 for pytorch tasks). The
    # priming command uses ``uv pip download --python-version 3.13
    # --only-binary=:all:`` to fetch platform-correct wheels
    # without needing Python 3.13 installed on the host.
    verifier_uv_cache_path: Optional[Path] = Field(
        default=None,
        description=(
            "Host path to a pre-populated uv cache directory "
            "(wheels-v0/ subdir). Bind-mounted RO into the agent "
            "container at /root/.cache/uv. Default None: no mount, "
            "verifier cold-downloads every trial."
        ),
    )

    # Auto-extract (create_skill path) — opt-in, see bridge.py
    enable_auto_extract: bool = False
    extract_every_n_trials: int = Field(
        default=4, ge=1,
        description=(
            "Batched-evolve flush cadence. Every N qualifying trials "
            "(those whose attribution ∈ {SUCCESS_NO_SKILL_SEEN, "
            "FAILURE_SKILL_NOT_USED}), spawn ONE claude --print "
            "subprocess that aggregates the N (task, knowledge) records "
            "into a single new SKILL.md. Default 4 mirrors SkillsVote's "
            "evolve_every_n_trials=1 default offset by the extra LLM "
            "call cost in the paper's per-trial attribution step. "
            "(2026-06-26: SUCCESS_VIEWED_SKILL_BUT_NOT_USED removed — "
            "structurally unreachable under L1 force-use. "
            "FAILURE_SKILL_USED is no longer in the extract trigger set; "
            "the failure-path create trigger is now FAILURE_SKILL_NOT_USED "
            "only.)"
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
    # Method B ("pull") — paper-intent default (2026-07-01):
    # SessionStart / UserPromptSubmit injects Top-K skills into the
    # agent context. The agent is **required** to invoke at least
    # one of the presented skills (all passed the sim Hard Gate, so
    # every presented skill is task-relevant). Only skills the agent
    # actually invokes get Q-update / attribution / L3 edit / L4
    # create — skills that are merely presented but not invoked get
    # only ``n_retrievals++`` for UCB exploration credit.
    # "auto" picks agentic when ``len(lib) < library_size_threshold``,
    # else pull. Decided at on_trial_started time.
    retrieval_mode: str = Field(
        default="pull",
        description=(
            'Retrieval mode: "pull" (Method B + UserPromptSubmit inject '
            'of Top-K skills, default since 2026-07-01 — paper-intent '
            'behaviour, agent sees candidates proactively) '
            'or "hook" (PreToolUse only — agent-driven, no proactive '
            'push; historically the default). '
            'Historical "auto" / "agentic" values are still accepted '
            'for back-compat but treated as "hook".'
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
    emb_cache_path: Optional[Path] = None
    # defaults to sibling of state_path (``<library_root>/.state/emb_cache.json``).
    # Override to a stable, host-side path (e.g. a sibling of
    # ``seed_skills_dir``) to share emb_cache across runs that use
    # different ``library_root``s (typical for timestamped run dirs).
    # Plan D pre-embed will read whatever sits at the resolved path
    # on the next trial and only re-embed skills whose
    # ``skill_id`` is missing from it. See 2026-06-30 review.

    # Plan D: optional on-disk seed library. When the paper method
    # boots and ``library.skills`` is empty, the bridge scans this
    # directory for ``<skill>/SKILL.md`` files and pre-populates the
    # library + Q-table from them (every seed skill gets
    # ``seed_initial_q``). Default None: do nothing on first run.
    # The smoke configs set this to
    # ``/home/gonern/workspace/skillq/skills`` so the curated skills
    # get auto-loaded on first boot AND so any newly auto-extracted
    # skill can be mirrored back to this same dir (see
    # ``skillq.shared.mirror.mirror_skill_to_host_dir``),
    # making it visible to subsequent trials via the existing
    # bind-mount at /skills.
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
        """Resolve the ``method_state.json`` path.

        Order:
        1. ``state_path`` field (if explicitly set)
        2. ``<library_root>/.state/method_state.json`` (legacy default)

        For Plan D co-location with the curated skills, set
        ``state_path`` explicitly in YAML::

            state_path: <seed_skills_dir>/.skillq_state/method_state.json
        """
        if self.state_path is not None:
            return self.state_path
        return self.library_root / ".state" / "method_state.json"

    def resolved_emb_cache_path(self) -> Path:
        """Resolve the ``emb_cache.json`` path.

        Order:
        1. ``emb_cache_path`` field (if explicitly set — typical
           when the user wants a stable, cross-run cache location
           shared across timestamped ``library_root``s)
        2. ``<state_path>.parent / emb_cache.json`` (legacy default;
           i.e. same parent dir as ``method_state.json``)

        Setting ``emb_cache_path`` lets ``Q-table`` stay per-run
        (under a timestamped ``library_root``) while ``emb_cache``
        lives at a stable location — the two have different
        freshness semantics (see ``fresh-start-q-table-only``
        memory).
        """
        if self.emb_cache_path is not None:
            return self.emb_cache_path
        return self.resolved_state_path().parent / "emb_cache.json"

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
