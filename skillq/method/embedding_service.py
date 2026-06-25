"""Host-side embedding service — FastAPI daemon that the agent
container's PreToolUse hook calls per Skill invocation.

**Why a daemon (not a per-call subprocess)**: the agent's
``PreToolUse`` hook is synchronous — the agent waits for the hook
to return before the Skill call resolves. A subprocess-per-call
would add ~hundreds of ms of Python startup per hook fire, and a
per-trial trial typically fires 5-20 Skill calls. A long-lived
HTTP server keeps the embedder (LiteLLM client, model connection
pool) warm and serves requests in single-digit ms of overhead.

**Configuration (env-driven)**: keys live in ``.env`` (loaded by
``paper.env.load_env_file`` before the daemon starts):

- ``EMBEDDING_API_KEY``    — required; passed to LiteLLM
- ``EMBEDDING_BASE_URL``   — optional; default OpenAI
- ``EMBEDDING_MODEL``      — default ``text-embedding-3-small``
- ``EMBEDDING_DIM``        — default ``1536`` (small's dim)
- ``EMBEDDING_SERVICE_PORT`` — default ``8765``
- ``EMBEDDING_HOST``       — default ``0.0.0.0``; container calls
  ``host.docker.internal`` (Docker Desktop) or the host's LAN IP

**Lifecycle**:
1. :class:`skillq.skillq_runtime.agent.PaperClaudeCodeAgent` (re-)starts
   the daemon at the start of every trial via
   :func:`start_embedding_service_background`.
2. The hook (container-side, ``skillq/skillq_runtime/hook.py``) calls
   ``POST /embed {text: str} -> {vec: [...]}``.
3. The daemon shuts down at trial end (``stop_embedding_service``).
"""

import logging
import os
import threading
from typing import Annotated, Any

import numpy as np

logger = logging.getLogger("paper.method.embedding_service")


# ---------------------------------------------------------------------------
# Public type alias — the bridge / container_wiring passes this handle
# through start → stop. Defined here so callers don't have to use
# the untyped dict shape.
# ---------------------------------------------------------------------------
from typing import TypedDict  # noqa: E402


class EmbeddingServiceHandle(TypedDict):
    """Return type of :func:`start_embedding_service_background`.

    The dict shape is fixed; the TypedDict makes the API
    self-documenting and IDE-friendly without forcing callers
    through an extra import.
    """

    thread: Any
    server: Any
    port: int
    stop_event: Any


