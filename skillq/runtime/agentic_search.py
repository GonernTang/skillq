"""Method A (agentic) retrieval — paper's small-library design.

In agentic mode the bridge does **not** install a PreToolUse hook.
Instead, on every ``on_trial_started`` we:

1. Write each skill's body to ``<trial_dir>/skillq_skills/<name>/SKILL.md``
   with a YAML frontmatter enriched with ``q_value``,
   ``n_uses``, ``n_success`` (the agent can read these when it
   ``cat``s the file).
2. Write a ``_manifest.json`` that lists every skill with the same
   metadata — used by the search script.
3. Write a ``_search.sh`` bash script that the agent invokes as::

       bash $CLAUDE_CONFIG_DIR/skillq_skills/_search.sh "query" [--top-k N]

   The script does: grep across SKILL.md files (rank_grep) +
   sort by Q value (rank_q) → RRF fusion → top-k JSON output.
4. Write a ``CLAUDE.md`` snippet into the container's
   ``$CLAUDE_CONFIG_DIR/CLAUDE.md`` so the agent knows the search
   tool exists and how to call it.

The bridge bind-mounts the staging dir into the container at
``$CLAUDE_CONFIG_DIR/<agentic_skill_dir_name>``.

References:
- Paper §3.1 "Method A" — system-prompt injection + agentic search.
- The actual injection mechanism is a CLAUDE.md file (not the
  system prompt), per design choice 2026-06-14.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from skillq.shared.types import Qlib, Skill


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------
_YAML_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _read_existing_body(raw: str) -> tuple[dict[str, str], str]:
    """Split a SKILL.md into (frontmatter_dict, body). Missing
    frontmatter → ({}, raw).
    """
    m = _YAML_RE.match(raw)
    if not m:
        return {}, raw
    fm_block, body = m.group(1), m.group(2)
    out: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out, body


def render_skill_md(skill: Skill, *, q_value: float, n_uses: int, n_success: int) -> str:
    """Render a SKILL.md with enriched frontmatter.

    Preserves any existing frontmatter fields the skill may have
    (e.g. ``description``, ``name`` from earlier writes) and
    overwrites the three Q-related fields.
    """
    existing_fm, body = _read_existing_body(skill.body)
    # Sanitize body (strip a leading "---\\n...\\n---\\n" if the
    # stored body accidentally includes frontmatter).
    existing_fm.setdefault("name", skill.skill_id)
    existing_fm["q_value"] = f"{q_value:.3f}"
    existing_fm["n_uses"] = str(int(n_uses))
    existing_fm["n_success"] = str(int(n_success))
    fm_lines = "\n".join(f"{k}: {v}" for k, v in existing_fm.items())
    return f"---\n{fm_lines}\n---\n{body.lstrip()}"


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
def render_manifest(lib: Qlib, q_for) -> str:
    """Render ``_manifest.json`` listing every skill with metadata.

    Parameters
    ----------
    lib : Qlib
        The library snapshot.
    q_for : callable
        ``Qlib -> skill_id -> float`` — the Q-value lookup.
    """
    skills_out: list[dict[str, Any]] = []
    for s in lib.skills.values():
        skills_out.append(
            {
                "name": s.skill_id,
                "description": _extract_description(s.body),
                "q_value": round(float(q_for(s.skill_id)), 4),
                "n_uses": int(s.n_uses),
                "n_success": int(s.n_success),
            }
        )
    return json.dumps({"skills": skills_out}, ensure_ascii=False, indent=2) + "\n"


def _extract_description(body: str) -> str:
    """Pull the ``description`` field from the SKILL.md frontmatter,
    or return a short snippet of the first body line.
    """
    fm, body_text = _read_existing_body(body)
    if "description" in fm:
        return fm["description"]
    first_line = next((l.strip() for l in body_text.splitlines() if l.strip()), "")
    return first_line[:200]


# ---------------------------------------------------------------------------
# _search.sh
# ---------------------------------------------------------------------------
_SEARCH_SH_TEMPLATE = """#!/usr/bin/env bash
# _search.sh — Method A search (RRF fusion of grep + Q-value ranking)
#
# Usage:
#   bash _search.sh "query" [--top-k N] [--k-rrf K]
#
# Output: a JSON array of objects, sorted by rrf_score desc:
#   [{"name", "description", "q_value", "n_uses", "n_success",
#     "rank_grep", "rank_q", "rrf_score"}, ...]
#
# Dependencies: bash, grep, awk, sort, head. No python3, no jq.
# Hand-rolled JSON output keeps the script portable to minimal
# container images.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUERY="${1:-}"
TOP_K="{TOP_K}"
K_RRF="{K_RRF}"
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --top-k) TOP_K="$2"; shift 2 ;;
    --k-rrf) K_RRF="$2"; shift 2 ;;
    *) shift ;;
  esac
