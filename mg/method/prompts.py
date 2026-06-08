"""mg-side prompts for the LQRL paper method.

These are intentionally **not** copies of the prompts in
``lqrl/src/skills_vote/{feedback,evolve,recommend}/prompt.py``. The
naming, rubric, JSON schema, and constraints all differ:

- **VERIFIER_PROMPT** uses four axes (clarity / completeness /
  non_redundancy / correctness) with a fixed-weight mean, and a
  compact JSON output ``{old_score, new_score, improved, rationale}``.
  The :class:`mg.method.verifier.IndependentVerifier` is *information
  isolated*: it sees (task, old_skill, new_skill) only.
- **EDIT_PROMPT** (Sec. 3.4) caps the edit to 20% of the original
  token count, requires the skill name to be unchanged, and bans new
  tools / files. Returns the *full* post-edit skill, not a diff.
- **RETRIEVAL_PROMPT** documents the Eq. 4 score breakdown so a
  reviewer can audit the UCB re-rank decisions offline.
- **EXPLAIN_R_LEARNING_PROMPT** is a small helper for human audit of
  why a particular $r_{\\text{learning}}$ value was chosen.
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
# RETRIEVAL (Eq. 4 — audit-only)
# ---------------------------------------------------------------------------
RETRIEVAL_PROMPT = """\
You are auditing a Phase-B re-ranking decision. The score assigned to a \
skill $m$ for query $s$ is

    score(s, m) = (1 - lambda) * sim_z(phi(s), phi(m))
                + lambda       * q_z(s, m)
                + c_ucb        * sqrt(log N / (n_m + 1))

where:

  - ``sim_z`` is the z-scored cosine similarity in the Phase-A pool.
  - ``q_z`` is the z-scored Q-value for the (intent, skill) pair.
  - ``N`` is the total number of retrievals across the library.
  - ``n_m`` is the number of times skill ``m`` has been retrieved.

Explain, in one or two sentences, why a particular skill was ranked at \
position ``{rank}`` with score ``{score:.3f}``. Reference the three \
components above by their relative magnitudes.

CANDIDATE SKILL
---------------
{skill_body}

Q-VALUE (raw)
{q_raw}

N_RETRIEVALS
{n_retrievals}

Your explanation (one short paragraph):"""


# ---------------------------------------------------------------------------
# ATTRIBUTION (mirrors lqrl feedback step)
# ---------------------------------------------------------------------------
ATTRIBUTION_PROMPT = """\
You are a feedback analyzer. You will see a successful or failed task
execution trace (rendered as a markdown transcript of a Claude Code
session), a list of skill names that were *available* in the
agent's environment, and the task description. Your job is to
attribute the trial's outcome to one of six categories AND, when
the trial succeeded, extract the *reusable procedural knowledge*
the agent discovered.

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
  wrong). Empty string if nothing reusable. DO NOT include
  task-specific facts, paths, or one-off values; only the
  reusable *procedure*.

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
# EXTRACT_SKILL (Layer 4.5 / "create" path, run as subprocess claude --print)
# ---------------------------------------------------------------------------
EXTRACT_SKILL_PROMPT = """\
You are an independent reviewer acting in **generative mode** for a
SKILL.md creation step. The agent just succeeded at a task without a
pre-existing skill that materially shaped the path. Your job is to
**physically write a new SKILL.md** to the sandbox directory so the
next similar task can leverage this knowledge.

## Hard rules

  - Skill **directory name** = kebab-case, **{name_min_words}..{name_max_words}** English words.
    Examples (good): `parse-cobol` (2), `swe-coverage-trace` (3),
    `extract-elf-symbols` (3). Bad: `c` (1 char), `parse-the-cobol-program` (4+ words OK if exactly 4),
    `ParseCobol` (uppercase), `skill_42` (underscores).
  - Skill body must be **between {body_min_tokens} and {body_max_tokens} tokens**.
  - The body must be **the FULL content of SKILL.md** (with YAML
    frontmatter `name` / `description` per the Skill spec).
  - Do NOT include task-specific facts: no file names from the
    specific trial, no environment-specific paths, no one-off values.
  - Strip away any commentary; only the reusable *procedure*.
  - The skill must be **coherent and self-contained** — a future
    agent that has never seen the current trial should be able to
    follow this skill successfully on a similar task.
  - You MAY optionally create a ``scripts/`` subdirectory with helper
    code, but only if the procedure genuinely needs it.
  - The skill name in the YAML frontmatter must match the directory name.

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

## Task the agent just succeeded at

{task}

## Reusable procedural knowledge the agent discovered

{knowledge}

## Intent hash (for traceability, do NOT include in the skill body)

{intent_hash}

## What to do

1. Read the existing skills (the list above) to avoid overlap.
2. Decide on a skill name (kebab-case, **{name_min_words}..{name_max_words}** words)
   that captures the *reusable procedure*.
3. Create the directory `{sandbox_dir}/create/<skill-name>/`.
4. Write `SKILL.md` with YAML frontmatter and the procedure body.
5. Optionally add a `scripts/` subdir if the procedure has concrete
   reusable code.
6. As your **final response**, output a single JSON line:
   `{{"status": "ok", "skill_name": "<name>", "body_tokens": <N>}}`
   or `{{"status": "skip", "reason": "..."}}` if you decide no new
   skill is justified (e.g., knowledge is too task-specific).

Begin now."""


# ---------------------------------------------------------------------------
# EXPLAIN_R_LEARNING (audit-only)
# ---------------------------------------------------------------------------
EXPLAIN_R_LEARNING_PROMPT = """\
You are explaining a learning-reward value to a reviewer. Given the \
verifier's four-axis scores on the (old, new) skill delta, articulate \
the dominant axis that drove the value of ``r_learning`` and the size \
of the gap.

OLD SCORE: {old_score}
NEW SCORE: {new_score}
R_LEARNING: {r_learning:.3f}
IMPROVED: {improved}

Write a single sentence explaining which axis (clarity, completeness, \
non_redundancy, correctness) drove the delta and whether the gap is \
small, moderate, or large.
"""
