"""Host-side ranking service — FastAPI daemon that the agent
container's PreToolUse hook calls per Skill invocation.

Step 3 of the 2026-06-26 refactor moved this from
``skillq.services.ranking_service`` (which is now a thin
shim). The new design adds the ``/rank`` endpoint so the L1
scoring algorithm runs in one place — the host — and the
container-side hook just ships an HTTP request.

**Endpoints**:

- ``GET /healthz`` — liveness probe (returns ``{"status":"ok"}``).
  Used by :func:`start_ranking_service_background` to wait for the
  server to bind before the trial starts.
- ``POST /embed`` — backward-compatible with the legacy hook. Takes
  ``{"text": str}`` and returns ``{"vec": [...], "dim": int}``.
  Marked deprecated in the runtime path (Step 5's new
  ``runtime/hook.py`` uses ``/rank``); retained for smoke tests and
  any external tool that embedded against the old contract.
- ``POST /rank`` — the new L1 scoring endpoint. Takes
  ``{"query": str, "top_k": int, "ranking_id": str, "params": {...}}``
  and returns ``{"allowed": bool, "reason": str, "top_k": [...],
  "ranking_id": str, ...}``. Calls
  :func:`skillq.layers.l1_retrieval.scoring.score_skills` against
  the in-memory ``app.state.{lib, emb_cache}`` snapshot, plus the
  global ``app.state.mgr.q_table``.

**Configuration (env-driven)** — same as the legacy embedding
service: ``EMBEDDING_API_KEY`` / ``EMBEDDING_BASE_URL`` /
``EMBEDDING_MODEL`` / ``EMBEDDING_DIM`` / ``EMBEDDING_SERVICE_PORT``
/ ``EMBEDDING_HOST``.

**Lifecycle**:

1. The host's bridge (Step 4's ``runtime/bridge.py``) starts the
   daemon at the start of every trial via
   :func:`start_ranking_service_background` and passes the
   per-trial ``{lib, mgr, emb_cache, method}`` snapshot.
2. The container's hook (Step 5's ``runtime/hook.py``) calls
   ``POST /rank`` once per Skill invocation.
3. The daemon shuts down at trial end (``stop_ranking_service``).

**State injection contract**:

The hook's ``POST /rank`` is *stateless from the daemon's
perspective*: every request reads the current ``app.state.lib``,
``app.state.emb_cache``, and ``app.state.mgr.q_table`` snapshot,
runs Eq. 4 against them, and returns. The hook does NOT mutate any
of these (Q-update happens in the host bridge's on_trial_ended
callback). This means the hook is purely a read-only view into the
host's library state, and the only "race" we need to handle is
trial-end shutdown — which we do by replacing
``app.state.lib`` with an empty ``Qlib()`` before stopping the
daemon.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Annotated, Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("skillq.services.ranking_service")


# ---------------------------------------------------------------------------
# Public type alias — the bridge passes this handle through start → stop
# ---------------------------------------------------------------------------
class RankingServiceHandle(TypedDict):
    """Return type of :func:`start_ranking_service_background`."""

    thread: Any
    server: Any
    port: int
    stop_event: Any


# ---------------------------------------------------------------------------
# Pydantic schemas — module-level so Pydantic can resolve them eagerly.
# Nesting inside ``build_fastapi_app`` would create ForwardRef issues
# with FastAPI 0.110+.
# ---------------------------------------------------------------------------
class EmbedRequest(BaseModel):
    text: str


class EmbedResponse(BaseModel):
    vec: list[float]
    dim: int


class RankParams(BaseModel):
    """Tunable knobs for the L1 scorer. Mirrors ``MethodConfig``'s
    retrieval sub-config + the legacy hook's env vars."""

    model_config = ConfigDict(extra="forbid")

    sim_gate_min_score: float = 0.7
    sim_gate_floor: int = 0
    score_mode: str = "multiplicative"
    beta: float = 0.5
    gamma: float = 0.2
    c_ucb: float = 0.5
    # ``lambda_`` is the additive-mode weight; the request uses
    # ``lambda`` to keep the JSON shape Python-keyword-clean.
    lambda_: float = Field(default=0.5, alias="lambda")
    # 2026-06-29 (Phase 10 Bug 1): q_clip_min / q_clip_max removed.
    # The scorer hard-codes Q clamp [0, 1] internally.


class RankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=3, ge=1, le=50)
    ranking_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    params: RankParams = Field(default_factory=RankParams)


class ScoredSkill(BaseModel):
    skill_id: str
    score: float
    # 2026-06-29 (Phase 10 Bug 2): post-gate L1 sim carried back to
    # the hook so calls_log.jsonl can persist per-skill retrieval
    # similarity. None = sim unavailable (rare: embed unavailable).
    sim: float | None = None
    description: str = ""


class RankResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str
    top_k: list[ScoredSkill] = Field(default_factory=list)
    ranking_id: str
    cache_hit: bool = False
    # 2026-06-29 (Phase 10 Debug-Log): pre-gate top-5 highest-sim
    # candidates for audit (skipped when empty_library, since there
    # are no candidates). Always returned (not gated by SKILLQ_RANK_DEBUG
    # etc.) because calls_log.jsonl is the primary audit surface —
    # we want sim distribution even when the gate drops everyone.
    debug: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Configuration from env
# ---------------------------------------------------------------------------
def get_embedder_config_from_env() -> dict[str, Any]:
    """Read EMBEDDING_* env vars and return a config dict for LiteLLMEmbedder.

    Mirrors the legacy
    :func:`skillq.services.ranking_service.get_embedder_config_from_env`.
    Kept here so the new entry point (``services.ranking_service``)
    has the same env contract without forcing callers through the
    legacy shim.
    """
    model = os.environ.get("EMBEDDING_MODEL", "openai/text-embedding-3-small")
    if "/" not in model:
        model = f"openai/{model}"
    return {
        "model": model,
        "api_key": os.environ.get("EMBEDDING_API_KEY"),
        "base_url": os.environ.get("EMBEDDING_BASE_URL"),
        "dim": int(os.environ.get("EMBEDDING_DIM", "1536")),
    }


def make_embedder_from_env():
    """Build a :class:`LiteLLMEmbedder` from env.

    Raises ``ValueError`` if ``EMBEDDING_API_KEY`` is missing.
    """
    cfg = get_embedder_config_from_env()
    if not cfg["api_key"]:
        raise ValueError(
            "EMBEDDING_API_KEY is not set in the environment. "
            "Add it to .env (e.g. EMBEDDING_API_KEY=sk-...)."
        )

    from skillq.shared.backends.litellm import LiteLLMEmbedder

    kwargs: dict[str, Any] = {"model": cfg["model"], "dim": cfg["dim"]}
    if cfg["base_url"]:
        os.environ.setdefault("OPENAI_BASE_URL", cfg["base_url"])
    return LiteLLMEmbedder(**kwargs)


