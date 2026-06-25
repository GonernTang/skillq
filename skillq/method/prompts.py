"""mg-side prompts for the SkillQ paper method.

These are intentionally **not** copies of the prompts in
``skillsvote/src/skills_vote/{feedback,evolve,recommend}/prompt.py``. The
naming, rubric, JSON schema, and constraints all differ:

- **VERIFIER_PROMPT** uses four axes (clarity / completeness /
  non_redundancy / correctness) with a fixed-weight mean, and a
  compact JSON output ``{old_score, new_score, improved, rationale}``.
  The :class:`paper.method.verifier.IndependentVerifier` is *information
  isolated*: it sees (task, old_skill, new_skill) only.
- **EDIT_PROMPT** (Sec. 3.4) requires the skill name to be unchanged
  and bans new dependencies / tools / files. Returns the *full*
  post-edit skill, not a diff.
- **ATTRIBUTION_PROMPT** is the LLM-as-judge for the per-trial
  attribution step (six-class enum + ``knowledge_to_extract``).
- **BATCHED_EXTRACT_SKILL_PROMPT** is the system prompt for the
  batched-evolve ``claude --print`` subprocess. It aggregates N
  successful (task, knowledge) records into a single new SKILL.md.
- **BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT** is the symmetric
  version for the Rule 5 path (failure + no useful skill → new
  skill). Aggregates N failure-attribution records into a single
  guard-rail SKILL.md.
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# VERIFIER (Sec. 3.2)
# ---------------------------------------------------------------------------
VERIFIER_PROMPT = """\
You are an **informationally isolated** content reviewer. You do NOT see \
the agent's prompt, its generation trace, or any other skill in the \
library — only the two versions of *one* skill and the task it was \
applied to. Treat the two skill texts as the only signal you have.

Score each version along four axes, each in the closed interval [0, 1]:

  - **clarity**         (0.3 weight) — is the language unambiguous, \
                          well-structured, and free of vague hand-waving?
  - **completeness**    (0.3 weight) — does it cover the cases and \
                          sub-steps needed to actually apply the skill?
  - **non_redundancy**  (0.2 weight) — does it avoid restating the same \
                          idea in different words?
  - **correctness**     (0.2 weight) — are the claims, APIs, and \
                          commands factually correct given the task?

Compute the per-version score as the weighted mean of the four axes.

Return a JSON object with these fields (and nothing else):

  - ``old_score``: float in [0, 1], the pre-task version's weighted mean.
  - ``new_score``: float in [0, 1], the post-task version's weighted mean.
  - ``improved``: bool, true iff ``new_score - old_score > 0.1``. Use the \
                  0.1 threshold; tiny drifts do not count.
  - ``rationale``: one sentence. If ``improved`` is true, name the \
                   single biggest delta. If false, name the single \
                   biggest gap.

TASK
----
{task}

PRE-TASK SKILL (verbatim)
-------------------------
{old_skill}

POST-TASK SKILL (verbatim)
--------------------------
{new_skill}

Your JSON (no prose outside the object):"""


# ---------------------------------------------------------------------------
# EDIT (Sec. 3.4, Layer 4)
# ---------------------------------------------------------------------------
EDIT_PROMPT = """\
You are an independent reviewer acting in *generative mode*. The skill \
below just failed a task. Propose a MINIMAL edit that would have \
prevented the failure.

Hard constraints (any violation makes the edit invalid):

  - Touch at most 20% of the original token count.
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

TASK
----
{task}

FAILURE TRACE (excerpt)
-----------------------
{trace}

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

- If r_task = 1: ``overall_attribution`` MUST be one of the three
  ``success_*`` enum values. NEVER return a ``fail_*`` value.
  Choose between:
    - ``success_skill_used``: a skill materially shaped the solution
    - ``success_viewed_skill_but_not_used``: agent viewed skills but
      solved via own exploration
    - ``success_no_skill_seen``: agent solved via own exploration
      without even viewing any relevant skill