done

if [[ -z "$QUERY" ]]; then
  echo "[]"
  exit 0
fi

MANIFEST="$SCRIPT_DIR/_manifest.json"
if [[ ! -f "$MANIFEST" ]]; then
  echo "[]"
  exit 0
fi

# Temp files. Use mktemp to avoid clobbering under concurrent runs.
TMP_BASE="$(mktemp -d -t skillqsearch.XXXXXX)"
trap 'rm -rf "$TMP_BASE"' EXIT

SKILLS_Q="$TMP_BASE/skills_q.txt"        # name<TAB>q<TAB>desc
RANK_GREP="$TMP_BASE/rank_grep.txt"      # 1 name per line, in file order
RRF_OUT="$TMP_BASE/rrf.txt"              # name<TAB>q<TAB>desc<TAB>rg<TAB>rq<TAB>rrf

# 1. Parse manifest: extract name, q_value, description for each skill.
#    Uses awk with simple regex matching on the line-oriented JSON
#    produced by render_manifest (indent=2, no embedded newlines in
#    string values). Each line of output: name<TAB>q<TAB>description
#
#    The JSON emits fields in order: name, description, q_value. We
#    buffer all three and flush when we see the *next* name (or EOF).
awk -v OUT="$SKILLS_Q" '
  /"name":/ {
    # Flush the previous record (if any)
    if (name != "") {
      print name "\\t" q "\\t" desc > OUT
    }
    match($0, /"name"[[:space:]]*:[[:space:]]*"([^"]+)"/, a)
    name = a[1]
    q = 0
    desc = ""
  }
  /"q_value":/ {
    match($0, /"q_value"[[:space:]]*:[[:space:]]*([0-9.]+)/, a)
    q = a[1] + 0
  }
  /"description":/ {
    match($0, /"description"[[:space:]]*:[[:space:]]*"([^"]*)"/, a)
    desc = a[1]
  }
  END {
    # Flush the last record
    if (name != "") {
      print name "\\t" q "\\t" desc > OUT
    }
  }
' "$MANIFEST"

if [[ ! -s "$SKILLS_Q" ]]; then
  echo "[]"
  exit 0
fi

