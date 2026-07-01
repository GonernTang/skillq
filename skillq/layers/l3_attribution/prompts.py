"""L3 attribution + edit prompts (Step 6 of the 2026-06-26 refactor).

Inlined from ``skillq/layers/l3_attribution/prompts.py``. Own wording,
intentionally not a copy of the vendored skillsvote prompts.

- :data:`EDIT_PROMPT` (Sec. 3.4) requires the skill name to be
  unchanged and bans new dependencies / tools / files. Returns the
  *full* post-edit skill, not a diff.
- :data:`ATTRIBUTION_PROMPT` is the LLM-as-judge for the per-trial
  attribution step (5-class enum + ``knowledge_to_extract``).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# EDIT (Sec. 3.4, Layer 4)
# ---------------------------------------------------------------------------
EDIT_PROMPT = """\
You are an independent reviewer acting in *generative mode*. The skill \
below just failed a task. Propose a MINIMAL edit that would have \
prevented the failure.

Hard constraints (any violation makes the edit invalid):

  - Keep the skill's name unchanged.
  - Do not introduce new dependencies, new tools, or new files.
  - Preserve all currently-correct content; only patch the gap.
  - Return the FULL post-edit skill (the entire SKILL.md), not a diff.

Soft guidance:

  - Prefer local replacement or local insertion over rewriting.
  - Do not delete existing content only because the agent did not use it.
  - If the failure is environment-specific (network flake, missing \
    package), prefer recording the failure mode as a guard than as a \
    rewrite.
  - Update the frontmatter ``description:`` line if the skill's \
    scope meaningfully changed (so the L1 retrieval can re-rank \
    it). If the scope is unchanged, leave the description alone.

TASK
----
{task}

FAILURE DIAGNOSIS (from attribution analyzer)
---------------------------------------------
{diagnosis}

RECENT AGENT TRACE (last {tail_k} assistant messages, markdown)
----------------------------------------------------------------
{tail}

ORIGINAL SKILL
--------------
{old_skill}

POST-EDIT SKILL (full text, not a diff):"""


# ---------------------------------------------------------------------------
# ATTRIBUTION (mirrors skillsvote feedback step)
# ---------------------------------------------------------------------------
ATTRIBUTION_PROMPT = """\
You are a feedback analyzer. You will see a successful or failed task
execution trace (rendered as a markdown transcript of a Claude Code
session), a list of skill names that were *available* in the
agent's environment, and the task description. Your job is to
attribute the trial's outcome to one of six categories AND, when
the trial succeeded, extract the *reusable procedural knowledge*
the agent discovered.

## Trial outcome (GROUND TRUTH from the verifier)

r_task = {r_task}
  - 1 = the trial-level verifier confirmed the agent solved the task
  - 0 = the trial-level verifier reported the agent did NOT solve the task

## HARD CONSTRAINTS — violations make the verdict unusable

- If r_task = 1: ``overall_attribution`` MUST be one of the two
  ``success_*`` enum values. NEVER return a ``failure_*`` or
  ``fail_*`` value. Choose between:
    - ``success_skill_used``: a skill materially shaped the solution
    - ``success_no_skill_seen``: agent solved via own exploration
      without using a relevant skill (either no relevant skill
      existed, or the L1 force-use hook gave the agent nothing
      above the similarity gate)
  Note: the previous "viewed-but-not-used" enum was removed
  2026-06-26. Under the new force-use hook, the agent is told
  to MUST-call one of the listed skills, so it can no longer
  "see but not use" a relevant skill. If you observe that state
  in a trace, classify it as ``success_skill_used`` (the agent
  was effectively forced to use a relevant skill).
- If r_task = 0: ``overall_attribution`` MUST be one of the three
  ``failure_*`` / ``fail_*`` enum values. NEVER return a
  ``success_*`` value. Choose between:
    - ``failure_skill_used``: a skill was used and the trial
      still failed — the skill is at fault (wrong, incomplete,
      or stale); bridge will edit it in place
    - ``failure_skill_not_used``: no relevant skill was used —
      the library is missing a relevant skill; bridge will
      create a guard-rail skill from this failure attribution
    - ``fail_env_issue``: environment / external / network /
      package error — nothing actionable for the skill library.
      ONLY use this enum when ALL of the following hold:
        (a) The agent could not complete the task because of an
            infrastructure-level failure (container OOM, network
            timeout, missing system dependency, Docker pull
            failure, disk full), OR the verifier itself could not
            run (VerifierTimeoutError, RewardFileNotFoundError).
        (b) The failure is NOT explainable by the agent's own
            actions — the agent ran tools, read files, and wrote
            output, but the infrastructure or verifier failed
            independently.
      If the agent called a Skill(), ran tools, read/wrote files,
      and the verifier returned 0.0 because the OUTPUT was
      incorrect, this is NOT fail_env_issue — it is either
      failure_skill_used (a skill was used and the trial still
      failed) or failure_skill_not_used (no relevant skill was
      available). DO NOT classify a skill-capability gap as
      fail_env_issue.
