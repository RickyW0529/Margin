"""Failure degradation wrapper for Provider calls.

When a primary provider call fails, the wrapper optionally executes a fallback
and reports both outcomes to Prometheus. Degraded results remain inspectable
through the ``from_fallback`` flag on ``CallResult``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from margin.core.metrics import PROVIDER_CALLS, PROVIDER_DEGRADED
from margin.core.provider import CallResult

logger = logging.getLogger(__name__)


def call_with_fallback(
    fn: Callable[..., CallResult],
    fallback: Callable[..., CallResult] | None,
    *,
    trace_id: str,
    metrics_label: str,
    **kwargs: Any,
) -> CallResult:
    """Call ``fn``; on failure execute ``fallback`` and mark result as degraded.

    Args:
        fn: Callable[..., CallResult]: .
        fallback: Callable[..., CallResult] | None: .
        trace_id: str: .
        metrics_label: str: .
        **kwargs: Any: .

    Returns:
        CallResult: .
    """
    try:
        result = fn(**kwargs)
        PROVIDER_CALLS.labels(
            provider=metrics_label,
            method="primary",
            status="success" if result.success else "error",
        ).inc()
        return result
    except Exception as exc:  # noqa: BLE001
        # Primary failed: count the error and, if available, invoke fallback.
        PROVIDER_CALLS.labels(
            provider=metrics_label,
            method="primary",
            status="error",
        ).inc()
        logger.warning(
            "Primary call failed, attempting fallback",
            extra={
                "trace_id": trace_id,
                "metrics_label": metrics_label,
                "error": str(exc),
            },
        )
        if fallback is None:
            # No fallback path: report degraded and return a synthetic failure.
            PROVIDER_DEGRADED.labels(
                provider=metrics_label,
                method="primary",
            ).inc()
            return CallResult(
                provider_name=metrics_label,
                provider_version="",
                success=False,
                error=f"primary failed and no fallback: {exc}",
                from_fallback=False,
            )
        try:
            result = fallback(**kwargs)
            result.from_fallback = True
            PROVIDER_CALLS.labels(
                provider=metrics_label,
                method="fallback",
                status="success" if result.success else "error",
            ).inc()
            PROVIDER_DEGRADED.labels(
                provider=metrics_label,
                method="fallback",
            ).inc()
            return result
        except Exception as fb_exc:  # noqa: BLE001
            # Fallback also failed: count both degraded and return combined error details.
            PROVIDER_CALLS.labels(
                provider=metrics_label,
                method="fallback",
                status="error",
            ).inc()
            PROVIDER_DEGRADED.labels(
                provider=metrics_label,
                method="fallback",
            ).inc()
            return CallResult(
                provider_name=metrics_label,
                provider_version="",
                success=False,
                error=f"primary: {exc}; fallback: {fb_exc}",
                from_fallback=True,
            )
