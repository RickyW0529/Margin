"""Tests for release capability reporting from provider configuration."""

from __future__ import annotations

from margin.bootstrap.features import build_feature_capabilities
from margin.strategy.models import ConfigLifecycle, ProviderConfigVersion


def test_feature_capabilities_report_missing_provider_requirements() -> None:
    """Verify missing provider categories are reported without raising.

    Returns:
        None: .
    """
    statuses = build_feature_capabilities(())

    assert statuses["api"].enabled is True
    assert statuses["valuation_discovery"].enabled is False
    assert "data_source.quant_required_financials" in statuses["valuation_discovery"].missing
    assert "llm" in statuses["agent_runtime"].missing


def test_feature_capabilities_require_active_provider_secrets() -> None:
    """Verify secret-backed providers without secrets are reported as missing.

    Returns:
        None: .
    """
    statuses = build_feature_capabilities(
        (
            ProviderConfigVersion(
                version_id="provider-llm-active",
                provider_name="llm",
                provider_type="llm",
                lifecycle=ConfigLifecycle.ACTIVE,
            ),
        )
    )

    assert statuses["agent_runtime"].enabled is False
    assert "llm.secret" in statuses["agent_runtime"].missing


def test_feature_capabilities_enable_configured_local_stack() -> None:
    """Verify feature capabilities from a minimally configured local stack.

    Returns:
        None: .
    """
    statuses = build_feature_capabilities(
        (
            ProviderConfigVersion(
                version_id="provider-akshare-active",
                provider_name="akshare",
                provider_type="market_data",
                non_sensitive_config={"secret_required": False},
                lifecycle=ConfigLifecycle.ACTIVE,
            ),
            ProviderConfigVersion(
                version_id="provider-tushare-active",
                provider_name="tushare",
                provider_type="market_data",
                secret_version_id="secret-tushare",
                lifecycle=ConfigLifecycle.ACTIVE,
            ),
            ProviderConfigVersion(
                version_id="provider-websearch-active",
                provider_name="tavily",
                provider_type="websearch",
                secret_version_id="secret-tavily",
                lifecycle=ConfigLifecycle.ACTIVE,
            ),
            ProviderConfigVersion(
                version_id="provider-llm-active",
                provider_name="llm",
                provider_type="llm",
                secret_version_id="secret-llm",
                lifecycle=ConfigLifecycle.ACTIVE,
            ),
            ProviderConfigVersion(
                version_id="provider-embedding-active",
                provider_name="embedding",
                provider_type="embedding",
                secret_version_id="secret-embedding",
                lifecycle=ConfigLifecycle.ACTIVE,
            ),
        )
    )

    assert statuses["market_data"].enabled is True
    assert statuses["news"].enabled is True
    assert statuses["agent_runtime"].enabled is True
    assert statuses["valuation_discovery"].enabled is True
