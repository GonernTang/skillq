"""Host-side services (Step 3 of the 2026-06-26 refactor).

- :mod:`skillq.services.ranking_service` — FastAPI daemon exposing
  ``/rank`` (the new L1 endpoint) + ``/embed`` (legacy) + ``/healthz``.
- :mod:`skillq.services.ranking_client` — synchronous ``/rank``
  client with bounded retries (used by the container-side hook).
"""

from skillq.services.ranking_service import (  # noqa: F401
    RankingServiceHandle,
    get_embedder_config_from_env,
    make_embedder_from_env,
    build_fastapi_app,
    inject_ranking_state,
    start_ranking_service_background,
    stop_ranking_service,
    sync_embed,
)
from skillq.services.ranking_client import (  # noqa: F401
    DEFAULT_RANK_ENDPOINT,
    get_default_endpoint,
    RankOutcome,
    RankParams,
    sync_rank,
)

__all__ = [
    "RankingServiceHandle",
    "get_embedder_config_from_env",
    "make_embedder_from_env",
    "build_fastapi_app",
    "inject_ranking_state",
    "start_ranking_service_background",
    "stop_ranking_service",
    "sync_embed",
    "DEFAULT_RANK_ENDPOINT",
    "get_default_endpoint",
    "RankOutcome",
    "RankParams",
    "sync_rank",
]