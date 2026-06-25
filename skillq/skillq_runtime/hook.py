"""Container-side PreToolUse hook for the per-subtask skill retrieval.

**This file is read by the agent container at run time**, not at the
mg CLI's Python import time. The hook is configured via Claude
Code's ``settings.json`` and is invoked synchronously before each
``Skill`` tool call. It MUST be a self-contained executable Python
script (the host's ``paper.*`` modules are NOT importable inside
the container; the hook only depends on stdlib + the
``requests`` package, which is preinstalled in the prebuilt image).

**Flow** (per design 2026-06-11):

1. Agent calls ``Skill("X")``.
2. Claude Code fires ``PreToolUse`` for the ``Skill`` tool.
3. Hook reads:
   - ``$SKILLQ_LIB`` — JSON list of {skill_id, description, body, n_retrievals}
   - ``$SKILLQ_Q_TABLE`` — JSON {skill_id: q}
   - ``$SKILLQ_EMB_CACHE`` — JSON {skill_id: [embedding_vec]}
   - ``$SKILLQ_CALLS_LOG`` — append-only path for sub-task call log
   - ``$SKILLQ_EMBED_HOST`` / ``$SKILLQ_EMBED_PORT`` — where to call for sub-task
     embedding
   - ``$SKILLQ_TRANSCRIPT`` — path to the session transcript (set by
     Claude Code as ``CLAUDE_TRANSCRIPT_PATH``)
4. Hook reads the last 2-3 assistant messages from the transcript,
   concats with the requested skill name, embeds via HTTP call to
   the host embedding service.
5. Computes Eq. 4 score per skill:
       score = (1-λ) * sim_z + λ * q_z + c_ucb * sqrt(log N / (n+1))
6. Returns top-k. If the requested skill is in the top-k, allow.
   Otherwise, block with a list of top-k skills + "or skip" hint.
7. Logs the call (timestamp, requested, top-k, approved) to
   ``$SKILLQ_CALLS_LOG`` (one JSON line per call).
8. Failure-open: if the embedding call times out (>5s) or errors,
   the hook returns ``approve`` so a single embedding outage does
   not block trials.

**Top-level entrypoint**: :func:`main` (no args). Reads JSON from
stdin (Claude Code hook protocol), writes JSON to stdout, and exits
0 for any decision (allow or block) or 2 for hard errors.

**Hook input format** (Claude Code PreToolUse):

.. code-block:: json

    {
      "session_id": "...",
      "transcript_path": "/path/to/.jsonl",
      "cwd": "/...",
      "hook_event_name": "PreToolUse",
      "tool_name": "Skill",
      "tool_input": {"skill": "fix-git-basics"},
      ...
    }

**Hook output format** (Claude Code PreToolUse):

.. code-block:: json

    {
      "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow" | "deny",
        "permissionDecisionReason": "..."
      }
    }

For "deny" with a reason, the agent sees the reason text in its
context and is expected to re-call Skill with one of the suggested
skill names, or skip the call.

**Pull-mode** (added 2026-06-23, retrieval_mode='pull'): in addition
to the PreToolUse handler above, ``main()`` also dispatches the
``SessionStart`` event. ``SessionStart`` fires once per ``claude``
subprocess invocation (per trial under harbor), before the agent's
first turn. The handler embeds the user's prompt, runs the same
Eq. 4 scoring, and emits a ``hookSpecificOutput.additionalContext``
block listing the top-``SKILLQ_PULL_TOP_K`` skills. The agent sees
this reminder as part of its first-turn context and can call any of
the listed skills via ``Skill(skill="<skill_id>")``. The
PreToolUse handler continues to gate and Q-update those calls.

**Hook input format** (Claude Code SessionStart):

.. code-block:: json

    {
      "session_id": "...",
      "transcript_path": "/path/to/.jsonl",
      "cwd": "/...",
      "hook_event_name": "SessionStart",
      "prompt": "<the user's task text>"
    }

**Hook output format** (Claude Code SessionStart):

.. code-block:: json

    {
      "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": "Top-3 skills available for this task ..."
      }
    }

The pull-mode handler does **not** mutate the Q-table or write to
``$SKILLQ_CALLS_LOG`` — those remain exclusive to the PreToolUse
branch, which fires only on actual ``Skill(...)`` calls.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from typing import Any, Sequence


# ---------------------------------------------------------------------------
# Tunables — read from env (set by host bridge at trial start)
# ---------------------------------------------------------------------------
TOP_K = int(os.environ.get("SKILLQ_HOOK_TOP_K", "3"))
LAMBDA = float(os.environ.get("SKILLQ_HOOK_LAMBDA", "0.5"))
C_UCB = float(os.environ.get("SKILLQ_HOOK_C_UCB", "0.5"))
EMBED_TIMEOUT_SEC = float(os.environ.get("SKILLQ_HOOK_EMBED_TIMEOUT_SEC", "5.0"))
# Pull-mode: Top-K for SessionStart injected additionalContext. Falls back
# to SKILLQ_HOOK_TOP_K when unset so old configs work unchanged.
PULL_TOP_K = int(os.environ.get("SKILLQ_PULL_TOP_K", os.environ.get("SKILLQ_HOOK_TOP_K", "3")))

# 2026-06-24: Scoring mode + multiplicative params + Hard Gate.
# These map 1:1 to MethodConfig fields. Defaults MUST match
# MethodConfig defaults exactly (the latter is set in
# config.py:124) — if they ever disagree, the container-side
# hook silently runs a different formula than the host-side
# bridge (e.g. hook scoring with additive while bridge Q-updates
# assume multiplicative ranks). 2026-06-25 changed the fallback
# from "additive" to "multiplicative" to align with
# MethodConfig's default; an in-container default of "additive"
# is a footgun.
SCORE_MODE = os.environ.get("SKILLQ_HOOK_SCORE_MODE", "multiplicative")
MULT_BETA = float(os.environ.get("SKILLQ_HOOK_MULT_BETA", "0.5"))
MULT_GAMMA = float(os.environ.get("SKILLQ_HOOK_MULT_GAMMA", "0.2"))
Q_CLIP_MIN = float(os.environ.get("SKILLQ_HOOK_Q_CLIP_MIN", "0.0"))
Q_CLIP_MAX = float(os.environ.get("SKILLQ_HOOK_Q_CLIP_MAX", "1.0"))
SIM_GATE_MIN_SCORE = float(os.environ.get("SKILLQ_SIM_GATE_MIN_SCORE", "0.7"))
SIM_GATE_FLOOR = int(os.environ.get("SKILLQ_SIM_GATE_FLOOR", "0"))


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _append_jsonl(path: str, record: dict[str, Any]) -> None:
    """Append a single JSON record to a JSONL file. Best-effort."""
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        # Never fail the hook on log write errors.
        pass


def _post_embed(host: str, port: int, text: str) -> list[float] | None:
    """Call the host embedding service. Returns None on any failure.

    Failures are silently absorbed — the hook is fail-open.
    """
    try:
        import requests
    except ImportError:
        return None
    try:
        r = requests.post(
            f"http://{host}:{port}/embed",
            json={"text": text},
            timeout=EMBED_TIMEOUT_SEC,
        )
        r.raise_for_status()
        return r.json()["vec"]
    except Exception as exc:  # noqa: BLE001
        # DEBUG: surface the actual failure mode. Without this,
        # the hook silently returns None and the calls_log
        # shows "embedding unavailable" with no indication of
        # why. The previous calls_log trial sequence showed
        # top-3 with identical scores (0.4163 = UCB only)
        # because _post_embed was returning None — the embed
        # endpoint is correct, the response shape is correct,
        # the request body is correct; the failure is
        # somewhere in the request itself (host unreachable
        # from container? timeout? HTTP error from the
        # service?). This stderr should make the next failure
        # visible without another round of manual debugging.
        sys.stderr.write(
            f"[skillq-hook] _post_embed failed: {type(exc).__name__}: {exc!r} "
            f"(url=http://{host}:{port}/embed)\n"
        )
        sys.stderr.flush()
        return None


# ---------------------------------------------------------------------------
# Eq. 4 scoring (global-Q variant)
# ---------------------------------------------------------------------------
def _zscore(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    n = len(values)
    mu = sum(values) / n
    var = sum((v - mu) ** 2 for v in values) / n
    sd = math.sqrt(var) + 1e-9
    return [(v - mu) / sd for v in values]


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    # 2026-06-25: tolerate numpy arrays (the emb cache stores float32
    # vectors); `not a` raises on ndarray. Use len-based check.
    if len(a) == 0 or len(b) == 0:
        return 0.0
    na = math.sqrt(sum(x * x for x in a)) + 1e-9
    nb = math.sqrt(sum(x * x for x in b)) + 1e-9
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n)) / (na * nb)


def _score_skills(
    *,
    subtask_emb: list[float] | None,
    skills: list[dict[str, Any]],
    q_table: dict[str, float],
    emb_cache: dict[str, list[float]],
    lambda_: float,
    c_ucb: float,
    top_k: int,
    # 2026-06-24: Hard Gate (Fix 1) — drop low-sim candidates before
    # scoring. sim_gate_threshold is the high-water threshold (≥ this
    # passes the gate). Backward-compat: caller passes the same value as
    # sim_gate_min_score from MethodConfig.
    sim_gate_threshold: float = 0.0,
    sim_gate_floor: int = 1,
    sim_gate_min_score: float = 0.05,
    # 2026-06-24: Multiplicative scoring (Fix 2) — switch formula.
    score_mode: str = "additive",
    mult_beta: float = 0.5,
    mult_gamma: float = 0.2,
    q_clip_min: float = 0.0,
    q_clip_max: float = 1.0,
) -> list[tuple[str, float]]:
    """Return top-k (skill_id, score).

    Two scoring formulas (controlled by ``score_mode``):

    - ``"additive"`` (legacy Eq.4):
          score = (1-λ)·sim_z + λ·q_z + c_ucb·√(log N/(n+1))
      sim_z / q_z are z-scored within the (post-gate) batch. After
      z-scoring, a low-sim skill can still rank high if its Q is above
      mean — irrelevant skills occasionally reach Top-K.

    - ``"multiplicative"`` (2026-06-24, Fix 2):
          score = sim·(1 + β·Q_norm) + γ·UCB
      using RAW (non-z-scored) cosine. Critical property: when sim=0
      the entire sim term vanishes and the skill can only rank by its
      UCB exploration bonus — Q cannot promote an irrelevant skill.

    Hard Gate (Fix 1): if ``sim_gate_threshold > 0``, candidates with
    raw cosine < ``sim_gate_min_score`` are dropped before any
    z-scoring or formula application. ``sim_gate_floor`` is the minimum
    number of survivors — if the gate would leave fewer, the top-N by
    raw sim are retained (so Top-K is never empty on early trials with
    poor embedding coverage).

    If ``subtask_emb`` is None (embedding failed), falls back to
    global-Q + UCB only (no sim term) — same as legacy.
    """
    # 1. Raw sim per candidate (Fail-open: missing emb → sim=0)
    sims: list[float] = []
    for s in skills:
        sid = s["skill_id"]
        cached = emb_cache.get(sid)
        if subtask_emb is not None and cached is not None:
            sims.append(_cosine(subtask_emb, cached))
        else:
            sims.append(0.0)

    # 2. Hard Gate — drop low-sim candidates (Fix 1)
    #
    # 2026-06-25: previous "fall through with full list when gated<floor"
    # behavior was too permissive — it let irrelevant skills reach the
    # agent's context and the Q-table's n_retrievals++ counter, polluting
    # both. New behavior: if gated has at least sim_gate_floor candidates,
    # use gated. Otherwise, keep EXACTLY the top-(sim_gate_floor) by raw
    # sim (descending). When sim_gate_floor=0 and gated is empty, the
    # kept-list is empty — strict mode (the new default).
    if sim_gate_threshold > 0.0 and skills:
        gated = [(s, sim) for s, sim in zip(skills, sims) if sim >= sim_gate_min_score]
        if len(gated) >= sim_gate_floor:
            skills = [s for s, _ in gated]
            sims = [sim for _, sim in gated]
        else:
            # Not enough survivors — keep top-(sim_gate_floor) by raw sim.
            # floor=0 → kept=[] (strict mode).
            # floor=1 → kept=[best-by-sim].
            sorted_by_sim = sorted(
                zip(skills, sims), key=lambda pair: -pair[1]
            )
            kept = sorted_by_sim[: max(sim_gate_floor, 0)]
            if kept:
                skills = [s for s, _ in kept]
                sims = [sim for _, sim in kept]
            else:
                skills = []
                sims = []

    # 3. Q-values per candidate (needed for both modes)
    qs = [q_table.get(s["skill_id"], 0.0) for s in skills]

    # 4. UCB term (used by both modes)
    n_total = max(int(sum(s.get("n_retrievals", 0) for s in skills)), 1) + 1

    scored: list[tuple[str, float]] = []

    if score_mode == "multiplicative":
        # Fix 2: sim·(1 + β·Q_norm) + γ·UCB
        # Normalize Q to [0, 1] for stable β scaling
        q_range = max(q_clip_max - q_clip_min, 1e-6)
        for s, sim, q in zip(skills, sims, qs):
            sid = s["skill_id"]
            q_clamped = max(q_clip_min, min(q_clip_max, q))
            q_norm = (q_clamped - q_clip_min) / q_range
            n = int(s.get("n_retrievals", 0)) + 1
            ucb = c_ucb * math.sqrt(math.log(max(n_total, 2)) / n)
            score = sim * (1.0 + mult_beta * q_norm) + mult_gamma * ucb
            scored.append((sid, float(score)))
    else:
        # Legacy Eq.4: (1-λ)·sim_z + λ·q_z + c_ucb·√(log N/(n+1))
        sims_z = _zscore(sims) if len(sims) > 1 else [0.0] * len(sims)
        qs_z = _zscore(qs) if len(qs) > 1 else [0.0] * len(qs)
        for s, sim_z, q_z in zip(skills, sims_z, qs_z):
            sid = s["skill_id"]
            n = int(s.get("n_retrievals", 0)) + 1
            ucb = c_ucb * math.sqrt(math.log(max(n_total, 2)) / n)
            score = (1.0 - lambda_) * sim_z + lambda_ * q_z + ucb
            scored.append((sid, float(score)))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Transcript reader — last 2-3 assistant messages
# ---------------------------------------------------------------------------
def _read_recent_assistant_messages(
    transcript_path: str | None, k: int = 3
) -> list[str]:
    """Read the last ``k`` assistant messages from the Claude Code session
    transcript (a JSONL file). Best-effort — returns [] on any failure.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return []
    out: list[str] = []
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            # We want the last k assistant messages; for efficiency read
            # backwards. JSONL is append-only so we can't seek backwards
            # cheaply, but for the typical case (a few hundred lines) the
            # full read is fine.
            lines = f.readlines()
        for line in reversed(lines):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message", {})
            content = msg.get("content", "")
            if isinstance(content, list):
                # content is a list of blocks; pick the first text block
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        content = block.get("text", "")
                        break
            if isinstance(content, str) and content.strip():
                out.append(content.strip()[:1000])
                if len(out) >= k:
                    break
    except Exception:  # noqa: BLE001
        return out
    return list(reversed(out))  # chronological order