# ---------------------------------------------------------------------------
# Daemon — FastAPI app
# ---------------------------------------------------------------------------
def build_fastapi_app(
    embedder,
    *,
    lib=None,
    mgr=None,
    emb_cache=None,
    method=None,
):
    """Construct the FastAPI app.

    Parameters
    ----------
    embedder
        A :class:`LiteLLMEmbedder` (or stub) used by ``/embed`` and by
        ``/rank`` to embed the incoming query.
    lib, mgr, emb_cache, method
        Optional initial state. The bridge (Step 4) re-injects the
        per-trial snapshot via :func:`inject_ranking_state` after
        startup; tests typically pass everything up front.

    Imported lazily so the module loads even if FastAPI isn't
    installed.
    """
    from fastapi import Body, FastAPI, HTTPException

    app = FastAPI(title="skillq-ranking-service", version="0.2.0")

    # Schemas are module-level (above) so Pydantic can resolve them
    # eagerly without ForwardRef issues.

    # --- state injection ------------------------------------------
    # ``app.state`` is FastAPI's per-app attribute bag. The bridge
    # writes here at trial start; the request handlers read here.
    # The four fields are independent so a partial injection (e.g.
    # tests that don't care about the Q-table) doesn't break.
    if lib is not None:
        app.state.lib = lib
    if mgr is not None:
        app.state.mgr = mgr
    if emb_cache is not None:
        app.state.emb_cache = emb_cache
    if method is not None:
        app.state.method = method
    app.state.embedder = embedder

    # --- handlers --------------------------------------------------
    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/embed", response_model=EmbedResponse)
    def embed(req: EmbedRequest = Body(...)) -> EmbedResponse:
        if not req.text:
            raise HTTPException(status_code=400, detail="text is empty")
        try:
            arr = app.state.embedder([req.text])
        except Exception as exc:  # noqa: BLE001
            logger.exception("embed call failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        vec = arr[0]
        return EmbedResponse(vec=vec.tolist(), dim=int(vec.shape[0]))

    @app.post("/rank", response_model=RankResponse)
    def rank(req: RankRequest = Body(...)) -> RankResponse:  # noqa: F811
        """Score the query against the in-memory library snapshot.

        Returns ``allowed=True`` only when the requested skill is
        in the top-k AND the top-k is non-empty (i.e., at least one
        skill passed the Hard Gate). Any other case returns
        ``allowed=False`` with a structured ``reason`` so the hook
        can format the deny text without re-running the scorer.
        """
        # Lazy imports keep the module-load-time surface small.
        from skillq.layers.l1_retrieval.scoring import score_skills
        from skillq.shared.types import Qlib

        lib = getattr(app.state, "lib", None) or Qlib()
        mgr = getattr(app.state, "mgr", None)
        emb_cache = getattr(app.state, "emb_cache", None) or {}
        method = getattr(app.state, "method", None)

        if lib.size == 0:
            return RankResponse(
                allowed=False,
                reason="empty_library",
                top_k=[],
                ranking_id=req.ranking_id,
            )

        # Embed the query. Fail-open: any embedder error → ``subtask_emb=None``
        # which the scorer treats as ``sim=0`` for every candidate. The Hard
        # Gate then drops everyone and we return ``reason="embed_unavailable"``.
        try:
            arr = app.state.embedder([req.query])
            subtask_emb = arr[0].tolist()
        except Exception as exc:  # noqa: BLE001
            logger.warning("/rank: embedder failed (%s); fail-open", exc)
            subtask_emb = None

        # Build the candidate list — every skill currently in the lib.
        # The Hard Gate inside the scorer handles the filtering.
        candidates: list[dict[str, Any]] = []
        for sid, skill in lib.skills.items():
            candidates.append({
                "skill_id": sid,
                "description": (skill.body[:200] if skill.body else ""),
                "n_retrievals": skill.n_retrievals,
            })

        # Pull Q-values from the manager (fall back to 0.0 if no mgr).
        q_table: dict[str, float] = {}
        if mgr is not None:
            for sid in lib.skills:
                q_table[sid] = mgr.q_for(sid)

        # Resolve tunables from request params (which override method defaults).
        p = req.params
        # 2026-06-29 (Phase 10 Bug 2): out-param carrying post-gate
        # sims back in top-k order so ScoredSkill.sim is populated.
        sims_out: list[float] = []
        # 2026-06-29 (Phase 10 Debug-Log): also compute pre-gate raw
        # sims so we can log the top-N highest candidates regardless
        # of whether the Hard Gate drops them. This makes "L1 sees
        # 0.05 sims everywhere → no_relevant_skills" distinguishable
        # from "L1 sees 0.65 sims but gate is 0.7" — useful for
        # debugging gate threshold / embedding coverage issues.
        pre_gate_sims: list[float] = []
        for s in candidates:
            cached = emb_cache.get(s["skill_id"])
            if subtask_emb is not None and cached is not None:
                from skillq.layers.l1_retrieval.scoring import cosine
                pre_gate_sims.append(cosine(subtask_emb, cached))
            else:
                pre_gate_sims.append(0.0)
        # Build top-5 pre-gate sim snapshot for debug logging.
        n_debug = min(5, len(candidates))
        pre_gate_top = sorted(
            zip(candidates, pre_gate_sims), key=lambda pair: -pair[1]
        )[:n_debug]
        logger.info(
            "/rank: query=%r lib_size=%d sim_gate_min_score=%.3f "
            "pre_gate_top%d=%s",
            req.query[:80],
            len(candidates),
            p.sim_gate_min_score,
            n_debug,
            [
                (s["skill_id"], round(sim, 4))
                for s, sim in pre_gate_top
            ],
        )

        top_k_pairs = score_skills(
            subtask_emb=subtask_emb,
            skills=candidates,
            q_table=q_table,
            emb_cache=emb_cache,
            lambda_=p.lambda_,
            c_ucb=p.c_ucb,
            top_k=req.top_k,
            sim_gate_threshold=1.0 if p.sim_gate_min_score > 0 else 0.0,
            sim_gate_floor=p.sim_gate_floor,
            sim_gate_min_score=p.sim_gate_min_score,
            score_mode=p.score_mode,
            mult_beta=p.beta,
            mult_gamma=p.gamma,
            sims_out=sims_out,
        )

        # Map (skill_id, score) → ScoredSkill with description + sim.
        by_id = {s["skill_id"]: s for s in candidates}
        scored = [
            ScoredSkill(
                skill_id=sid,
                score=float(score),
                # 2026-06-29 (Phase 10 Bug 2): sim is None when the
                # scorer could not compute it (e.g. embed unavailable);
                # the hook filters None entries out of calls_log.l1_sims.
                sim=sims_out[i] if i < len(sims_out) else None,
                description=by_id.get(sid, {}).get("description", "")[:200],
            )
            for i, (sid, score) in enumerate(top_k_pairs)
        ]

        if not scored:
            # Strict gate: nothing passed. ``reason="no_relevant_skills"``
            # so the hook can format the explicit "no relevant skills"
            # text without trying to deny a non-existent top-k.
            # Still include debug.pre_gate_top5 so the calls_log
            # captures the sim distribution that led to this decision
            # (otherwise the audit trail would show empty top_k with
            # no way to know whether sims were 0.05 (off-topic) or
            # 0.65 (gate too strict)).
            return RankResponse(
                allowed=False,
                reason="no_relevant_skills",
                top_k=[],
                ranking_id=req.ranking_id,
                debug={
                    "pre_gate_top5": [
                        # float() in addition to round() — Pydantic v2
                        # can't serialize numpy.float32 (Bug #1
                        # 2026-06-30: rank endpoint 500 → fail-open)
                        # when sims come from numpy emb-cache vectors.
                        {"skill_id": s["skill_id"], "sim": float(round(sim, 4))}
                        for s, sim in pre_gate_top
                    ],
                },
            )

        logger.info(
            "/rank: returned top_k=%d reason=ok %s",
            len(scored),
            [
                # float() defensively for the logger too — logger
                # would print ``numpy.float32(1.0)`` otherwise (ugly
                # but not fatal; Pydantic 500 only on JSON-serialize
                # paths).
                (s.skill_id, float(round(s.score, 4)),
                 float(round(s.sim or 0.0, 4)))
                for s in scored
            ],
        )
        return RankResponse(
            allowed=True,
            reason="ok",
            top_k=scored,
            ranking_id=req.ranking_id,
            debug={
                "pre_gate_top5": [
                    # Same float()-wrap as the no_relevant_skills
                    # branch above — pre-2026-06-30 this leaked
                    # numpy.float32 and triggered /rank 500.
                    {"skill_id": s["skill_id"], "sim": float(round(sim, 4))}
                    for s, sim in pre_gate_top
                ],
            },
        )

    return app


def inject_ranking_state(
    app,
    *,
    lib=None,
    mgr=None,
    emb_cache=None,
    method=None,
) -> None:
    """Replace the app.state snapshot at trial boundary.

    Called by the bridge (Step 4) after Q-update / lib maintenance
    so the next ``/rank`` request sees the post-update library.
    Cheap: just attribute writes. None means "don't touch this"
    field, so callers can update only what changed.
    """
    if lib is not None:
        app.state.lib = lib
    if mgr is not None:
        app.state.mgr = mgr
    if emb_cache is not None:
        app.state.emb_cache = emb_cache
    if method is not None:
        app.state.method = method


# ---------------------------------------------------------------------------
# Background lifecycle — start/stop the daemon from a non-async caller
# ---------------------------------------------------------------------------
def start_ranking_service_background(
    port: int | None = None,
    host: str | None = None,
    embedder=None,
    *,
    lib=None,
    mgr=None,
    emb_cache=None,
    method=None,
    ready_timeout_sec: float = 5.0,
) -> "RankingServiceHandle":
    """Start the ranking daemon in a daemon thread.

    Returns a handle dict: ``{"thread", "server", "port", "stop_event"}``.
    Use :func:`stop_ranking_service` to shut it down.

    Polls ``GET /healthz`` until the server actually binds
    (uvicorn's bind takes ~50-150ms); on timeout we log a warning
    and return anyway (the hook will fail-open on the first call).
    """
    import requests
    import uvicorn

    port = port or int(os.environ.get("EMBEDDING_SERVICE_PORT", "8765"))
    host = host or os.environ.get("EMBEDDING_HOST", "0.0.0.0")
    if embedder is None:
        embedder = make_embedder_from_env()
    app = build_fastapi_app(
        embedder, lib=lib, mgr=mgr, emb_cache=emb_cache, method=method,
    )

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="warning",
        lifespan="on",
        access_log=False,
    )
    server = uvicorn.Server(config)
    stop_event = threading.Event()

    def _run() -> None:
        server.run()

    thread = threading.Thread(target=_run, name="skillq-ranking-service", daemon=True)
    thread.start()

    logger.info("Started ranking service on %s:%d", host, port)

    deadline = time.monotonic() + ready_timeout_sec
    ready = False
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = requests.get(
                f"http://127.0.0.1:{port}/healthz", timeout=0.5
            )
            if r.status_code == 200:
                ready = True
                break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(0.05)
    if ready:
        logger.info(
            "Ranking service ready on %s:%d (after ready-wait)", host, port
        )
    else:
        logger.warning(
            "Ranking service NOT ready on %s:%d after %.1fs "
            "(last_err=%r); hook will fail-open",
            host, port, ready_timeout_sec, last_err,
        )

    return {"thread": thread, "server": server, "port": port, "stop_event": stop_event}


