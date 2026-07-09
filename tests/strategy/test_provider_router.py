"""Provider category URL routing tests."""

from __future__ import annotations

from margin.strategy.provider_router import (
    detect_provider_from_url,
    provider_category_for_config,
)


def test_llm_router_detects_deepseek_from_url() -> None:
    """DeepSeek URLs should be reflected as the DeepSeek LLM label.

    Returns:
        None: .
    """
    detected = detect_provider_from_url("llm", "https://api.deepseek.com/v1")

    assert detected.provider_id == "deepseek"
    assert detected.label == "DeepSeek"
    assert detected.is_custom is False


def test_llm_router_detects_modelscope_from_url() -> None:
    """ModelScope OpenAI-compatible URLs should be reflected as ModelScope.

    Returns:
        None: .
    """
    detected = detect_provider_from_url(
        "llm",
        "https://api-inference.modelscope.cn/v1/",
    )

    assert detected.provider_id == "modelscope"
    assert detected.label == "ModelScope"


def test_llm_router_detects_minimax_from_platform_url() -> None:
    """Minimax platform URLs should be reflected as the Minimax LLM label."""
    detected = detect_provider_from_url("llm", "https://platform.minimaxi.com")

    assert detected.provider_id == "minimax"
    assert detected.label == "Minimax"
    assert detected.is_custom is False


def test_llm_router_detects_minimax_from_api_url() -> None:
    """Minimax API URLs should be reflected as the Minimax LLM label."""
    detected = detect_provider_from_url("llm", "https://api.minimaxi.com/v1")

    assert detected.provider_id == "minimax"
    assert detected.label == "Minimax"
    assert detected.is_custom is False


def test_data_source_router_detects_teajoin_tushare_proxy() -> None:
    """Teajoin is the configured Tushare HTTP proxy and should not be Custom."""
    detected = detect_provider_from_url("data_source", "https://teajoin.com")

    assert detected.provider_id == "tushare"
    assert detected.label == "Tushare"
    assert detected.is_custom is False


def test_llm_router_detects_local_ollama_and_vllm_ports() -> None:
    """Local OpenAI-compatible URLs should identify common local providers.

    Returns:
        None: .
    """
    ollama = detect_provider_from_url("llm", "http://localhost:11434/v1")
    vllm = detect_provider_from_url("llm", "http://127.0.0.1:8000/v1")

    assert ollama.provider_id == "ollama"
    assert ollama.label == "Ollama"
    assert vllm.provider_id == "vllm"
    assert vllm.label == "VLLM"


def test_router_falls_back_to_custom_with_user_url() -> None:
    """Unknown URLs should remain usable as Custom within the selected category.

    Returns:
        None: .
    """
    detected = detect_provider_from_url("web_search", "https://search.internal.example")

    assert detected.provider_id == "custom"
    assert detected.label == "Custom"
    assert detected.is_custom is True


def test_provider_category_uses_type_and_config_fallbacks() -> None:
    """Provider categories should normalize old and new config shapes.

    Returns:
        None: .
    """
    assert provider_category_for_config("market_data", "tushare", {}) == "data_source"
    assert (
        provider_category_for_config(
            "websearch",
            "tavily",
            {"provider_category": "web_search"},
        )
        == "web_search"
    )