def _build_subtask_text(
    *,
    tool_input: dict[str, Any],
    recent_assistant: list[str],
    user_task_hint: str | None = None,
) -> str:
    """Concatenate the hint + recent assistant messages + requested skill."""
    parts: list[str] = []
    if user_task_hint:
        parts.append(user_task_hint)
    parts.extend(recent_assistant)
    parts.append(f"Trying skill: {tool_input.get('skill', '?')}")
    return " || ".join(parts)[:4000]


# ---------------------------------------------------------------------------
# Hook decision
# ---------------------------------------------------------------------------
def _make_allow() -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }


def _make_deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _format_top_k(top_k: list[tuple[str, float]]) -> str:
    """Format the deny-reason text the agent sees after a blocked Skill() call.

    Two cases:
      1. ``top_k`` non-empty — list the gated+scored candidates so the
         agent can re-call with one of them. The agent still chooses
         to call or skip; we don't force either.
      2. ``top_k`` empty (sim_gate_floor=0 + all sim<threshold) —
         emit an explicit "no relevant skills" message. This is the
         strict-gate design (2026-06-25): if every candidate is below
         ``sim_gate_min_score`` AND there's no floor to keep fallbacks,
         we DO NOT hand the agent an irrelevant list. Irrelevant
         skills would otherwise pollute both the agent's context
         ("maybe I should try one of these?") and the Q-table's
         per-trial UCB update (n_retrievals++ for skills that should
         never have been retrieved). Tell the agent to solve directly.
    """
    if not top_k:
        return (
            "No skills in the library are relevant to this sub-task "
            "(every candidate is below the sim=0.7 similarity gate). "
            "Skip the Skill() call and solve this directly."
        )
    lines = [f"Top-{len(top_k)} relevant skills (re-rank by Eq. 4 global-Q):"]
    for i, (sid, score) in enumerate(top_k, 1):
        lines.append(f"  {i}. {sid}   score={score:+.3f}")
    lines.append("")
    lines.append("Re-call Skill with one of these, or skip if none fit.")
    return "\n".join(lines)


