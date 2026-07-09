"""Tests for provider degradation wrapper.

Validates the three failure modes: successful fallback, no fallback needed, and
cascading failure when both primary and fallback raise exceptions.
"""

from __future__ import annotations

from margin.core.degradation import call_with_fallback
from margin.core.provider import CallResult


def test_degradation_returns_fallback_on_failure():
    """Test that degradation returns the fallback result on primary failure.

    Returns:
        Any: .
    """

    def failing(**_):
        """Raise an error simulating a provider outage.

        Args:
            **_: Any: .

        Returns:
            Any: .
        """
        raise RuntimeError("provider down")

    def fallback(**_):
        """Return a successful fallback CallResult.

        Args:
            **_: Any: .

        Returns:
            Any: .
        """
        return CallResult(provider_name="x", provider_version="1", success=True, data="fallback")

    result = call_with_fallback(failing, fallback, trace_id="t1", metrics_label="x")
    assert result.from_fallback is True
    assert result.data == "fallback"


def test_degradation_returns_primary_when_successful():
    """Test that degradation returns the primary result when it succeeds.

    Returns:
        Any: .
    """

    def primary(**_):
        """Return a successful primary CallResult.

        Args:
            **_: Any: .

        Returns:
            Any: .
        """
        return CallResult(provider_name="x", provider_version="1", success=True, data="primary")

    def fallback(**_):
        """Return a successful fallback CallResult.

        Args:
            **_: Any: .

        Returns:
            Any: .
        """
        return CallResult(provider_name="x", provider_version="1", success=True, data="fallback")

    result = call_with_fallback(primary, fallback, trace_id="t1", metrics_label="x")
    assert result.from_fallback is False
    assert result.data == "primary"


def test_degradation_returns_failure_when_fallback_also_fails():
    """Test that degradation returns a failure when both primary and fallback fail.

    Returns:
        Any: .
    """

    def failing(**_):
        """Raise an error simulating a primary provider outage.

        Args:
            **_: Any: .

        Returns:
            Any: .
        """
        raise RuntimeError("provider down")

    def fallback(**_):
        """Raise an error simulating a fallback provider outage.

        Args:
            **_: Any: .

        Returns:
            Any: .
        """
        raise RuntimeError("fallback down")

    result = call_with_fallback(failing, fallback, trace_id="t1", metrics_label="x")
    # Even though both providers failed, the caller receives a single structured
    # failure with context from both the primary and fallback attempts.
    assert result.success is False
    assert result.from_fallback is True
    assert "fallback down" in result.error
