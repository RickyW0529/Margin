"""Tests for provider degradation wrapper."""

from __future__ import annotations

from margin.core.degradation import call_with_fallback
from margin.core.provider import CallResult


def test_degradation_returns_fallback_on_failure():
    def failing(**_):
        raise RuntimeError("provider down")

    def fallback(**_):
        return CallResult(provider_name="x", provider_version="1", success=True, data="fallback")

    result = call_with_fallback(failing, fallback, trace_id="t1", metrics_label="x")
    assert result.from_fallback is True
    assert result.data == "fallback"


def test_degradation_returns_primary_when_successful():
    def primary(**_):
        return CallResult(provider_name="x", provider_version="1", success=True, data="primary")

    def fallback(**_):
        return CallResult(provider_name="x", provider_version="1", success=True, data="fallback")

    result = call_with_fallback(primary, fallback, trace_id="t1", metrics_label="x")
    assert result.from_fallback is False
    assert result.data == "primary"


def test_degradation_returns_failure_when_fallback_also_fails():
    def failing(**_):
        raise RuntimeError("provider down")

    def fallback(**_):
        raise RuntimeError("fallback down")

    result = call_with_fallback(failing, fallback, trace_id="t1", metrics_label="x")
    assert result.success is False
    assert result.from_fallback is True
    assert "fallback down" in result.error
