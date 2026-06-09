"""Bridge between Harbor's trial-event stream and the four-layer method.

Two public functions:

- :func:`attach_paper_registers` — wires a single
  :class:`harbor.trial.hooks.TrialEvent.END` callback that runs the
  retrieval → β-Q → library → near-miss pipeline.
- :func:`run_paper_job` — high-level orchestrator that creates a Harbor
  :class:`Job`, attaches the hook, and runs it.

The bridge is intentionally narrow: it only handles the trial-end
event. Anything that needs to fire at trial-start can be added to the
agent subclass (:class:`mg.paper_mode.agent.PaperClaudeCodeAgent`).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

from harbor.job import Job
from harbor.models.trial.result import TrialResult
from harbor.trial.hooks import TrialHookEvent
from omegaconf import OmegaConf

from mg.method.attribution import (
    Attribution,
    AttributionAnalyzer,
    LiteLLMAttributionBackend,
)
from mg.method.editor_backend import LiteLLMEditBackend
from mg.method.extractor import SkillExtractor
from mg.method.hash import qhash
from mg.method.layered_q import BetaLayeredQ
from mg.method.library import LibManager
from mg.method.near_miss import NearMissRefiner
from mg.method.retrieval import LiteLLMEmbedder, TwoStageRanker
from mg.method.state import QlibState
from mg.method.types import Qlib, Skill
from mg.method.verifier import IndependentVerifier, LiteLLMVerifierBackend
from mg.paper_mode.config import MethodConfig

logger = logging.getLogger("mg.paper.bridge")


# ---------------------------------------------------------------------------
# Trial-level helpers
# ---------------------------------------------------------------------------
def _harbor_r_task(result: TrialResult) -> float:
    """Extract the scalar reward from a Harbor TrialResult.

    Returns ``0.0`` if the result has no verifier reward yet (e.g. the
    trial was cancelled).
    """
    if result.verifier_result is None or not result.verifier_result.rewards:
        return 0.0
    rewards = result.verifier_result.rewards
    reward = rewards.get("reward")
    if reward is None:
        if len(rewards) == 1:
            reward = next(iter(rewards.values()))
        else:
            return 0.0
    try:
        return float(reward)
    except (TypeError, ValueError):
        return 0.0


def _is_retryable_failure(event: TrialHookEvent, retry_config) -> bool:
    """Equivalent semantics to lqrl's ``_will_harbor_retry`` helper.

    We do **not** import lqrl's helper — keep the dependency surface
    minimal and the semantics easy to audit in one place.
    """
    if event.result is None or event.result.exception_info is None:
        return False
    exception_type = event.result.exception_info.exception_type
    if (
        retry_config.exclude_exceptions is not None
        and exception_type in retry_config.exclude_exceptions
    ):
        return False
    if (
        retry_config.include_exceptions is not None
        and exception_type not in retry_config.include_exceptions
    ):
        return False
    return True


def _trial_dir(event: TrialHookEvent) -> Path:
    return Path(urlparse(event.result.trial_uri).path)  # type: ignore[union-attr]


def _find_skills_dir(event: TrialHookEvent) -> Path | None:
    """Locate the directory lqrl's ``step_recommend`` copied skills into.

    lqrl sets ``$CLAUDE_CONFIG_DIR/skills`` for the Claude agent and
    ``$CODEX_HOME/skills`` for the Codex agent. We read whichever is
    present from the event's :class:`TrialHookEvent.config.agent.env`
    if available, falling back to a probe of the standard paths
    inside the trial's environment trace. Returning ``None`` is
    acceptable — the attribution step will just receive an empty
    available-skills list and classify as
    ``SUCCESS_NO_SKILL_SEEN`` if no skill is otherwise visible.
    """
    config = event.config
    if config is None:
        return None
    env = getattr(config.agent, "env", None) or {}
    for var in ("CLAUDE_CONFIG_DIR", "CODEX_HOME"):
        val = env.get(var) if isinstance(env, dict) else None
        if val:
            candidate = Path(val) / "skills"
            if candidate.exists():
                return candidate
    return None


# ---------------------------------------------------------------------------
# Public: hook registration
# ---------------------------------------------------------------------------
def attach_paper_registers(job: Job, method: MethodConfig) -> None:
    """Wire a single ``on_trial_ended`` callback that runs the
    four-layer method against each completed trial.

    The callback is wrapped in a broad ``try/except`` so a bug in the
    method does not abort the trial: Harbor's hook dispatch
    (``harbor/trial/trial.py:_emit``) is sequential, and an exception
    from one hook would prevent other hooks from running. Since paper
    mode is registered alone this is mostly a safety net for
    production.
    """
    lib = Qlib(b_max=method.b_max)
    mgr = LibManager(
        b_max=method.b_max,
        theta_admit=method.theta_admit,
        theta_evict=method.theta_evict,
        n_explore=method.n_explore,
        n_stale=method.n_stale,
    )
    q_update = BetaLayeredQ(
        alpha=method.alpha,
        beta=method.beta,
        increment_clip=method.increment_clip,
    )
    verifier = IndependentVerifier(
        backend=LiteLLMVerifierBackend(model=method.verifier_model),
        model=method.verifier_model,
    )
    refiner = NearMissRefiner(
        backend=LiteLLMEditBackend(model=method.editor_model),
        model=method.editor_model,
    )
    ranker = TwoStageRanker(
        embedder=LiteLLMEmbedder(model=method.embedder_model),
        k1=method.k1,
        k2=method.k2,
        lambda_=method.lambda_,
        c_ucb=method.c_ucb,
    )
    # Attribution (mirrors lqrl's feedback step): LLM reads session
    # trace + available skills list, returns a 6-class verdict plus a
    # knowledge_to_extract blob for the optional extract step.
    attribution_analyzer = AttributionAnalyzer(
        backend=LiteLLMAttributionBackend(model=method.attribution_model),
        model=method.attribution_model,
    )
    # Skill extractor (creates new skills): subprocess claude --print
    # writes a SKILL.md to a sandbox; we read it back and lib.add.
    # Only constructed when the user opts in.
    extractor: SkillExtractor | None = (
        SkillExtractor(
            claude_cli=method.extractor_claude_cli,
            timeout_sec=method.extract_timeout_sec,
        )
        if method.enable_auto_extract
        else None
    )
    state = QlibState(method.resolved_state_path())
    state.load_into(lib, mgr, lib_root=method.library_root)

    async def on_ended(event: TrialHookEvent) -> None:
        if event.result is None:
            return
        if event.result.exception_info is not None:
            return
        if _is_retryable_failure(event, job.config.retry):
            logger.debug(
                "Skipping paper method for retryable failed trial %s",
                event.trial_id,
            )
            return

        try:
            r_task = _harbor_r_task(event.result)
            intent_text = event.task_name or _trial_dir(event).name
            intent_hash = qhash(intent_text)
            trial_dir = _trial_dir(event)

            # Retrieval (Phase A + Phase B)
            retrieved = ranker.retrieve_for_intent(
                query=intent_text,
                lib=lib,
                intent_hash=intent_hash,
                q_for=mgr.q_for,
            )

            # Attribution step: 1 LLM call, reads session jsonl +
            # available-skills list, returns 6-class verdict +
            # knowledge_to_extract.
            attribution = attribution_analyzer.analyze(
                task=intent_text,
                trial_dir=trial_dir,
                skills_root=_find_skills_dir(event),
            )

            # Compute a single r_learning for the top retrieved skill.
            # When the library is empty, the learning signal is zero.
            r_learning = 0.0
            if retrieved:
                top_skill = retrieved[0].skill
                if lib.get(top_skill.skill_id) is not None:
                    verdict = verifier.score(intent_text, top_skill, top_skill)
                    r_learning = verdict.r_learning

            # Q-update for every retrieved skill
            for r in retrieved:
                q_old = mgr.q_for(intent_hash, r.skill.skill_id)
                q_new = q_update.apply(q_old, r_task, r_learning)
                mgr.update_q(intent_hash, r.skill.skill_id, q_new - q_old)
                mgr.mark_retrieved(r.skill.skill_id, state.step + 1)
                r.skill.n_uses += 1
                if r_task > 0.5:
                    r.skill.n_success += 1

            # Optional: small Q-bump for the "viewed but not used"
            # case. The agent glanced at the skill but solved the
            # task from its own exploration; we acknowledge the
            # exposure with a small reward so the skill doesn't
            # drift to extreme-negative Q from being repeatedly
            # passed over.
            if (
                attribution.overall_attribution
                == Attribution.SUCCESS_VIEWED_SKILL_BUT_NOT_USED
                and r_task > 0.5
            ):
                for st in attribution.subtasks:
                    if st.skill_linked and st.skill_linked in lib:
                        mgr.update_q(
                            intent_hash,
                            st.skill_linked,
                            0.05,  # small positive bump
                        )

            # Optional: auto-extract (create_skill path)
            extracted_skills: list[Skill] = []
            if (
                extractor is not None
                and r_task > 0.5
                and attribution.overall_attribution
                in (
                    Attribution.SUCCESS_VIEWED_SKILL_BUT_NOT_USED,
                    Attribution.SUCCESS_NO_SKILL_SEEN,
                )
                and not any(
                    mgr.q_for(intent_hash, r.skill.skill_id)
                    > method.theta_consider_used
                    for r in retrieved
                )
                and attribution.knowledge_to_extract.strip()
                and len(extracted_skills) < method.extract_max_new_per_trial
            ):
                new_skill = await extractor.extract(
                    task=intent_text,
                    knowledge=attribution.knowledge_to_extract,
                    intent_hash=intent_hash,
                    available_skill_names=[s.skill_id for s in lib.skills.values()],
                )
                if new_skill is not None and new_skill.skill_id not in lib:
                    lib.add(new_skill)
                    # Reset probation for the new skill so it goes
                    # through the full n_explore window.
                    mgr.probation_count.pop(new_skill.skill_id, None)
                    mgr.probation_avg_q.pop(new_skill.skill_id, None)
                    # Initial Q-value for the new skill on the
                    # current intent. MethodConfig defaults to 0.5
                    # (an "optimistic prior" — gives the new skill
                    # a fair chance at the z-score Phase B ranking).
                    mgr.update_q(
                        intent_hash,
                        new_skill.skill_id,
                        method.new_skill_initial_q,
                    )
                    extracted_skills.append(new_skill)
                    logger.info(
                        "Extracted new skill %s (Q_init=%.2f) for intent %s",
                        new_skill.skill_id,
                        method.new_skill_initial_q,
                        intent_text,
                    )

            # Library maintenance (admission / eviction / rejuvenation)
            mgr.maintain(lib, current_step=state.step + 1)
            state.step += 1
            state.save(lib, mgr, lib_root=method.library_root)

            # Near-miss refine (Layer 4) — only on failures
            if r_task == 0.0 and retrieved:
                top = retrieved[0]
                current_skill = lib.get(top.skill.skill_id)
                if current_skill is not None:
                    current_q = mgr.q_for(intent_hash, current_skill.skill_id)
                    if refiner.is_near_miss(
                        r_task, current_q, method.theta_near_miss
                    ):
                        new_skill = refiner.propose_edit(
                            skill=current_skill,
                            task=intent_text,
                            failure_trace=str(trial_dir),
                        )
                        if new_skill is not current_skill:
                            lib.replace(new_skill)
                            logger.info(
                                "Near-miss refined skill %s for intent %s",
                                new_skill.skill_id,
                                intent_text,
                            )
        except Exception:
            # Never let a method bug abort the trial.
            logger.exception(
                "Paper method on_ended failed for trial %s; swallowed.",
                event.trial_id,
            )

    job.on_trial_ended(on_ended)


# ---------------------------------------------------------------------------
# Public: high-level entry
# ---------------------------------------------------------------------------
async def run_paper_job(job_config_path: Path, method: MethodConfig) -> int:
    """Create a Harbor Job, attach the paper hook, and run it."""
    from harbor import Job
    from harbor.cli.utils import run_async  # type: ignore[attr-defined]
    from harbor.environments.factory import EnvironmentFactory
    from harbor.models.job.config import JobConfig

    cfg = OmegaConf.load(str(job_config_path))
    cfg_container = OmegaConf.to_container(cfg, resolve=True)
    if not isinstance(cfg_container, dict):
        raise TypeError("Job config must be a mapping.")
    job_cfg = JobConfig.model_validate(cfg_container)

    EnvironmentFactory.run_preflight(
        type=job_cfg.environment.type,
        import_path=job_cfg.environment.import_path,
    )

    job = await Job.create(job_cfg)
    attach_paper_registers(job, method)
    result = await job.run()

    # Final state save
    logger.info(
        "Paper method finished: %s trials, %s successes",
        getattr(result, "n_trials", "?"),
        getattr(result, "n_succeeded", "?"),
    )
    return 0


def run_paper_job_sync(job_config_path: Path, method: MethodConfig) -> int:
    """Synchronous wrapper around :func:`run_paper_job`."""
    return asyncio.run(run_paper_job(job_config_path, method))