def _format_pull_context(top_k: list[tuple[str, float]],
                         skills: list[dict[str, Any]]) -> str:
    """Compact reminder text injected via SessionStart additionalContext.

    Shows skill_id (used by the Skill tool) and description (truncated to
    120 chars). Body is intentionally excluded — at full lib size 1000
    bodies would blow the agent's context budget.

    2026-06-25 (strict Hard Gate): when ``top_k`` is empty (no skill
    above the sim gate), we DO NOT emit a confusing "Top-0 skills"
    list. Instead the agent gets an explicit "no relevant skills"
    message so it doesn't burn turns trying to invoke Skill() with
    nothing useful to choose from.
    """
    if not top_k:
        return (
            "No skills in the library are relevant to this task "
            "(every candidate is below the sim=0.7 similarity gate). "
            "Don't invoke the Skill tool for this turn — solve directly."
        )
    by_id = {s["skill_id"]: s for s in skills}
    lines = [
        f"Top-{len(top_k)} skills available for this task "
        "(invoke via the Skill tool, e.g. Skill(skill=\"<id>\")):"
    ]
    for i, (sid, score) in enumerate(top_k, 1):
        sk = by_id.get(sid, {})
        desc = (sk.get("description") or "").replace("\n", " ").strip()
        if len(desc) > 120:
            desc = desc[:117] + "..."
        lines.append(f"  {i}. {sid}   score={score:+.3f}")
        if desc:
            lines.append(f"     {desc}")
    return "\n".join(lines)


