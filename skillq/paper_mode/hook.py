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
    if not a or not b:
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
) -> list[tuple[str, float]]:
    """Return top-k (skill_id, score) by Eq. 4.

    If ``subtask_emb`` is None (embedding failed), falls back to
    global-Q + UCB only (no sim term).
    """
    sims: list[float] = []
    for s in skills:
        sid = s["skill_id"]
        cached = emb_cache.get(sid)
        if subtask_emb is not None and cached is not None:
            sims.append(_cosine(subtask_emb, cached))
        else:
            sims.append(0.0)

    qs = [q_table.get(s["skill_id"], 0.0) for s in skills]
    sims_z = _zscore(sims)
    qs_z = _zscore(qs)

    n_total = max(int(sum(s.get("n_retrievals", 0) for s in skills)), 1) + 1
    scored: list[tuple[str, float]] = []
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
    lines = [f"Top-{len(top_k)} relevant skills (re-rank by Eq. 4 global-Q):"]
    for i, (sid, score) in enumerate(top_k, 1):
        lines.append(f"  {i}. {sid}   score={score:+.3f}")
    lines.append("")
    lines.append("Re-call Skill with one of these, or skip if none fit.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    """Hook entrypoint — read stdin JSON, write stdout JSON, exit code."""
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        # Hard error → exit 2 (Claude Code will likely log + continue)
        return 2

    tool_name = payload.get("tool_name", "")
    if tool_name != "Skill":
        # We only act on Skill; pass through everything else.
        return 0

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


if __name__ == "__main__":
    sys.exit(main())