# 2. rank_grep: case-insensitive grep across SKILL.md files. One
#    matching skill per line, in directory listing order. uniq -i
#    is not used (we want first-occurrence order for the rank).
grep -ril -- "$QUERY" "$SCRIPT_DIR"/*/SKILL.md 2>/dev/null \
  | xargs -I{} dirname {} 2>/dev/null \
  | xargs -I{} basename {} 2>/dev/null > "$RANK_GREP" || true

# 3. RRF fusion via awk.
#    - Reads SKILLS_Q, sorts by q desc (handled by sort -k2 -rn)
#    - Loads rank_grep into an associative array indexed by name
#    - Emits per-skill rrf_score, then sort -rn takes top-K
#    - Set FS="\t" so description (which may contain spaces) is
#      captured as a single $3 field.
sort -t$'\\t' -k2,2 -rn "$SKILLS_Q" \
  | awk -v RG="$RANK_GREP" -v K="$K_RRF" -v OUT="$RRF_OUT" '
      BEGIN {
        FS = "\t"
        # Load rank_grep: 1-indexed, by line order in the file.
        rg_n = 0
        while ((getline line < RG) > 0) {
          rg[line] = ++rg_n
        }
        close(RG)
        n_total = (rg_n > 0) ? rg_n : 0
        rq = 0
      }
      {
        rq++
        name = $1
        q = $2
        desc = $3
        # If not in rank_grep, use n_total + 1 (last place).
        rg_pos = (name in rg) ? rg[name] : n_total + 1
        rrf = 1.0 / (K + rg_pos) + 1.0 / (K + rq)
        printf "%s\\t%s\\t%s\\t%d\\t%d\\t%.6f\\n", name, q, desc, rg_pos, rq, rrf > OUT
      }
    '

# 4. Sort by rrf desc, take top-K, format as JSON.
sort -t$'\\t' -k6,6 -rn "$RRF_OUT" | head -n "$TOP_K" > "$TMP_BASE/topk.txt"

# 5. JSON output (hand-rolled). Each topk line:
#    name<TAB>q<TAB>desc<TAB>rg<TAB>rq<TAB>rrf
{
  echo "["
  first=1
  while IFS=$'\\t' read -r name q desc rg rq rrf; do
    [[ -z "$name" ]] && continue
    if [[ $first -eq 0 ]]; then echo ","; fi
    first=0
    # Escape any double-quotes / backslashes in the description.
    esc_desc="${desc//\\\\/\\\\\\\\}"
    esc_desc="${esc_desc//\\"/\\\\\\"}"
    # rg can be n_total+1 (sentinel) — render as null in that case.
    rg_field="null"
    if [[ "$rg" -le 0 || "$rg" -gt 1000000 ]]; then
      rg_field="null"
    else
      rg_field="$rg"
    fi
    printf '{"name": "%s", "description": "%s", "q_value": %s, "n_uses": 0, "n_success": 0, "rank_grep": %s, "rank_q": %s, "rrf_score": %s}' \\
      "$name" "$esc_desc" "$q" "$rg_field" "$rq" "$rrf"
  done < "$TMP_BASE/topk.txt"
  echo ""
  echo "]"
}
"""


def render_search_sh(*, top_k: int, k_rrf: int) -> str:
    return _SEARCH_SH_TEMPLATE.replace("{TOP_K}", str(top_k)).replace(
        "{K_RRF}", str(k_rrf)
    )


# ---------------------------------------------------------------------------
# Paper-method instructions snippet
# ---------------------------------------------------------------------------
# This is **not** named ``CLAUDE.md`` to avoid conflicting with the
# user's existing CLAUDE.md. It is written to the staging dir and
# bind-mounted at ``$CLAUDE_CONFIG_DIR/<agentic_skill_dir_name>/``.
# The container_wiring layer optionally merges it with the user's
# existing CLAUDE.md (see ``user_claude_md_path`` in MethodConfig).
INSTRUCTIONS_SNIPPET = """\
# Paper-method skill search (Method A)

You have a curated library of skills under
`$CLAUDE_CONFIG_DIR/{SKILLS_DIR}/`. Each skill is a directory
containing a `SKILL.md` with a YAML frontmatter that includes
`q_value`, `n_uses`, and `n_success` — use these to gauge how
reliable each skill has been historically.

To find skills relevant to the current task, run:

```
bash $CLAUDE_CONFIG_DIR/{SKILLS_DIR}/_search.sh "your natural-language query"
```

The script returns a JSON array of the top-{TOP_K} skills, sorted
by RRF fusion of lexical match and Q-value. Pick the top-1 (or
skip if none fit), then call `Skill("top-1-name")` to load it.

You may also `cat` any individual `SKILL.md` directly, or
`ls $CLAUDE_CONFIG_DIR/{SKILLS_DIR}/` to see everything available.

The Q values are updated at the end of each trial by the host
process; you will see the freshest Q at the start of the next
trial.
"""


def render_instructions(*, skills_dir_name: str, top_k: int) -> str:
    """Render the skillq-method instructions snippet."""
    return (
        INSTRUCTIONS_SNIPPET.replace("{SKILLS_DIR}", skills_dir_name).replace(
            "{TOP_K}", str(top_k)
        )
    )


def render_claude_md(*, skills_dir_name: str, top_k: int) -> str:
    """Backwards-compatible alias for :func:`render_instructions`."""
    return render_instructions(skills_dir_name=skills_dir_name, top_k=top_k)


# Method B (hook) — the PreToolUse hook intercepts every Skill()
# call and re-ranks it against the paper-method library using
# Eq. 4 (cosine + Q + UCB). The agent does not need to pre-sort
# skills; it just needs to know that the Skill tool is wired up
# and where to find the SKILL.md files. The host process handles
# the ranking; the agent should just call Skill("<name>") when
# the description matches the current task.
HOOK_INSTRUCTIONS_SNIPPET = """\
# Curated skills are available (Method B) — REQUIRED USAGE

You have a curated library of skills at `$CLAUDE_CONFIG_DIR/skills/`.
Each subdirectory contains a `SKILL.md` describing one skill.

**Required: read the catalog and decide if any skill clearly
matches the current task before your first shell action.** This
is not optional — but "no match" is also a valid answer (see
step 3 below). The host records every Skill() call, re-ranks
them against the curated library, and updates the Q-table.

Concretely:

1. Read the catalog (SessionStart injection or
   `ls $CLAUDE_CONFIG_DIR/skills/`) and pick the skill
   whose `SKILL.md` description most directly covers the
   user's request. Prefer specificity over breadth.
2. **Only call `Skill("<name>")` if the skill's description
   clearly matches the task** — i.e., it names the
   technology, file format, or procedure the task requires.
   Match is a judgment call, not a keyword match; a Python
   regex skill is NOT a match for a circuit-synthesis task
   even if both involve "code generation".
3. **If no skill clearly matches, do NOT call Skill() at all.**
   Instead, write one line in your reasoning, in this exact
   form:
   `LIBRARY_GAP: no skill in $CLAUDE_CONFIG_DIR/skills/
   matches this task (need <one-line description of what
   would have helped, e.g. "a skill covering hardware
   circuit synthesis with sanity-test checklist">)`
   The host treats this as a signal to potentially
   auto-extract a new skill at trial end — leaving it
   blank is a missed opportunity for the library to grow.
4. After loading a matching skill, follow its instructions
   before continuing with shell or edit actions.

**Why "wrong" calls hurt:** Calling an unrelated skill
produces a bad attribution signal that demotes genuinely
relevant skills in future trials. The hook logs every
Skill() call; "wrong" calls hurt future ranking. The
host re-ranks on a per-trial basis — you do not need
to pre-sort, but you do need to call only when the
match is real.

(2026-06-25: rewrote the compliance clause above. The
previous wording "calling the wrong skill is fine" caused
agents to invoke irrelevant skills as a "tick-the-box"
gesture — see the 2026-06-24 circuit-fibsqrt case study.)
"""


def render_hook_instructions() -> str:
    """Render the skillq-method instructions snippet for hook (Method B).

    Unlike :func:`render_instructions` (Method A) this snippet has
    no template variables — the curated skills always live at the
    same path (``$CLAUDE_CONFIG_DIR/skills/``) and the agent is
    expected to call the Skill tool directly rather than going
    through a search script.
    """
    return HOOK_INSTRUCTIONS_SNIPPET


# ---------------------------------------------------------------------------
# Pull-mode (2026-06-23): CLAUDE.md fallback for the agent's first turn
# ---------------------------------------------------------------------------
def render_pull_recommendation(
    *,
    task_name: str,
    top_k: list[tuple[str, float]],
    skills_by_id: dict[str, Any],
    lambda_: float = 0.5,
    c_ucb: float = 0.0,
    subtask_emb: list[float] | None = None,
) -> str:
    """Render a Top-K skills recommendation block for the agent's CLAUDE.md.

    Used by retrieval_mode='pull'. Why this exists instead of just the
    UserPromptSubmit hook: in ``claude --print`` (non-interactive) mode
    Claude Code does NOT fire the UserPromptSubmit hook — only SessionStart
    and PreToolUse fire. So the recommendation has to land in CLAUDE.md
    where the agent will see it on its first turn.

    Args:
        task_name: Used as the query text when subtask_emb is None
            (no live embed available at trial start). Falls back to
            Q + UCB-only ranking.
        top_k: Pre-computed ``[(skill_id, score), ...]`` from a
            scoring call. If None or empty, returns a degraded
            reminder text.
        skills_by_id: ``{skill_id: skill_dict}`` for description lookup.
        lambda_/c_ucb: Score equation params — only used for the hint
            footer, not for re-ranking.
        subtask_emb: Optional embedding vector for the task. When
            None, footer flags "Q + UCB only" (no semantic similarity).
    """
    if not top_k:
        return (
            "# Top-K skills recommendation (pull-mode)\n\n"
            "The skillq library is empty or scoring failed. "
            "Call `Skill(\"<name>\")` for any skill whose description "
            "matches the task — the host will gate the call.\n"
        )
    lines = [
        "# Top-K skills recommendation (pull-mode, 2026-06-23)",
        "",
        "Before your first shell action, call `Skill(\"<id>\")` for "
        "one of the Top-K skills below. The host re-ranks these "
        "against the curated library, gates the call, and updates "
        "the Q-table. **Use the Skill tool — do not `cat` the SKILL.md "
        "manually.**",
        "",
        f"Task query used for ranking: `{task_name}`",
        f"Score = (1-λ={1 - lambda_:.1f}) sim_z + λ={lambda_:.1f} q_z "
        f"+ c_ucb={c_ucb} sqrt(log N/(n+1))",
        "",
        f"**Top-{len(top_k)} skills for this task** (invoke via "
        "`Skill(\"<skill_id>\")`):",
        "",
    ]
    for i, (sid, score) in enumerate(top_k, 1):
        sk = skills_by_id.get(sid, {})
        desc = (sk.get("description") or "").replace("\n", " ").strip()
        if len(desc) > 120:
            desc = desc[:117] + "..."
        lines.append(f"{i}. **{sid}**   score={score:+.3f}")
        if desc:
            lines.append(f"   - {desc}")
    if subtask_emb is None:
        lines.append("")
        lines.append(
            "*(embedding unavailable at trial start; ranking used "
            "Q + UCB only — semantic similarity term is 0)*"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Orchestrator: write everything for one trial
# ---------------------------------------------------------------------------
@dataclass
class AgenticSearchWriter:
    """Materialize the Method-A artifact tree for one trial.

    Output layout under ``staging_dir``::

        staging_dir/
        ├── <skill_id>/
        │   └── SKILL.md
        ├── _manifest.json
        ├── _search.sh
        └── CLAUDE.md

    The bridge bind-mounts ``staging_dir`` into the container at
    ``$CLAUDE_CONFIG_DIR/<agentic_skill_dir_name>``.
    """

    skills_dir_name: str  # e.g. "skillq_skills"
    top_k: int = 3
    k_rrf: int = 60

    def write(
        self,
        *,
        staging_dir: Path,
        lib: Qlib,
        q_for,
    ) -> Path:
        """Write the artifact tree. Returns the staging_dir."""
        staging_dir.mkdir(parents=True, exist_ok=True)

        # 1. Per-skill SKILL.md
        for s in lib.skills.values():
            skill_dir = staging_dir / s.skill_id
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                render_skill_md(
                    s,
                    q_value=q_for(s.skill_id),
                    n_uses=s.n_uses,
                    n_success=s.n_success,
                ),
                encoding="utf-8",
            )

        # 2. Manifest
        (staging_dir / "_manifest.json").write_text(
            render_manifest(lib, q_for), encoding="utf-8"
        )

        # 3. Search script
        search_path = staging_dir / "_search.sh"
        search_path.write_text(
            render_search_sh(top_k=self.top_k, k_rrf=self.k_rrf),
            encoding="utf-8",
        )
        search_path.chmod(0o755)

        # 4. Paper-method instructions (NOT named CLAUDE.md so we
        #    never overwrite the user's existing CLAUDE.md). The
        #    container_wiring layer optionally merges this with the
        #    user's CLAUDE.md (see user_claude_md_path).
        (staging_dir / "PAPER_METHOD_INSTRUCTIONS.md").write_text(
            render_instructions(
                skills_dir_name=self.skills_dir_name, top_k=self.top_k
            ),
            encoding="utf-8",
        )

        return staging_dir


__all__ = [
    "AgenticSearchWriter",
    "render_skill_md",
    "render_manifest",
    "render_search_sh",
    "render_instructions",
    "render_claude_md",  # backwards-compat alias
    "render_hook_instructions",
    "render_pull_recommendation",
]