# ---------------------------------------------------------------------------
# Configuration from env
# ---------------------------------------------------------------------------
def get_embedder_config_from_env() -> dict[str, Any]:
    """Read EMBEDDING_* env vars and return a config dict for LiteLLMEmbedder.

    Falls back to defaults that match the existing
    :class:`paper.method.retrieval.LiteLLMEmbedder` defaults.

    Model names without a ``provider/`` prefix are ambiguous to
    litellm (raises "LLM Provider NOT provided"). The smoke config
    stores ``openai/<model>`` in the method yaml's
    ``embedder_model`` field, so by the time the bridge calls
    ``start_embedding_service_background`` the model already has
    the right prefix. When this function reads ``EMBEDDING_MODEL``
    directly (e.g. when the env-only path is used) the prefix is
    missing — we add it here so the fallback path stays
    consistent.
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
    """Build a :class:`paper.method.retrieval.LiteLLMEmbedder` from env.

    Returns a fully-configured embedder. Raises ``ValueError`` if
    ``EMBEDDING_API_KEY`` is missing.
    """
    cfg = get_embedder_config_from_env()
    if not cfg["api_key"]:
        raise ValueError(
            "EMBEDDING_API_KEY is not set in the environment. "
            "Add it to .env (e.g. EMBEDDING_API_KEY=sk-...)."
        )

    from skillq.method.retrieval import LiteLLMEmbedder

    kwargs: dict[str, Any] = {"model": cfg["model"], "dim": cfg["dim"]}
    if cfg["base_url"]:
        # LiteLLM accepts base_url via the model string (openai/<...>) or
        # by setting env var OPENAI_BASE_URL. For non-OpenAI providers
        # the model string is usually enough; for OpenAI-compatible
        # custom endpoints, set the env var.
        os.environ.setdefault("OPENAI_BASE_URL", cfg["base_url"])

    return LiteLLMEmbedder(**kwargs)


# ---------------------------------------------------------------------------
# Daemon — FastAPI app
# ---------------------------------------------------------------------------
def build_fastapi_app(embedder):
    """Construct the FastAPI app around a given embedder.

    Imported lazily so the module loads even if FastAPI isn't
    installed (tests using StubEmbedder don't need it).
    """
    from fastapi import Body, FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(title="mg-embedding-service", version="0.1.0")

    class EmbedRequest(BaseModel):
        text: str

    class EmbedResponse(BaseModel):
        vec: list[float]
        dim: int

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/embed", response_model=EmbedResponse)
    def embed(req: Annotated[EmbedRequest, Body(...)]) -> EmbedResponse:
        # The Body() annotation is required so FastAPI doesn't treat
        # the ``req: EmbedRequest`` Pydantic model as a query
        # parameter (which would 422 with "field 'req' required"
        # because the hook's POST has no ``?req=`` query string).
        # We use ``Annotated[..., Body(...)]`` instead of
        # ``req: EmbedRequest = Body(...)`` because the latter
        # creates a ForwardRef that Pydantic can't resolve in
        # some FastAPI versions. Keep this in sync with
        # :func:`skillq.skillq_runtime.hook._post_embed`.
        if not req.text:
            raise HTTPException(status_code=400, detail="text is empty")
        try:
            arr = embedder([req.text])
        except Exception as exc:  # noqa: BLE001
            logger.exception("embed call failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        vec = arr[0]
        return EmbedResponse(vec=vec.tolist(), dim=int(vec.shape[0]))

    return app


# ---------------------------------------------------------------------------
# Background lifecycle — start/stop the daemon from a non-async caller
# ---------------------------------------------------------------------------
def start_embedding_service_background(
    port: int | None = None,
    host: str | None = None,
    embedder=None,
) -> "EmbeddingServiceHandle":
    """Start the embedding daemon in a daemon thread.

    Returns a handle dict: ``{"thread", "server", "port", "stop_event"}``.
    Use :func:`stop_embedding_service` to shut it down.

    This is what :class:`skillq.skillq_runtime.agent.PaperClaudeCodeAgent`
    calls at trial start. It does NOT block — the agent continues
    to start the Claude Code CLI immediately. The hook fires after
    the agent has started, by which time the server is bound.
    """
    import uvicorn

    port = port or int(os.environ.get("EMBEDDING_SERVICE_PORT", "8765"))
    host = host or os.environ.get("EMBEDDING_HOST", "0.0.0.0")
    if embedder is None:
        embedder = make_embedder_from_env()
    app = build_fastapi_app(embedder)

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

    thread = threading.Thread(target=_run, name="mg-embedding-service", daemon=True)
    thread.start()

    logger.info("Started embedding service on %s:%d", host, port)
    return {"thread": thread, "server": server, "port": port, "stop_event": stop_event}


def stop_embedding_service(handle: dict[str, Any] | None) -> None:
    """Signal the daemon thread to exit. Safe to call with None / twice."""
    if not handle:
        return
    server = handle.get("server")
    stop_event = handle.get("stop_event")
    if stop_event is not None:
        stop_event.set()
    if server is not None:
        # uvicorn.Server.should_exit is the supported stop signal
        try:
            server.should_exit = True
        except Exception:  # noqa: BLE001
            pass
    thread = handle.get("thread")
    if thread is not None and thread.is_alive():
        thread.join(timeout=5.0)


# ---------------------------------------------------------------------------
# Synchronous client — used by the container-side hook (or by tests
# running in the same process). The container's hook can also use
# ``requests.post(...)`` directly; this is just a convenience.
# ---------------------------------------------------------------------------
def sync_embed(text: str, host: str = "127.0.0.1", port: int = 8765) -> list[float]:
    """Synchronous embedding call against a running daemon.

    Used by tests and by the host-side bridge if it needs to embed
    descriptions outside the daemon (e.g., during emb_cache refresh).
    """
    import requests

    r = requests.post(f"http://{host}:{port}/embed", json={"text": text}, timeout=30)
    r.raise_for_status()
    return r.json()["vec"]


__all__ = [
    "get_embedder_config_from_env",
    "make_embedder_from_env",
    "build_fastapi_app",
    "start_embedding_service_background",
    "stop_embedding_service",
    "sync_embed",
]
