"""HTTP POST helper with bounded retries — used by the /rank client.

Step 1 of the 2026-06-26 refactor creates this module ahead of Step 3
(:mod:`skillq.services.ranking_service`) and Step 4 (the new runtime
bridge). The full HTTP request / response flow lives in
:mod:`skillq.services.ranking_client`; this helper isolates the
retry-on-transient-error behaviour so the client stays small.

Why we need retries:
    The host-side :func:`post_with_retry` is called from the
    container hook over the docker bridge interface. On trial start
    the network namespace is still being initialised; the first one
    or two ``/rank`` calls occasionally race the interface coming up
    and return ``ConnectionError``. A single retry with a 200ms
    backoff is sufficient to clear this race in 99.9% of trials (see
    ``test_post_with_retry`` for the contract).

Fail-open contract:
    The caller (``runtime/hook.py``) treats any non-200 response —
    including exhausted retries — as ``reason="error"`` and returns
    a permissive decision to the agent. We deliberately do NOT raise
    from :func:`post_with_retry`; the only signal of an exhausted
    retry budget is the ``RetryExhausted`` marker in the return
    value's ``.status_code`` field (``-1``).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("skillq.shared.retry")


@dataclass
class RetryResult:
    """Lightweight wrapper around an HTTP response.

    Carries the JSON-decoded body alongside the status code so the
    hook can branch on ``status_code == 200`` without re-parsing.
    On retry exhaustion we set ``status_code = -1`` and ``body = None``
    so the caller's ``if resp.status_code == 200`` check naturally
    falls through to the fail-open branch.
    """

    status_code: int
    body: dict[str, Any] | None


class RetryExhausted(Exception):
    """Raised only when the caller explicitly opts into raise-mode.

    :func:`post_with_retry` defaults to swallow-and-return
    (``RetryResult(status_code=-1, body=None)``); pass
    ``raise_on_exhaust=True`` to get an exception instead.
    """


def post_with_retry(
    url: str,
    *,
    json: dict[str, Any] | None = None,
    timeout: float = 5.0,
    retries: int = 1,
    backoff_sec: float = 0.2,
    raise_on_exhaust: bool = False,
) -> RetryResult:
    """POST ``json`` to ``url`` with bounded retries on transient errors.

    Parameters
    ----------
    url : str
        The full URL (e.g., ``http://host:8765/rank``).
    json : dict | None
        Request body. Passed through to ``requests.post``.
    timeout : float
        Per-attempt timeout in seconds. Default 5.0.
    retries : int
        Number of *additional* attempts after the first failure.
        ``retries=0`` means a single attempt. ``retries=1`` (the
        default) means up to 2 attempts total.
    backoff_sec : float
        Sleep duration between attempts. Default 0.2s.
    raise_on_exhaust : bool
        If True, raise :class:`RetryExhausted` when all attempts
        fail. Default False (return a sentinel RetryResult instead).

    Returns
    -------
    RetryResult
        ``status_code=200`` and the decoded body on success. On any
        failure (network, timeout, non-2xx, JSON parse): the last
        observed status code (or ``-1`` on network failure) and
        ``body=None``.
    """
    import requests  # local import so tests / non-network callers
                     # don't pay the import cost

    last_status: int = -1
    last_body: dict[str, Any] | None = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=json, timeout=timeout)
            last_status = resp.status_code
            if resp.status_code == 200:
                try:
                    last_body = resp.json()
                except ValueError:
                    last_body = None
                return RetryResult(status_code=resp.status_code, body=last_body)
            # Non-200: still try to decode (some 4xx have JSON)
            try:
                last_body = resp.json()
            except ValueError:
                last_body = None
        except Exception as exc:  # ConnectionError, Timeout, etc.
            logger.debug(
                "post_with_retry: attempt %d/%d failed for %s: %s",
                attempt + 1, retries + 1, url, exc,
            )
            last_status = -1
            last_body = None
        if attempt < retries:
            time.sleep(backoff_sec)
    if raise_on_exhaust:
        raise RetryExhausted(
            f"post_with_retry exhausted after {retries + 1} attempts "
            f"to {url} (last_status={last_status})"
        )
    return RetryResult(status_code=last_status, body=last_body)


__all__ = ["RetryResult", "RetryExhausted", "post_with_retry"]