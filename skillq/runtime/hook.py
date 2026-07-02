"""Container-side PreToolUse hook — Step 5 (2026-06-26) refactor.

**This file is read by the agent container at run time.** It must
be self-contained: the container only has Python stdlib (the
SkillsVote prebuilt image ships python3 without ``requests``).
No imports from ``skillq.layers.*`` or ``skillq.runtime.*`` — the
hook contract is **stdlib-only**.

2026-06-29 (Phase 10 Bug 4): ``_call_rank`` was rewritten to use
``urllib.request`` instead of ``requests``. The prebuilt image
lacks ``requests`` and the previous implementation raised
``ModuleNotFoundError`` on every Skill() call in Method B mode,
making the PreToolUse hook a silent fail-open.

**What changed in Step 5 (vs the legacy 547-line
``runtime/hook.py``)**:

- The container-side hook used to **re-implement** Eq. 4 + Hard
  Gate in stdlib Python (because the agent container cannot
  import ``skillq.layers.l1_retrieval.scoring``). Now it just
  POSTs to ``/rank`` on the host's ranking daemon (added in
  Step 3, see :mod:`skillq.services.ranking_service`).
- **No more reads of** ``SKILLQ_LIB`` / ``SKILLQ_Q_TABLE`` /
  ``SKILLQ_EMB_CACHE`` — those are mounted on the **host** only
  and managed by ``MethodServices`` (Step 4). The hook has no
  access to the library or the Q-table; the host is the single
  source of truth.
- **No more Eq. 4 / Hard Gate logic** — the host's
  ``score_skills`` (lifted to :mod:`skillq.layers.l1_retrieval.scoring`
  in Step 2) is the only implementation.
- **bind-mounts from 6 → 2**: hook script + ``settings.json`` +
  skills tree. The 4 bind-mounts for ``lib.json`` /
  ``q_table.json`` / ``emb_cache.json`` / ``settings.json`` (yes,
  we still need ``settings.json`` — Claude Code's hook schema
  requires it on disk) drop to 1 (the ``settings.json``); the
  state files are gone.
- **fail-open preserved**: any non-200 / timeout / network error
  on ``/rank`` → hook returns ``allow`` and writes ``reason``
  to the calls log so users can see what happened.

**Hook protocol** (unchanged):

- ``PreToolUse`` + ``tool_name == "Skill"``: read ``tool_input``,
  POST to ``/rank`` with the request body, write allow/deny to
  stdout, append a line to ``calls_log``.
- ``UserPromptSubmit`` (pull-mode): POST to ``/rank`` with the
  user prompt as query, write ``additionalContext`` to stdout.
  No Q-table mutation, no calls-log entry.
- Anything else: pass through.

2026-07-01 (Bug #51/#52 fix): per-trial state (the agent's task
text + the per-trial calls log path) is read from the
bind-mounted ``/logs/agent/sessions/settings.json``'s ``"skillq"``
block via :func:`_load_skillq_settings`, NOT from env vars. Env
vars raced against Harbor's per-trial ``agent._extra_env``
snapshot under ``n_concurrent_trials >= 2``.

**Container-safe invariants** (asserted at module-load time):

1. ``SKILLQ_RANK_ENDPOINT`` is set (no default; we fail loud).
2. ``SKILLQ_HOOK_TOP_K`` is set (default = 3; hook uses
   ``os.environ.get`` with the default).
3. No imports from any non-stdlib, non-``requests`` module.

The host bridge (:func:`skillq.runtime.env_seed.seed_agent_env`)
injects all 14 ``SKILLQ_*`` vars before :func:`harbor.Job.create`,
so these invariants hold by the time the hook runs.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any


# ---------------------------------------------------------------------------
# Tunables — read at module-load time. Mirror of the host's
# ``MethodConfig.retrieval`` field; the host's ``env_seed.py`` writes
# these before the container's first hook invocation.
# ---------------------------------------------------------------------------
# Module-level assertion: SKILLQ_RANK_ENDPOINT must be present.
# Step 3's /rank contract — hook fails loud if the host didn't
# seed the endpoint. This catches the "env_seed didn't run"
# failure mode loudly instead of letting the hook silently fall
# open on every Skill() call.
RANK_ENDPOINT = os.environ["SKILLQ_RANK_ENDPOINT"]
# Tunables that drive the /rank request body. All have sensible
# defaults matching MethodConfig defaults; the host's env_seed
# overrides them with method-config-derived values.
TOP_K = int(os.environ.get("SKILLQ_HOOK_TOP_K", "3"))
LAMBDA = float(os.environ.get("SKILLQ_HOOK_LAMBDA", "0.5"))
C_UCB = float(os.environ.get("SKILLQ_HOOK_C_UCB", "0.5"))
SCORE_MODE = os.environ.get("SKILLQ_HOOK_SCORE_MODE", "multiplicative")
MULT_BETA = float(os.environ.get("SKILLQ_HOOK_MULT_BETA", "0.5"))
MULT_GAMMA = float(os.environ.get("SKILLQ_HOOK_MULT_GAMMA", "0.2"))
# 2026-06-29 (Phase 10 Bug 1): Q_CLIP_MIN/MAX env vars removed;
# the scorer hard-codes Q clamp to [0, 1] internally. The host's
# env_seed drops these from agent.env so no stale value can leak.
SIM_GATE_MIN_SCORE = float(os.environ.get("SKILLQ_SIM_GATE_MIN_SCORE", "0.7"))
SIM_GATE_FLOOR = int(os.environ.get("SKILLQ_SIM_GATE_FLOOR", "0"))
RANK_TIMEOUT_SEC = float(
    os.environ.get("SKILLQ_HOOK_RANK_TIMEOUT_SEC", "5.0")
)
# Pull-mode (UserPromptSubmit) top-K. Falls back to TOP_K when
# unset so old configs work unchanged.
PULL_TOP_K = int(
    os.environ.get("SKILLQ_PULL_TOP_K", os.environ.get("SKILLQ_HOOK_TOP_K", "3"))
)
# Calls log path + per-trial user_task are now read from the
# bind-mounted ``/logs/agent/sessions/settings.json`` (the
# ``"skillq"`` block) via :func:`_load_skillq_settings`. See
# the module docstring's "2026-07-01 Bug #51/#52 fix" note.
#
# Back-compat shim: keep ``CALLS_LOG_PATH`` as a module-level
# reference to the *initial* env-var value (empty by default) so
# any direct import still gets a string. New code must use
# :func:`_calls_log_path` instead.
CALLS_LOG_PATH = os.environ.get("SKILLQ_CALLS_LOG_PATH", "")
# Pull-mode /rank cache: UserPromptSubmit writes top_k here so
# PreToolUse can skip the redundant second /rank call.
RANK_CACHE_PATH = "/tmp/skillq_rank_cache.json"
RANK_CACHE_TTL_SEC = 300  # 5 minutes — one Skill() call per turn
# Module-level cache so we only read the settings file once per
# hook process (the hook is short-lived: one ProcessPool worker
# per request, so caching per-process is fine and avoids the
# disk round-trip on every Skill() call).
_SETTINGS_CACHE: dict[str, Any] | None = None
# Container path of the bind-mounted settings.json. Set by the
# host's :func:`skillq.runtime.container_wiring._settings_json_path`
# via ``settings.json`` -> /logs/agent/sessions/settings.json.
_SETTINGS_PATH = "/logs/agent/sessions/settings.json"


# ---------------------------------------------------------------------------
# Per-trial settings.json reader (Bug #51/#52 fix)
# ---------------------------------------------------------------------------
def _load_skillq_settings() -> dict[str, Any]:
    """Read the per-trial ``skillq`` block from the bind-mounted settings.json.

    Cached after first successful read — the hook is short-lived
    (one process per Skill() / UserPromptSubmit request) so per-
    process caching is sufficient and avoids a disk round-trip on
    every Skill() call.

    Returns ``{}`` on any read failure (missing file, malformed
    JSON, schema mismatch). Empty dict means "no per-trial state
    available" and the hook falls back to env vars / transcript-
    tail reads.
    """
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None:
        return _SETTINGS_CACHE
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
    except (OSError, json.JSONDecodeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    block = data.get("skillq", {})
    if not isinstance(block, dict):
        block = {}
    _SETTINGS_CACHE = block
    return _SETTINGS_CACHE


def _user_task() -> str:
    """Per-trial task intent (replaces the racy ``SKILLQ_USER_TASK`` env var)."""
    return str(_load_skillq_settings().get("user_task", "") or "")


def _calls_log_path() -> str:
    """Per-trial calls-log path (replaces the racy ``SKILLQ_CALLS_LOG_PATH`` env var)."""
    p = str(_load_skillq_settings().get("calls_log_path", "") or "")
    return p or CALLS_LOG_PATH  # legacy fallback to env var


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def _append_jsonl(path: str, record: dict[str, Any]) -> None:
    """Append a single JSON record to a JSONL file. Best-effort.

    Never raises — a log write failure must not block the hook
    from emitting its allow/deny decision (the contract is
    "always emit a decision before returning").
    """
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def _rank_params() -> dict[str, Any]:
    """Build the 7-tunable payload for ``/rank`` (was 9, dropped q_clip in Phase 10 Bug 1).

    Note: ``lambda_`` is sent under the alias key ``lambda`` to
    keep the JSON shape Python-keyword-clean. Mirrors the
    Pydantic alias in
    :class:`skillq.services.ranking_service.RankParams`.
    """
    return {
        "sim_gate_min_score": SIM_GATE_MIN_SCORE,
        "sim_gate_floor": SIM_GATE_FLOOR,
        "score_mode": SCORE_MODE,
        "beta": MULT_BETA,
        "gamma": MULT_GAMMA,
        "c_ucb": C_UCB,
        "lambda": LAMBDA,
    }


def _call_rank(query: str, top_k: int, *, timeout: float | None = None) -> tuple[int, dict[str, Any] | None, str]:
    """POST ``/rank`` with bounded retries. Returns (status_code, body, reason).

    On success ``body`` is the parsed JSON and ``status_code == 200``.
    On any failure ``body`` is ``None`` and ``reason`` describes the
    failure mode (used by the hook's calls_log entry).

    2026-06-29 (Phase 10 Bug 4): switched from ``requests`` to
    stdlib ``urllib.request``. The SkillsVote prebuilt image only
    ships python3 stdlib (no ``requests``); the previous
    implementation triggered ``ModuleNotFoundError`` on every
    Skill() invocation in Method B mode, causing the hook to
    fail-open with non-blocking errors visible in the trajectory.
    Stdlib ``urllib.request`` is guaranteed to be in the container.
    """
    import urllib.request
    import urllib.error

    url = RANK_ENDPOINT.rstrip("/") + "/rank"
    payload = {
        "query": query[:4000],
        "top_k": int(top_k),
        "ranking_id": uuid.uuid4().hex,
        "params": _rank_params(),
    }
    data = json.dumps(payload).encode("utf-8")
    timeout = timeout if timeout is not None else RANK_TIMEOUT_SEC
    last_err: str = ""
    # 1 retry on transient failure (Docker network-namespace race
    # during the first call after container start). 0.2s backoff
    # matches Step 3's ``post_with_retry(retries=1, backoff_sec=0.2)``.
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                status = resp.getcode() or 0
            if status == 200:
                return 200, json.loads(raw), "ok"
            last_err = f"http {status}"
        except urllib.error.HTTPError as exc:
            last_err = f"http {exc.code}"
        except urllib.error.URLError as exc:
            last_err = f"URLError: {exc.reason}"
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {exc!r}"
        time.sleep(0.2)
    return -1, None, last_err or "unknown"


# ---------------------------------------------------------------------------
# Allow/deny decision builders
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


def _make_session_start_context(text: str) -> dict[str, Any]:
    """Build the ``additionalContext`` payload for UserPromptSubmit (pull-mode).

    Claude Code merges ``additionalContext`` into the agent's
    turn context. Pure context injection — no allow/deny.
    """
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": text,
        }
    }


# ---------------------------------------------------------------------------
# Format helpers (mirror of layers.l1_retrieval.force_use_text)
# ---------------------------------------------------------------------------
# We duplicate these tiny formatters here (instead of importing
# from layers.l1_retrieval) because the container cannot import
# skillq.* modules. The semantics must match — these strings are
# what the agent reads as the deny reason / pull-context.
_NO_RELEVANT_SKILLS_DENY = (
    "No skills in the library are above the relevance threshold for this task. "
    "The Skill() tool is unavailable for this turn. Continue without "
    "invoking Skill()."
)

_NO_RELEVANT_SKILLS_PULL = (
    "No skills in the library are above the relevance threshold for this task."
)


def _format_top_k(top_k: list[dict[str, Any]]) -> str:
    """Format the top-k list into the deny-reason text.

    Each ``top_k`` entry is ``{"skill_id": str, "score": float, "description": str}``.
    """
    if not top_k:
        return _NO_RELEVANT_SKILLS_DENY
    lines = [
        "The following skills are available for this task "
        "(you MUST call Skill() with one of these):"
    ]
    for entry in top_k[:TOP_K]:
        sid = entry.get("skill_id", "?")
        score = entry.get("score", 0.0)
        desc = entry.get("description", "")[:200]
        if desc:
            lines.append(f"  - {sid} (score={score:.3f}): {desc}")
        else:
            lines.append(f"  - {sid} (score={score:.3f})")
    return "\n".join(lines)


def _format_pull_context(top_k: list[dict[str, Any]]) -> str:
    """Format the top-k list into the pull-mode context text."""
    if not top_k:
        return _NO_RELEVANT_SKILLS_PULL
    lines = ["Top skills available for this task:"]
    for entry in top_k[:PULL_TOP_K]:
        sid = entry.get("skill_id", "?")
        score = entry.get("score", 0.0)
        desc = entry.get("description", "")[:200]
        if desc:
            lines.append(f"  - {sid} (score={score:.3f}): {desc}")
        else:
            lines.append(f"  - {sid} (score={score:.3f})")
    lines.append(
        "\nYou MUST call Skill() with one of the above skills: "
        'Skill(skill="<skill_id>")'
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# UserPromptSubmit (pull-mode) handler
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Pull-mode /rank cache (PreToolUse reuse)
# ---------------------------------------------------------------------------
def _write_rank_cache(
    top_k: list[dict[str, Any]],
    l1_sims: dict[str, float | None],
) -> None:
    """Persist the UserPromptSubmit /rank result so PreToolUse can reuse it."""
    try:
        with open(RANK_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "ts": time.time(),
                    "top_k": [
                        {
                            "skill_id": e.get("skill_id"),
                            "score": e.get("score"),
                            "sim": e.get("sim"),
                            "description": e.get("description", "")[:200],
                        }
                        for e in top_k
                    ],
                    "l1_sims": l1_sims,
                },
                f,
                ensure_ascii=False,
            )
    except OSError:
        pass  # best-effort; fallback to /rank on PreToolUse


def _read_rank_cache() -> dict[str, Any] | None:
    """Read the cached /rank result, if fresh enough."""
    try:
        with open(RANK_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.loads(f.read())
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    elapsed = time.time() - data.get("ts", 0)
    if elapsed > RANK_CACHE_TTL_SEC:
        return None
    return data


def _handle_session_start(payload: dict[str, Any]) -> int:
    """Pull-mode: POST user prompt to ``/rank``, emit additionalContext.

    No Q-table mutation, no calls-log entry (those are
    exclusive to the PreToolUse branch when the agent
    actually calls Skill()).

    Fail-open: any error → return 0 with empty stdout.
    """
    prompt_text = payload.get("prompt", "") or ""
    if not prompt_text.strip():
        return 0

    status_code, body, reason = _call_rank(prompt_text, top_k=PULL_TOP_K)
    if status_code != 200 or body is None:
        # Fail-open: skip the reminder if the daemon is unreachable.
        return 0
    top_k = body.get("top_k", [])
    # Cache the /rank result so the subsequent PreToolUse can
    # skip the redundant second /rank call on Skill() invocation.
    l1_sims = {
        entry["skill_id"]: entry.get("sim")
        for entry in top_k
        if entry.get("sim") is not None
    }
    _write_rank_cache(top_k, l1_sims)
    text = _format_pull_context(top_k)
    if body.get("reason") == "embed_unavailable":
        text += "\n\n(embedding unavailable; ranking used Q + UCB only.)"

    sys.stdout.write(json.dumps(_make_session_start_context(text), ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


# ---------------------------------------------------------------------------
# PreToolUse handler (push-mode)
# ---------------------------------------------------------------------------
def _handle_pretooluse_skill(payload: dict[str, Any]) -> int:
    """Push-mode: POST sub-task intent to ``/rank``, allow/deny on result.

    Reads ``tool_input.skill`` to get the requested skill name.
    Builds the query text from the recent assistant messages +
    the user's task hint (via ``SKILLQ_USER_TASK`` env), posts
    to ``/rank``, and decides allow/deny on the response.

    Fail-open: any non-200 from ``/rank`` → allow (the trial can
    still complete; the agent can call Skill() unguarded; we
    just lose the L1 ranking for this Skill() invocation).
    """
    tool_input = payload.get("tool_input", {}) or {}
    requested = tool_input.get("skill", "")
    # 2026-07-01 (Bug #51/#52 fix): per-trial user_task comes from
    # the bind-mounted settings.json's "skillq" block, not from
    # the (racy) env var. Falls back to the env var / transcript
    # tail when the settings file is missing or malformed.
    user_task_hint = _user_task() or os.environ.get("SKILLQ_USER_TASK", "")
    transcript_path = payload.get("transcript_path") or os.environ.get(
        "SKILLQ_TRANSCRIPT"
    )

    # Build the query text. Use the user's task hint if set
    # (host bridge injects it via env_seed); fall back to a
    # transcript-tail read if absent.
    intent_text = user_task_hint.strip() if user_task_hint.strip() else ""
    if not intent_text and transcript_path:
        intent_text = _read_transcript_tail(transcript_path)

    t0 = time.monotonic()

    # Pull-mode shortcut: if UserPromptSubmit already ran /rank
    # for this turn, reuse the cached result instead of calling
    # /rank again. Fall back to a live /rank call when the cache
    # is stale or missing (e.g. hook mode, or first turn).
    cached = _read_rank_cache()
    if cached is not None:
        top_k = cached.get("top_k", [])
        l1_sims = cached.get("l1_sims", {})
        top_k_ids = {entry.get("skill_id") for entry in top_k if entry.get("skill_id")}
        approved = requested in top_k_ids
        _append_jsonl(
            _calls_log_path(),
            {
                "ts": time.time(),
                "requested": requested,
                "top_k": top_k,
                "approved": approved,
                "denied": not approved,
                "rank_ms": int((time.monotonic() - t0) * 1000),
                "rank_reason": "cached",
                "intent_text": (intent_text or "")[:500],
                "l1_sims": l1_sims,
            },
        )
        decision = _make_allow() if approved else _make_deny(
            _format_top_k(top_k)
        )
        sys.stdout.write(json.dumps(decision, ensure_ascii=False))
        sys.stdout.write("\n")
        return 0

    status_code, body, rank_reason = _call_rank(
        intent_text or requested, top_k=TOP_K
    )
    rank_ms = int((time.monotonic() - t0) * 1000)

    if status_code != 200 or body is None:
        # Fail-open allow. Write a debug record so users can see
        # what happened (without aborting the hook).
        _append_jsonl(
            _calls_log_path(),
            {
                "ts": time.time(),
                "requested": requested,
                "top_k": [],
                "approved": True,
                "denied": False,
                "rank_ms": rank_ms,
                "rank_status_code": status_code,
                "rank_reason": rank_reason,
                "intent_text": (intent_text or "")[:500],
                "fail_open": True,
            },
        )
        sys.stdout.write(json.dumps(_make_allow(), ensure_ascii=False))
        sys.stdout.write("\n")
        return 0

    top_k = body.get("top_k", [])
    top_k_ids = {entry.get("skill_id") for entry in top_k}
    approved = requested in top_k_ids

    if approved:
        decision = _make_allow()
    else:
        reason = _format_top_k(top_k)
        if body.get("reason") == "embed_unavailable":
            reason += "\n\n(embedding unavailable; ranking used Q + UCB only.)"
        decision = _make_deny(reason)

    _append_jsonl(
        _calls_log_path(),
        {
            "ts": time.time(),
            "requested": requested,
            "top_k": top_k,
            "approved": approved,
            "denied": not approved,
            "rank_ms": rank_ms,
            "rank_reason": body.get("reason", ""),
            "ranking_id": body.get("ranking_id", ""),
            "intent_text": (intent_text or "")[:500],
            # 2026-06-29 (Phase 10 Bug 2): persist post-gate L1 sims
            # in top-k order. Named ``l1_sims`` to distinguish from
            # ``q_updates.jsonl:cosine_sim`` (post-trial query↔trajectory
            # sim, Eq.5 delta scaling). Both are useful to audit but
            # answer different questions about the same trial.
            "l1_sims": {
                entry["skill_id"]: entry.get("sim")
                for entry in top_k
                if entry.get("sim") is not None
            },
            # 2026-06-29 (Phase 10 Debug-Log): pre-gate top-5 sim
            # snapshot from the host's ranking_service. Survives
            # Hard Gate drops (when top_k=[] + l1_sims={}, this is
            # the only way to see whether L1 saw off-topic queries
            # vs gate-threshold-too-strict).
            "l1_sims_top5_pre_gate": body.get("debug", {}).get(
                "pre_gate_top5", []
            ),
        },
    )

    sys.stdout.write(json.dumps(decision, ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


def _read_transcript_tail(transcript_path: str, k: int = 3) -> str:
    """Read the last ``k`` assistant messages from the transcript.

    Stdlib-only — no imports from skillq.*. Mirrors the logic
    in :mod:`skillq.layers.l1_retrieval.transcript_query` but
    simplified (the container only needs the raw text, not the
    structured payload).
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    try:
        last_msgs: list[str] = []
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("role") == "assistant":
                    content = obj.get("content", "")
                    if isinstance(content, str):
                        last_msgs.append(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                last_msgs.append(block.get("text", ""))
                if len(last_msgs) > k:
                    last_msgs.pop(0)
        return "\n".join(last_msgs)[-2000:]
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Main — dispatch on hook_event_name
# ---------------------------------------------------------------------------
def main() -> int:
    """Hook entrypoint — read stdin JSON, write stdout JSON, exit code.

    Dispatches by ``hook_event_name``:

    - ``"UserPromptSubmit"`` → ``_handle_session_start``
      (pull-mode: inject Top-K skills into agent context).
    - ``"PreToolUse"`` + ``tool_name == "Skill"`` → ``_handle_pretooluse_skill``
      (push-mode: allow/deny gate, calls_log).
    - Anything else → exit 0 (pass through).
    """
    try:
        payload = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        return 2

    event = payload.get("hook_event_name", "")
    if event == "UserPromptSubmit":
        return _handle_session_start(payload)
    if event == "PreToolUse":
        if payload.get("tool_name", "") == "Skill":
            return _handle_pretooluse_skill(payload)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())