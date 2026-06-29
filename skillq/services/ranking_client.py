"""Container-side ``/rank`` client — used by the new runtime hook.

Step 3 of the 2026-06-26 refactor. The container's PreToolUse hook
(Step 5's ``runtime/hook.py``) calls :func:`sync_rank` once per
Skill invocation; this module wraps the ``POST /rank`` HTTP call
with bounded retries (via :mod:`skillq.shared.retry`) so a
transient ``ConnectionError`` during Docker network-namespace
initialisation does not silently break the L1 layer.

Fail-open contract: any non-200 response — including exhausted
retries — is reported via the ``reason`` field on the returned
``RankOutcome``. The hook treats ``reason != "ok"`` as "allow
through and let the agent decide", so the daemon can be down
without taking down the trial.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from skillq.shared.retry import post_with_retry

logger = logging.getLogger("skillq.services.ranking_client")


# Default endpoint when ``SKILLQ_RANK_ENDPOINT`` is unset. The container
# reads ``host.docker.internal`` on Docker Desktop; on Linux with a
# custom bridge the user can set the env var to override.
DEFAULT_RANK_ENDPOINT = "http://host.docker.internal:8765"


def get_default_endpoint() -> str:
    """Resolve the /rank endpoint from env, falling back to docker-internal."""
    return os.environ.get("SKILLQ_RANK_ENDPOINT", DEFAULT_RANK_ENDPOINT)


@dataclass
class RankOutcome:
    """Result of a ``/rank`` call.

    Carries the full JSON body so the hook can format the deny
    reason using whatever fields the response provides
    (currently ``reason`` + ``top_k``).

    On any failure (network, timeout, non-200, JSON parse) we set
    ``status_code = -1`` and ``reason = "error"``. The hook then
    returns the fail-open allow decision.
    """

    status_code: int
    body: dict[str, Any] | None
    endpoint: str


@dataclass
class RankParams:
    """Tunable knobs for the L1 scorer.

    Defaults match the legacy hook's env-var defaults so the new
    /rank path produces bit-exact results with the old inline
    scorer when no override is provided. Each field is exposed
    as a kwarg to :func:`sync_rank`.
    """

    sim_gate_min_score: float = 0.7
    sim_gate_floor: int = 0
    score_mode: str = "multiplicative"
    beta: float = 0.5
    gamma: float = 0.2
    c_ucb: float = 0.5
    lambda_: float = 0.5
    # 2026-06-29 (Phase 10 Bug 1): q_clip_min / q_clip_max removed;
    # the scorer hard-codes Q clamp to [0, 1] internally.

    def to_payload(self) -> dict[str, Any]:
        """Serialise to the JSON shape ``/rank`` expects.

        Note: ``lambda_`` is sent under the alias key ``lambda`` so the
        JSON matches the Pydantic alias used in
        :mod:`skillq.services.ranking_service`.
        """
        return {
            "sim_gate_min_score": self.sim_gate_min_score,
            "sim_gate_floor": self.sim_gate_floor,
            "score_mode": self.score_mode,
            "beta": self.beta,
            "gamma": self.gamma,
            "c_ucb": self.c_ucb,
            "lambda": self.lambda_,
        }


def sync_rank(
    query: str,
    *,
    top_k: int = 3,
    endpoint: str | None = None,
    timeout: float = 5.0,
    params: RankParams | None = None,
    retries: int = 1,
    backoff_sec: float = 0.2,
) -> RankOutcome:
    """POST ``query`` to ``/rank`` with bounded retries.

    Returns a :class:`RankOutcome`. On success the ``body`` field
    is the parsed JSON response (carrying ``allowed``, ``reason``,
    ``top_k``, ``ranking_id``). On any failure ``body`` is ``None``
    and ``status_code`` is ``-1``.
    """
    import uuid

    payload = {
        "query": query[:4000],
        "top_k": int(top_k),
        "ranking_id": uuid.uuid4().hex,
        "params": (params or RankParams()).to_payload(),
    }
    url = (endpoint or get_default_endpoint()).rstrip("/") + "/rank"
    result = post_with_retry(
        url,
        json=payload,
        timeout=timeout,
        retries=retries,
        backoff_sec=backoff_sec,
    )
    return RankOutcome(
        status_code=result.status_code,
        body=result.body,
        endpoint=url,
    )


__all__ = [
    "DEFAULT_RANK_ENDPOINT",
    "get_default_endpoint",
    "RankOutcome",
    "RankParams",
    "sync_rank",
]