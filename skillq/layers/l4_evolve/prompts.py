"""L4 evolve prompts (Step 6 of the 2026-06-26 refactor).

Inlined from ``skillq/layers/l4_evolve/prompts.py``. Own wording,
intentionally not a copy of the vendored skillsvote prompts.

- :data:`BATCHED_EXTRACT_SKILL_PROMPT` is the system prompt for the
  batched-evolve ``claude --print`` subprocess. Aggregates N
  successful (task, knowledge) records into a single new SKILL.md.
- :data:`BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT` is the symmetric
  version for the failure path (Rule 5 — failure + no useful skill →
  new guard-rail skill). Aggregates N failure-attribution records
  into a single guard-rail SKILL.md.
"""

from __future__ import annotations


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

## Write location

  - The sandbox root is: `{sandbox_dir}`
  - Write your SKILL.md to: `{sandbox_dir}/create/<skill-name>/SKILL.md`
  - All file writes must be under `{sandbox_dir}/create/<skill-name>/`
  - DO NOT write outside `{sandbox_dir}`.

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
    be rejected by the bridge (2026-06-25: enforced in
    ``skillq/layers/l4_evolve/create.py:_collect_skill`` via the
    ``SkillExtractor.enforce_failure_skill_structure`` flag,
    default True; configured by
    ``MethodConfig.enforce_failure_skill_structure``).
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
  - DO NOT write outside `{sandbox_dir}`.

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


# ---------------------------------------------------------------------------
# PER_TRIAL_EXTRACT_SKILL (single-trial path, 2026-07-03)
# ---------------------------------------------------------------------------
# When extract_every_n_trials=1 (or buffer threshold=1), a single trial's
# knowledge record is the input. The batched prompt's "find common patterns
# across N trials" framing is vacuous for N=1 and harmful when N>1 with
# heterogeneous tasks grouped only by mode. This prompt tells the LLM to
# distill one trial's reusable knowledge into a SKILL.md, with an explicit
# skip gate for knowledge that is too task-specific.
PER_TRIAL_EXTRACT_SKILL_PROMPT = """\
You are an independent reviewer in **generative mode**. The agent
just solved a task **without** a pre-existing skill. Below is the
reusable procedural knowledge extracted from its trajectory.

Your job: synthesize a single SKILL.md that captures this procedure
so future agents facing similar tasks can reuse it.

## Hard rules

  - Skill **directory name** = kebab-case, **{name_min_words}..{name_max_words}** English words.
  - Skill body must be **between {body_min_tokens} and {body_max_tokens} tokens**.
  - The body must be **the FULL content of SKILL.md** (with YAML
    frontmatter `name` / `description` per the Skill spec).
  - Do NOT include task-specific facts: no file names from the
    current trial, no environment-specific paths, no one-off values.
  - The skill must be **self-contained**: an agent that has never
    seen this trial should be able to follow the skill on a similar
    task.
  - If the knowledge is too task-specific to form a reusable skill,
    output ``{{"status": "skip", "reason": "<why>"}}`` instead.
  - The skill name in the YAML frontmatter must match the directory name.

## Trial record

**Task description**: {task}

**Reusable knowledge** (extracted from the trace):
{knowledge}

## Write location

  - The sandbox root is: `{sandbox_dir}`
  - Write your SKILL.md to: `{sandbox_dir}/create/<skill-name>/SKILL.md`
  - All file writes must be under `{sandbox_dir}/create/<skill-name>/`
  - DO NOT write outside `{sandbox_dir}`.

## What to do

1. Decide on a skill name (kebab-case, **{name_min_words}..{name_max_words}** words)
   that captures the reusable procedure.
2. Create the directory `{sandbox_dir}/create/<skill-name>/`.
3. Write `SKILL.md` with YAML frontmatter and the procedure body.
4. As your **final response**, output a single JSON line:
   `{{"status": "ok", "skill_name": "<name>", "body_tokens": <N>}}`
   or `{{"status": "skip", "reason": "<why>"}}`.

Begin now."""


# ---------------------------------------------------------------------------
# PER_TRIAL_EXTRACT_SKILL_FROM_FAILURE (single-trial failure path, 2026-07-03)
# ---------------------------------------------------------------------------
PER_TRIAL_EXTRACT_SKILL_FROM_FAILURE_PROMPT = """\
You are an independent reviewer in **generative mode** for a
SKILL.md creation step driven by **failure analysis**. The agent
just failed on a task without a pre-existing skill that would have
prevented the failure. Below is the failure attribution.

Your job: synthesize a single SKILL.md that captures the *avoidance
pattern* as a guard-rail, so future agents can avoid repeating this
mistake.

## Hard rules

  - Skill **directory name** = kebab-case, **{name_min_words}..{name_max_words}** English words.
  - Skill body must be **between {body_min_tokens} and {body_max_tokens} tokens**.
  - The body must be **the FULL content of SKILL.md** (with YAML
    frontmatter `name` / `description` per the Skill spec).
  - Do NOT include task-specific facts: no file names from the
    current trial, no environment-specific paths, no one-off values.
  - The skill must contain TWO structural sections:
      (a) **Diagnostic checklist** — 2-4 testable checks the agent
          MUST run BEFORE committing to the main approach.
      (b) **Stop signal** — a concrete threshold and reset action.
    A skill missing either section is incomplete and will be rejected.
  - The skill name in the YAML frontmatter must match the directory name.

## Trial record

**Task description**: {task}

**Failure attribution** (what went wrong and why a skill was missing):
{knowledge}

## Write location

  - The sandbox root is: `{sandbox_dir}`
  - Write your SKILL.md to: `{sandbox_dir}/create/<skill-name>/SKILL.md`

## What to do

1. Decide on a skill name (kebab-case, **{name_min_words}..{name_max_words}** words)
   that captures the avoidance pattern.
2. Create the directory `{sandbox_dir}/create/<skill-name>/`.
3. Write `SKILL.md` with YAML frontmatter and the guard-rail body.
4. As your **final response**, output a single JSON line:
   `{{"status": "ok", "skill_name": "<name>", "body_tokens": <N>}}`
   or `{{"status": "skip", "reason": "<why>"}}`.

Begin now."""


__all__ = [
    "BATCHED_EXTRACT_SKILL_PROMPT",
    "BATCHED_EXTRACT_SKILL_FROM_FAILURE_PROMPT",
    "PER_TRIAL_EXTRACT_SKILL_PROMPT",
    "PER_TRIAL_EXTRACT_SKILL_FROM_FAILURE_PROMPT",
]
