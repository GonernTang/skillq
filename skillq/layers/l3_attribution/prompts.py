"""L3 attribution + edit prompts (Step 6 of the 2026-06-26 refactor).

Inlined from ``skillq/layers/l3_attribution/prompts.py``. Own wording,
intentionally not a copy of the vendored skillsvote prompts.

- :data:`EDIT_PROMPT` (Sec. 3.4) requires the skill name to be
  unchanged and bans new dependencies / tools / files. Returns the
  *full* post-edit skill, not a diff.
- :data:`ATTRIBUTION_PROMPT` is the LLM analysis prompt for the
  per-trial attribution step. The LLM outputs analysis only
  (rationale, per-subtask attribution, ``knowledge_to_extract``,
  ``library_gap_skill_description``); the top-level
  ``overall_attribution`` enum is derived in code from
  ``r_task`` + ``called_skill_ids`` (2026-07-20 refactor).
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# ATTRIBUTION (mirrors skillsvote feedback step)
# ---------------------------------------------------------------------------
ATTRIBUTION_PROMPT = """\
You are a feedback analyzer. You will see a successful or failed task
execution trace (rendered as a markdown transcript of a Claude Code
session), a list of skill names that were *available* in the
agent's environment, and the task description. Your job is to
analyze WHAT HAPPENED in the trial and extract reusable procedural
knowledge. You do NOT decide the trial's top-level success/failure
verdict — that is derived in code from the verifier's ground-truth
``r_task`` and the list of skill ids the agent actually called
(``called_skill_ids``). You only analyze the trace.

## Trial outcome (GROUND TRUTH from the verifier — for context only)

r_task = {r_task}
  - 1 = the trial-level verifier confirmed the agent solved the task
  - 0 = the trial-level verifier reported the agent did NOT solve the task

The code layer uses ``r_task`` together with ``called_skill_ids`` to
pick the top-level ``overall_attribution`` enum. You do NOT output
that field. You DO still attribute each *subtask* to one of the enum
values below, because subtask-level attribution is informational and
not derivable from the verifier reward alone.

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

## Attribution enum (used for per-subtask attribution only)

The top-level ``overall_attribution`` is NOT your output — code
derives it. You still use these enum values to attribute each
*subtask* you identify in the trace:

- `success_skill_used`: a skill materially shaped this subtask's
  successful path.
- `success_no_skill_seen`: the subtask succeeded without any
  library skill contributing (either no relevant skill was
  available, or the L1 force-use hook gave nothing above the
  similarity gate).
- `failure_skill_used`: a skill was used and materially shaped
  this subtask's (failed) execution — the skill is at fault
  (wrong, incomplete, or stale).
- `failure_skill_not_used`: this subtask failed and no relevant
  skill was used (or no skill was available) — the library is
  missing a relevant skill.
- `fail_env_issue`: this subtask failed because of an
  environment / external / network / package error. ONLY use
  this enum when the failure is infrastructure-level (container
  OOM, network timeout, missing system dependency, verifier
  could not run) AND NOT explainable by the agent's own actions.
  A skill-capability gap is NOT fail_env_issue.

## Output schema (JSON)

Return a JSON object with these fields. Do NOT include
``overall_attribution`` — it is derived in code.

- `overall_rationale`: one or two sentences analyzing what
  happened in the trial (the failure mode, or what made the
  success path work). This is your analysis of the trace, not
  a classification rationale.
- `subtasks`: list of subtasks, each with
    - `goal`: standalone description of the subtask
    - `summary`: factual summary of what happened
    - `attribution`: one of the five enum values above
      (per-subtask; the top-level enum is NOT your output)
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
- `library_gap_skill_description`: set this when the trial
  signals a missing-skill scenario — i.e. the agent succeeded
  without any library skill contributing (``success_no_skill_seen``)
  or the trial failed with no relevant skill used
  (``failure_skill_not_used``). Describe in ONE concrete sentence
  what skill the library SHOULD have contained for this trial —
  include the domain keyword(s) that should appear in the skill
  description and any specific guard rails it should encode
  (e.g., "a skill whose description names 'hardware-circuit-
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

JSON analysis:"""


__all__ = ["ATTRIBUTION_PROMPT"]