- If r_task = 0: ``overall_attribution`` MUST be one of the three
  ``fail_*`` enum values. NEVER return a ``success_*`` value.
  Choose between:
    - ``fail_skill_issue``: a skill the agent relied on was wrong
    - ``fail_agent_issue``: agent reasoning / action error
    - ``fail_env_issue``: environment / external / network error
- ``knowledge_to_extract`` MUST be non-empty when r_task = 1 (a
  reusable procedure is the whole point of this attribution step).
  When r_task = 0, also provide a non-empty knowledge string
  unless the failure was strictly env-only (``fail_env_issue``);
  Rule 5 needs a guard-rail to extract.

## Available skills

The agent had access to the following skill folders (paths relative
to the skills root). The agent MAY or MAY NOT have actually read any
of these — you must infer from the trace whether it did.

```json
{available_skills}
```

## Evidence rules

A skill was *viewed* if and only if the trace contains a `Read`
tool call whose target path is `<skills_root>/<skill_name>/SKILL.md`
(or a file inside that skill directory).

A skill was *used* if the assistant's behaviour after viewing it
matched the procedure documented in that skill (i.e., the agent
followed the skill's workflow, not its own exploration).

## Attribution enum

- `success_skill_used`: the trial succeeded AND a skill materially
  shaped the successful path.
- `success_viewed_skill_but_not_used`: the trial succeeded AND the
  agent viewed one or more skills, but those skills did not
  materially shape the successful path. The agent reached the
  solution through its own exploration.
- `success_no_skill_seen`: the trial succeeded AND the agent did not
  view any of the available skills (or no relevant skill was
  available at all).
- `fail_skill_issue`: the trial failed because a skill that the
  agent relied on was wrong, incomplete, or missing.
- `fail_agent_issue`: the trial failed because of an agent
  reasoning / action error.
- `fail_env_issue`: the trial failed because of an environment /
  external / network / package error.

## Output schema (JSON)

Return a JSON object with these fields:

- `overall_attribution`: one of the six enum values above.
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
  ``overall_attribution`` is one of the three gap-signaling
  enums (``success_no_skill_seen``,
  ``success_viewed_skill_but_not_used``, ``fail_agent_issue``).
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


# ---------------------------------------------------------------------------
# BATCHED_EXTRACT_SKILL (Layer 4.5 / "create" path, batched N trials)
# ---------------------------------------------------------------------------
# Mirrors SkillsVote's evolve/_CREATE_SYSTEM_PROMPT shape (aggregate
# reusable exploration across N trials → decide create or skip → write
# SKILL.md) but in skillq-method wording. The aggregate is what gives
# the LLM enough signal to converge on a *reusable procedure* (per-trial
# prompts tend to be too task-specific and produce duplicate skills).
BATCHED_EXTRACT_SKILL_PROMPT = """\
You are an independent reviewer acting in **generative mode** for a
SKILL.md creation step. Over the last {n_trials} successful trials,
the agent solved its tasks **without** a pre-existing skill that
materially shaped the path. Each trial is annotated with the agent's
*reusable procedural knowledge* the bridge extracted from the trace.

Your job is to **synthesize** a single, high-quality SKILL.md that
captures the *common* reusable procedure across these trials, then
**physically write it** to the sandbox directory so future similar
tasks can leverage this knowledge.

## Hard rules

  - Skill **directory name** = kebab-case, **{name_min_words}..{name_max_words}** English words.
    Examples (good): `parse-cobol` (2), `swe-coverage-trace` (3),
    `extract-elf-symbols` (3). Bad: `c` (1 char),
    `ParseCobol` (uppercase), `skill_42` (underscores).
  - Skill body must be **between {body_min_tokens} and {body_max_tokens} tokens**.
  - The body must be **the FULL content of SKILL.md** (with YAML
    frontmatter `name` / `description` per the Skill spec).
  - Do NOT include task-specific facts: no file names from the
    specific trials, no environment-specific paths, no one-off values.
  - Strip away any commentary; only the reusable *procedure*.
  - The skill must be **coherent and self-contained** — a future
    agent that has never seen any of the current trials should be
    able to follow this skill successfully on a similar task.
  - You MAY optionally create a ``scripts/`` subdirectory with helper
    code, but only if the procedure genuinely needs it.
  - The skill name in the YAML frontmatter must match the directory name.

## Aggregation strategy

  1. Read all {n_trials} trial records below.
  2. Identify the *common* reusable pattern: the procedure that
     generalises across the trials, NOT any one-off detail.
  3. If the trials are too heterogeneous to share a single procedure,
     decide: either pick the most reusable sub-pattern OR output
     ``status: skip`` with a clear rationale.
  4. Do NOT create a skill that is redundant with one of the
     available skills (list below) — in that case, output
     ``status: skip`` with reason ``redundant``.

## Write location

  - The sandbox root is: `{sandbox_dir}`
  - Write your SKILL.md to: `{sandbox_dir}/create/<skill-name>/SKILL.md`
  - All file writes must be under `{sandbox_dir}/create/<skill-name>/`
  - DO NOT write outside `{sandbox_dir}/`.

## Available skills (avoid duplicates)

The library already contains these skills. If your new skill would
be redundant with one of these, prefer extending that one (which
the bridge handles via near-miss edit) over creating a new one.
If you do create a new one, ensure its scope does not overlap.

```json
{available_skills}
```

## Aggregated trial records (chronological)

{aggregated_trials}

## Representative task (for context only; do NOT include in the skill body)

{representative_task}

## What to do

1. Read the available skills (list above) to avoid overlap.
2. Decide on a skill name (kebab-case, **{name_min_words}..{name_max_words}** words)
   that captures the *common reusable procedure*.
3. Create the directory `{sandbox_dir}/create/<skill-name>/`.
4. Write `SKILL.md` with YAML frontmatter and the procedure body.
5. Optionally add a `scripts/` subdir if the procedure has concrete
   reusable code.
6. As your **final response**, output a single JSON line:
   `{{"status": "ok", "skill_name": "<name>", "body_tokens": <N>}}`
   or `{{"status": "skip", "reason": "<why>"}}` if you decide no new
   skill is justified (heterogeneous trials, redundancy, etc.).

Begin now."""


# ---------------------------------------------------------------------------
# BATCHED_EXTRACT_SKILL_FROM_FAILURE (Rule 5 path — agent failed
# without a useful skill, summarise what to avoid next time)
# ---------------------------------------------------------------------------
# Mirrors BATCHED_EXTRACT_SKILL_PROMPT but framed for *failure*
# attribution. The aggregated "knowledge" is the LLM's failure
# analysis, not a success procedure; the resulting skill should
# encode the *guard rail* or *avoidance pattern* that would have
# prevented the failure.
BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT = """\
You are an independent reviewer acting in **generative mode** for a
SKILL.md creation step driven by **failure analysis**. Over the
last {n_trials} failed trials, the agent ran without a pre-existing
skill that would have prevented the failure. Each trial is annotated
with the *failure attribution* the bridge extracted from the trace
— a description of what went wrong and why a suitable skill was
missing.

Your job is to **synthesize** a single, high-quality SKILL.md that
captures the *common avoidance pattern* across these failures, then
**physically write it** to the sandbox directory so future similar
tasks can avoid repeating the mistake.

## Hard rules

  - Skill **directory name** = kebab-case, **{name_min_words}..{name_max_words}** English words.
  - Skill body must be **between {body_min_tokens} and {body_max_tokens} tokens**.
  - The body must be **the FULL content of SKILL.md** (with YAML
    frontmatter `name` / `description` per the Skill spec).
  - Do NOT include task-specific facts: no file names from the
    specific trials, no environment-specific paths, no one-off values.
  - The skill should encode the *reusable guard rail* — concrete
    steps to take, common pitfalls to check, and the failure
    pattern to avoid. Not just a description of what went wrong.
  - The skill MUST contain TWO structural sections in addition
    to the procedure body:
      (a) **Diagnostic checklist** — a numbered list of 2-4
          testable checks the agent MUST run BEFORE committing
          to the main approach (e.g., "Run the reference
          implementation on N=0, N=1, N=4 and confirm the
          outputs match expectations before scaling up to
          N=2^20").
      (b) **Stop signal** — a concrete threshold and reset
          action (e.g., "If you have written 3 versions of
          the generator and they all fail the same diagnostic,
          abandon the architecture and try the alternative
          listed in this skill"). Without these, the agent
          enters a debug spiral on the same architecture
          for hours (see the 2026-06-24 circuit-fibsqrt
          case study — 7 versions of gen.py, 115 min wasted).
    A skill missing either section is incomplete and will
    be rejected by the bridge.
  - You MAY optionally create a ``scripts/`` subdirectory with helper
    code, but only if the avoidance procedure genuinely needs it.
  - The skill name in the YAML frontmatter must match the directory name.

## Aggregation strategy

  1. Read all {n_trials} failure records below.
  2. Identify the *common* failure pattern: the recurring mistake or
     missing check that generalises across the trials.
  3. Phrase the resulting skill as an *actionable guard rail* —
     "before doing X, first check Y", "do not do Z when condition W".
  4. If the failures are too heterogeneous to share a single
     guard rail, decide: pick the most reusable sub-pattern OR
     output ``status: skip`` with a clear rationale.
  5. Do NOT create a skill that is redundant with one of the
     available skills (list below) — in that case, output
     ``status: skip`` with reason ``redundant``.

## Preferred seed (2026-06-25)

Each failure record below carries TWO knowledge fields:

- ``knowledge_to_extract`` — the agent's diagnosis of *what
  went wrong* (free-form, sometimes vague).
- ``library_gap_skill_description`` — the explicit "what skill
  SHOULD have been in the library" statement from the
  attribution step. This field is more actionable because it
  names the domain keyword and the guard rails the missing
  skill should encode.

When a failure record includes a non-empty
``library_gap_skill_description``, treat it as the *primary
seed* for the synthesized skill body. Use it to:

  - Choose the skill name (kebab-case, reflecting the domain
    keyword from the gap description).
  - Write the YAML `description` (so future retrieval can
    find it via the gap keyword).
  - Write the Diagnostic checklist (concrete checks the new
    skill should require).

The ``knowledge_to_extract`` field is secondary — use it only
when the gap description is empty, or to add colour to the
guard-rail body. When the two disagree, the gap description
wins.

## Write location

  - The sandbox root is: `{sandbox_dir}`
  - Write your SKILL.md to: `{sandbox_dir}/create/<skill-name>/SKILL.md`
  - All file writes must be under `{sandbox_dir}/create/<skill-name>/`
  - DO NOT write outside `{sandbox_dir}/`.

## Available skills (avoid duplicates)

The library already contains these skills. If your new skill would
be redundant with one of these, prefer extending that one (which
the bridge handles via near-miss edit) over creating a new one.
If you do create a new one, ensure its scope does not overlap.

```json
{available_skills}
```

## Aggregated failure records (chronological)

{aggregated_trials}

## Representative task (for context only; do NOT include in the skill body)

{representative_task}

## What to do

1. Read the available skills (list above) to avoid overlap.
2. Decide on a skill name (kebab-case, **{name_min_words}..{name_max_words}** words)
   that captures the *common avoidance pattern*.
3. Create the directory `{sandbox_dir}/create/<skill-name>/`.
4. Write `SKILL.md` with YAML frontmatter and the guard-rail body.
5. Optionally add a `scripts/` subdir if the procedure has concrete
   reusable code.
6. As your **final response**, output a single JSON line:
   `{{"status": "ok", "skill_name": "<name>", "body_tokens": <N>}}`
   or `{{"status": "skip", "reason": "<why>"}}` if you decide no new
   skill is justified (heterogeneous failures, redundancy, etc.).

Begin now."""
