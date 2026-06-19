"""Failure degradation wrapper for Provider calls."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

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
        fn: Primary function to call.
        fallback: Optional fallback function.
        trace_id: Trace identifier for observability.
        metrics_label: Label used for metrics.
        **kwargs: Arguments passed to both functions.

    Returns:
        CallResult with ``from_fallback=True`` if fallback was used.
    """
    try:
        return fn(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Primary call failed, attempting fallback",
            extra={
                "trace_id": trace_id,
                "metrics_label": metrics_label,
                "error": str(exc),
            },
        )
        if fallback is None:
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
            return result
        except Exception as fb_exc:  # noqa: BLE001
            return CallResult(
                provider_name=metrics_label,
                provider_version="",
                success=False,
                error=f"primary: {exc}; fallback: {fb_exc}",
                from_fallback=True,
            )
