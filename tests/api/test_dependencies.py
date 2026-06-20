"""Tests for production dependency construction from MarginSettings."""

from __future__ import annotations

from margin.api.dependencies import (
    build_embedding_provider,
    build_llm_provider,
    build_provider_status_providers,
)
from margin.settings import MarginSettings


def test_build_llm_provider_uses_centralized_settings():
    settings = MarginSettings(
        _env_file=None,
        llm_api_key="test-key",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-v4-flash",
    )

    provider = build_llm_provider(settings)

    assert provider is not None
    assert provider.descriptor.version == "deepseek-v4-flash"
    assert provider.descriptor.config["base_url"] == "https://api.deepseek.com"


def test_build_embedding_provider_uses_centralized_settings():
    settings = MarginSettings(
        _env_file=None,
        embedding_api_key="test-key",
        embedding_base_url="https://open.bigmodel.cn/api/paas/v4",
        embedding_model="embedding-3",
        embedding_dimension=2048,
    )

    provider = build_embedding_provider(settings)

    assert provider is not None
    assert provider.version == "embedding-3"
    assert provider.dim == 2048


def test_provider_factories_fail_closed_when_unconfigured():
    settings = MarginSettings(_env_file=None)

    assert build_llm_provider(settings) is None
    assert build_embedding_provider(settings) is None


def test_provider_factories_fail_closed_for_empty_container_secrets():
    settings = MarginSettings(
        _env_file=None,
        llm_api_key="",
        llm_base_url="https://api.deepseek.com",
        embedding_api_key="",
        embedding_base_url="https://open.bigmodel.cn/api/paas/v4",
    )

    assert build_llm_provider(settings) is None
    assert build_embedding_provider(settings) is None


def test_provider_status_providers_report_missing_optional_external_providers():
    settings = MarginSettings(
        _env_file=None,
        llm_api_key="test-key",
        llm_base_url="https://api.deepseek.com",
        embedding_api_key="embedding-key",
        embedding_base_url="https://open.bigmodel.cn/api/paas/v4",
    )

    providers = build_provider_status_providers(settings)
    names = [provider.descriptor.name for provider in providers]
    statuses = {provider.descriptor.name: provider.healthcheck() for provider in providers}

    assert "openai_llm" in names
    assert "openai_embedding" in names
    assert "tavily_websearch" in names
    assert "http_rerank" in names
    assert statuses["tavily_websearch"].status.value == "degraded"
    assert statuses["http_rerank"].status.value == "degraded"