def stop_ranking_service(handle: dict[str, Any] | None) -> None:
    """Signal the daemon thread to exit. Safe to call with None / twice."""
    if not handle:
        return
    server = handle.get("server")
    stop_event = handle.get("stop_event")
    if stop_event is not None:
        stop_event.set()
    if server is not None:
        try:
            server.should_exit = True
        except Exception:  # noqa: BLE001
            pass
    thread = handle.get("thread")
    if thread is not None and thread.is_alive():
        thread.join(timeout=5.0)


# ---------------------------------------------------------------------------
# Synchronous client — used by tests (and by Step 5's container-side
# hook via the ``ranking_client.sync_rank`` thin wrapper).
# ---------------------------------------------------------------------------
def sync_embed(text: str, host: str = "127.0.0.1", port: int = 8765) -> list[float]:
    """Synchronous embedding call against a running daemon.

    Backward compat with the legacy ``sync_embed``. Prefer
    :func:`skillq.services.ranking_client.sync_rank` for the new
    L1 hook path.
    """
    import requests

    r = requests.post(f"http://{host}:{port}/embed", json={"text": text}, timeout=30)
    r.raise_for_status()
    return r.json()["vec"]


__all__ = [
    "RankingServiceHandle",
    "get_embedder_config_from_env",
    "make_embedder_from_env",
    "build_fastapi_app",
    "inject_ranking_state",
    "start_ranking_service_background",
    "stop_ranking_service",
    "sync_embed",
]