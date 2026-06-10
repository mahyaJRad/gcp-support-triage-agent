"""Shared GCP helpers: a configured BigQuery client and a transient-error retry.

Centralizes how every module connects to GCP and applies the same
cost/location guardrails (see docs/adr/0004-cost-and-model-selection.md).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from google.api_core import exceptions as gexc

from support_triage.config import CONFIG

log = logging.getLogger("support_triage")

T = TypeVar("T")

# Errors worth retrying (transient); auth/quota-exhausted/bad-request are not.
_TRANSIENT = (
    gexc.ServiceUnavailable,
    gexc.TooManyRequests,
    gexc.InternalServerError,
    gexc.DeadlineExceeded,
)


def bq_client():
    """Return a BigQuery client bound to the configured project."""
    from google.cloud import bigquery

    return bigquery.Client(project=CONFIG.project_id)


def with_backoff(fn: Callable[..., T], *args, retries: int = 4, base: float = 1.0, **kwargs) -> T:
    """Call ``fn`` with exponential backoff on transient GCP errors.

    Non-transient errors (auth, invalid argument, permission) propagate
    immediately - retrying them only wastes quota.
    """
    for attempt in range(retries):
        try:
            return fn(*args, **kwargs)
        except _TRANSIENT as e:  # noqa: PERF203
            if attempt == retries - 1:
                raise
            wait = base * (2**attempt)
            log.warning(
                "transient error (%s); retry %d/%d in %.1fs",
                type(e).__name__,
                attempt + 1,
                retries,
                wait,
            )
            time.sleep(wait)
    raise RuntimeError("unreachable")  # pragma: no cover