- ``knowledge_to_extract`` MUST be non-empty when r_task = 1 (a
  reusable procedure is the whole point of this attribution step).
  When r_task = 0, also provide a non-empty knowledge string
  unless the failure was strictly env-only (``fail_env_issue``);
  Rule 5 needs a guard-rail to extract.

## Available skills

The agent had access to the following skill folders (paths relative
to the skills root). The agent MAY OR MAY NOT have actually read any
of these — you must infer from the trace whether it did.

```json
{available_skills}
```

## Evidence rules

A skill was *viewed* if and only if the trace contains a `Read`
tool call whose target path is `<skills_root>/<skill_name>/SKILL.md`
(or a file inside that skill directory).

A skill was *used* if **any** of the following holds:

- After viewing the SKILL.md, the assistant's subsequent actions
  applied content drawn from that skill — steps, caveats,
  commands, heuristics, or checklists — even partially or
  adapted to the task. The skill *materially shaped* the path;
  step-by-step adherence is NOT required.
- The PreToolUse hook force-injected the skill body into the
  agent's context (the agent called `Skill(<id>)` and the hook
  returned `allow`) AND the agent's subsequent actions did not
  visibly reject or contradict that content.

A skill is **NOT** used only when:

- The agent never called `Skill(<id>)` with this skill's id, OR
- The agent called it, but the hook denied the call (the body
  was never shown), OR
- The agent called it AND was shown the body AND visibly continued
  with wholly unrelated exploration, never applying any content
  from the skill.

**Critical success-path disambiguation.** When `r_task = 1`:

- If the agent Read/used ANY skill **present in the library**
  (i.e., it appears in `available_skills`) and the trial
  succeeded, classify it as `success_skill_used` — the library
  already covered this task, nothing to harvest.
- Reserve `success_no_skill_seen` for the case where the agent
  succeeded WITHOUT any library skill contributing — either no
  skill was above the similarity gate (the L1 force-use hook
  gave the agent nothing), or the agent used its own exploration
  without touching any skill's content.
- **Do NOT** classify as `success_no_skill_seen` just because
  the agent adapted the skill rather than following it verbatim.
  Partial/adapted use still counts as *used*.

## Attribution enum

- `success_skill_used`: the trial succeeded AND a skill materially
  shaped the successful path. No library action needed.
- `success_no_skill_seen`: the trial succeeded AND the agent did not
  use a relevant skill (either no relevant skill was available,
  or the L1 force-use hook gave it nothing above the similarity
  gate). Bridge will create a new skill from the success
  trajectory.
- `failure_skill_used`: the trial failed AND a skill was used and
  materially shaped the (failed) execution. The skill is at
  fault — wrong, incomplete, stale. Bridge will edit it in place
  via L3 EditRefiner.
- `failure_skill_not_used`: the trial failed AND no relevant
  skill was used (or no skill was available). The library is
  missing a relevant skill — bridge will create a guard-rail
  skill from this failure attribution.
- `fail_env_issue`: the trial failed because of an environment /
  external / network / package error. No library action.

## Output schema (JSON)

Return a JSON object with these fields:

- `overall_attribution`: one of the five enum values above.
- `overall_rationale`: one or two sentences explaining the
  classification.
- `subtasks`: list of subtasks, each with
    - `goal`: standalone description of the subtask
    - `summary`: factual summary of what happened
    - `attribution`: same enum
    - `skill_linked`: skill name if applicable, else null
    - `skill_refs`: list of `{{file_path, start_line, end_line,
      capability, used_for}}` (may be empty)
- `knowledge_to_extract`: a *concrete* procedural description of
  what made the trial succeed (or, for failures, what went
  wrong). MUST be non-empty when r_task = 1; the whole point of
  this step is to harvest a reusable procedure. For r_task = 0,
  also provide a non-empty string unless the failure was strictly
  env-only. DO NOT include task-specific facts, paths, or one-off
  values; only the reusable *procedure*.
- `library_gap_skill_description`: ONLY set this when
  ``overall_attribution`` is one of the two gap-signaling
  enums (``success_no_skill_seen``, ``failure_skill_not_used``).
  Describe in ONE concrete sentence what skill the library
  SHOULD have contained for this trial — include the domain
  keyword(s) that should appear in the skill description
  and any specific guard rails it should encode (e.g.,
  "a skill whose description names 'hardware-circuit-
  synthesis' or 'HDL' and includes a sanity-test checklist
  for N=0, 1, 4 plus a stop signal after 3 failed versions").
  Empty string otherwise. This field seeds the failure-path
  auto-extract step — without it the library will not learn
  from this trial.

TASK INSTRUCTION
----------------
{task}

CWD
---
{cwd}

TRIAL DIRECTORY (host)
----------------------
{trial_dir}

EXECUTION TRACE (chronological, may be truncated)
----------------------------------------------------
{trace}

JSON verdict:"""


__all__ = ["ATTRIBUTION_PROMPT", "EDIT_PROMPT"]
