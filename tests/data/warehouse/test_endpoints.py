"""Contracts for provider endpoint registration and sync run models."""

from __future__ import annotations

import pytest

from margin.data.endpoints import (
    DuplicateEndpointError,
    ProviderEndpoint,
    ProviderEndpointRegistry,
)


def test_registry_rejects_duplicate_provider_endpoint() -> None:
    """registry rejects duplicate provider endpoint."""
    registry = ProviderEndpointRegistry()
    endpoint = ProviderEndpoint(code="bars", provider="akshare", domain="market")

    registry.register(endpoint)

    with pytest.raises(DuplicateEndpointError):
        registry.register(endpoint)


def test_backfill_policy_is_not_user_scoped() -> None:
    """backfill policy is not user scoped."""
    endpoint = ProviderEndpoint(code="bars", provider="akshare", domain="market")

    assert endpoint.endpoint_id == "akshare:bars"
    assert "scope_version_id" not in ProviderEndpoint.model_fields


def test_default_registry_contains_akshare_and_tushare_market_endpoints() -> None:
    """default registry contains akshare and tushare market endpoints."""
    registry = ProviderEndpointRegistry.default()

    assert registry.get("akshare", "daily_bar").domain == "market"
    assert registry.get("tushare", "daily_bar").domain == "market"


def test_default_registry_contains_complete_tushare_sync_profile() -> None:
    """Default production sync covers the quant-required Tushare domains."""
    registry = ProviderEndpointRegistry.default()

    assert {endpoint.code for endpoint in registry.list(provider="tushare")} == {
        "security_master",
        "daily_bar",
        "adjustment_factor",
        "financial_statement",
        "valuation",
        "index_member_csi300",
        "index_member_csi500",
    }