def _make_session_start_context(text: str) -> dict[str, Any]:
    """Build the hookSpecificOutput.additionalContext payload for
    UserPromptSubmit (the event actually fired; the function name is a
    historical holdover from the SessionStart exploration).

    Claude Code merges `additionalContext` into the agent's context for
    the turn. The hook script reads no permissionDecision here — this is
    pure context injection, not allow/deny.
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": text,
        }
    }


# ---------------------------------------------------------------------------
# UserPromptSubmit (pull-mode) handler
# ---------------------------------------------------------------------------
def _handle_session_start(payload: dict[str, Any]) -> int:
    """Pull-mode: embed user prompt, score Top-K, emit additionalContext.

    Fires on every user prompt submission (per turn). Does NOT mutate
    the Q-table or write to calls_log — those remain exclusive to the
    PreToolUse branch when the agent actually calls Skill.

    Fail-open: any error → return 0 with empty stdout.
    """
    prompt_text = payload.get("prompt", "") or ""
    if not prompt_text.strip():
        return 0  # nothing to rank against

    lib_path = os.environ.get("SKILLQ_LIB", "")
    q_path = os.environ.get("SKILLQ_Q_TABLE", "")
    emb_path = os.environ.get("SKILLQ_EMB_CACHE", "")
    embed_host = os.environ.get("SKILLQ_EMBED_HOST", "host.docker.internal")
    embed_port = int(os.environ.get("SKILLQ_EMBED_PORT", "8765"))

    try:
        lib = _read_json(lib_path) if lib_path else {"skills": []}
        q_table = _read_json(q_path) if q_path else {}
        emb_cache = _read_json(emb_path) if emb_path else {"embeddings": {}}
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"[skillq-hook] session-start read failure: {exc!r}\n")
        sys.stderr.flush()
        return 0  # pass through

    skills = lib.get("skills", [])
    if not skills:
        return 0  # empty lib → no reminder needed
    emb_cache = emb_cache.get("embeddings", emb_cache)

    subtask_emb = _post_embed(embed_host, embed_port, prompt_text[:4000])

    top_k = _score_skills(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table=q_table,
        emb_cache=emb_cache,
        lambda_=LAMBDA,
        c_ucb=C_UCB,
        top_k=PULL_TOP_K,
        # 2026-06-24: Hard Gate + scoring mode + multiplicative params
        sim_gate_threshold=SIM_GATE_MIN_SCORE,
        sim_gate_floor=SIM_GATE_FLOOR,
        sim_gate_min_score=SIM_GATE_MIN_SCORE,
        score_mode=SCORE_MODE,
        mult_beta=MULT_BETA,
        mult_gamma=MULT_GAMMA,
        q_clip_min=Q_CLIP_MIN,
        q_clip_max=Q_CLIP_MAX,
    )

    text = _format_pull_context(top_k, skills)
    if subtask_emb is None:
        text += "\n\n(embedding unavailable; ranking used Q + UCB only.)"

    decision = _make_session_start_context(text)
    sys.stdout.write(json.dumps(decision, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


# ---------------------------------------------------------------------------
# PreToolUse handler (factored out of main() on 2026-06-23 for dispatch)
# ---------------------------------------------------------------------------
def _handle_pretooluse_skill(payload: dict[str, Any]) -> int:
    """Original allow/deny gate on actual Skill tool calls.

    Body is identical to the pre-refactor main() flow:
    1. Read lib / q_table / emb_cache.
    2. Embed the sub-task intent (recent assistant messages + tool input).
    3. Score Eq.4 top-k.
    4. Allow if requested ∈ top-k, else deny with the top-k text.
    5. Append to calls_log for offline analysis.
    """
    tool_input = payload.get("tool_input", {}) or {}
    requested = tool_input.get("skill", "")

    # Read pre-dumped data from env paths
    lib_path = os.environ.get("SKILLQ_LIB", "")
    q_path = os.environ.get("SKILLQ_Q_TABLE", "")
    emb_path = os.environ.get("SKILLQ_EMB_CACHE", "")
    calls_log_path = os.environ.get("SKILLQ_CALLS_LOG", "")
    embed_host = os.environ.get("SKILLQ_EMBED_HOST", "host.docker.internal")
    embed_port = int(os.environ.get("SKILLQ_EMBED_PORT", "8765"))
    transcript_path = payload.get("transcript_path") or os.environ.get(
        "SKILLQ_TRANSCRIPT"
    )
    user_task_hint = os.environ.get("SKILLQ_USER_TASK")  # optional; set by trial

    # Read all data — fall back to allow on any structural failure
    try:
        lib = _read_json(lib_path) if lib_path else {"skills": []}
        q_table = _read_json(q_path) if q_path else {}
        emb_cache = _read_json(emb_path) if emb_path else {"embeddings": {}}
    except Exception as exc:  # noqa: BLE001
        # DEBUG: log to stderr so we can see why the hook is bailing
        sys.stderr.write(
            f"[skillq-hook] early-return on read failure: {exc!r}\n"
        )
        sys.stderr.write(
            f"[skillq-hook]   lib_path={lib_path!r} q_path={q_path!r} "
            f"emb_path={emb_path!r}\n"
        )
        sys.stderr.flush()
        return 0  # pass through

    skills = lib.get("skills", [])
    if not skills:
        # Empty lib → nothing to rank → pass through
        return 0
    emb_cache = emb_cache.get("embeddings", emb_cache)  # tolerate flat dict

    # DEBUG
    import json as _json
    sys.stderr.write(
        f"[skillq-hook] lib={len(skills)} skills, emb_cache={len(emb_cache)} embeddings\n"
    )
    sys.stderr.write(
        f"[skillq-hook] requested={requested!r}, requested_in_emb={requested in emb_cache}\n"
    )
    if skills:
        first_sid = skills[0]['skill_id']
        sys.stderr.write(
            f"[skillq-hook] first_sid={first_sid!r}, first_sid_in_emb={first_sid in emb_cache}\n"
        )
    sys.stderr.flush()

    # Embed the sub-task intent
    recent = _read_recent_assistant_messages(transcript_path, k=3)
    intent_text = _build_subtask_text(
        tool_input=tool_input,
        recent_assistant=recent,
        user_task_hint=user_task_hint,
    )
    t0 = time.monotonic()
    subtask_emb = _post_embed(embed_host, embed_port, intent_text)
    embed_ms = int((time.monotonic() - t0) * 1000)

    # Score
    top_k = _score_skills(
        subtask_emb=subtask_emb,
        skills=skills,
        q_table=q_table,
        emb_cache=emb_cache,
        lambda_=LAMBDA,
        c_ucb=C_UCB,
        top_k=TOP_K,
        # 2026-06-24: Hard Gate + scoring mode + multiplicative params
        sim_gate_threshold=SIM_GATE_MIN_SCORE,
        sim_gate_floor=SIM_GATE_FLOOR,
        sim_gate_min_score=SIM_GATE_MIN_SCORE,
        score_mode=SCORE_MODE,
        mult_beta=MULT_BETA,
        mult_gamma=MULT_GAMMA,
        q_clip_min=Q_CLIP_MIN,
        q_clip_max=Q_CLIP_MAX,
    )

    # Decide
    top_k_ids = {sid for sid, _ in top_k}
    approved = requested in top_k_ids
    if approved:
        decision = _make_allow()
    else:
        reason = _format_top_k(top_k) + (
            "\n\n(embedding unavailable; ranking used Q + UCB only.)"
            if subtask_emb is None
            else ""
        )
        decision = _make_deny(reason)

    # Log
    if calls_log_path:
        # DEBUG: capture a few raw sims so we can verify the
        # hook's cosine computation matches the externally
        # computed one. (The previous calls_log entries had
        # top-3 with identical scores 0.4163, which is the
        # UCB-only signal — i.e., the cosine term was 0 for
        # all skills. We want to confirm whether that's a real
        # failure mode or a stale artifact of an earlier
        # typo that crashed the hook with NameError.)
        raw_sims = []
        for s in skills[:5]:
            sid = s["skill_id"]
            cached = emb_cache.get(sid)
            if subtask_emb is not None and cached is not None:
                raw_sims.append({"skill_id": sid, "sim": _cosine(subtask_emb, cached)})
            else:
                raw_sims.append({"skill_id": sid, "sim": None})
        _append_jsonl(
            calls_log_path,
            {
                "ts": time.time(),
                "requested": requested,
                "top_k": [{"skill_id": sid, "score": score} for sid, score in top_k],
                "approved": approved,
                "embed_ms": embed_ms,
                "intent_text": intent_text[:500],
                "_debug_emb_cache_size": len(emb_cache),
                "_debug_lib_size": len(skills),
                "_debug_first_5_sims": raw_sims,
            },
        )

    sys.stdout.write(json.dumps(decision, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


# ---------------------------------------------------------------------------
# Main — dispatch on hook_event_name (2026-06-23 refactor)
# ---------------------------------------------------------------------------
def main() -> int:
    """Hook entrypoint — read stdin JSON, write stdout JSON, exit code.

    Dispatches by ``hook_event_name``:

    - ``"UserPromptSubmit"`` → ``_handle_session_start`` (pull-mode: inject
      Top-K skills into agent context via additionalContext on every turn).
    - ``"PreToolUse"`` + ``tool_name == "Skill"`` → ``_handle_pretooluse_skill``
      (push-mode: original allow/deny gate, Q-table update, calls_log).
    - anything else → exit 0 (pass through).
    """
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # Hard error → exit 2 (Claude Code will likely log + continue)
        return 2

    event = payload.get("hook_event_name", "")

    # Pull-mode: top-K skills injected on every user prompt.
    if event == "UserPromptSubmit":
        return _handle_session_start(payload)

    # Push-mode: original Skill tool gate.
    if event == "PreToolUse":
        tool_name = payload.get("tool_name", "")
        if tool_name == "Skill":
            return _handle_pretooluse_skill(payload)
        return 0

    # Unknown event (SessionStart, Stop, PostToolUse, Notification, etc.) → pass through.
    return 0


if __name__ == "__main__":
    sys.exit(main())
