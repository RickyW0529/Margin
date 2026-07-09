"""Provider category routing and URL-based provider detection."""

from __future__ import annotations

import re
from dataclasses import dataclass

ProviderCategory = str

_CATEGORY_ALIASES: dict[str, ProviderCategory] = {
    "llm": "llm",
    "ai": "llm",
    "websearch": "web_search",
    "web_search": "web_search",
    "search": "web_search",
    "market_data": "data_source",
    "data": "data_source",
    "data_source": "data_source",
    "embedding": "embedding",
    "vector": "embedding",
    "rerank": "rerank",
}

_PROVIDER_NAME_CATEGORY: dict[str, ProviderCategory] = {
    "llm": "llm",
    "openai": "llm",
    "deepseek": "llm",
    "modelscope": "llm",
    "zhipu": "llm",
    "qwen": "llm",
    "gemini": "llm",
    "anthropic": "llm",
    "openrouter": "llm",
    "ollama": "llm",
    "vllm": "llm",
    "local": "llm",
    "tavily": "web_search",
    "exa": "web_search",
    "serpapi": "web_search",
    "bing": "web_search",
    "tushare": "data_source",
    "akshare": "data_source",
    "embedding": "embedding",
    "jina": "embedding",
    "rerank": "rerank",
    "cohere": "rerank",
}


@dataclass(frozen=True)
class ProviderDetection:
    """Safe URL detection metadata for provider settings UI and runtime routing.."""

    category: ProviderCategory
    provider_id: str
    label: str
    router_rule_id: str
    is_custom: bool


@dataclass(frozen=True)
class _ProviderRule:
    """One regex-based provider detection rule.."""

    provider_id: str
    label: str
    pattern: re.Pattern[str]

    @property
    def rule_id(self) -> str:
        """Return stable rule id.

        Returns:
            str: .
        """
        return f"{self.provider_id}"


_RULES: dict[ProviderCategory, tuple[_ProviderRule, ...]] = {
    "llm": (
        _ProviderRule("deepseek", "DeepSeek", re.compile(r"deepseek\.com", re.I)),
        _ProviderRule(
            "modelscope",
            "ModelScope",
            re.compile(r"api-inference\.modelscope\.cn|modelscope\.cn", re.I),
        ),
        _ProviderRule(
            "zhipu",
            "Zhipu",
            re.compile(r"open\.bigmodel\.cn|bigmodel\.cn", re.I),
        ),
        _ProviderRule(
            "ollama",
            "Ollama",
            re.compile(r"(localhost|127\.0\.0\.1|\[::1\]):11434", re.I),
        ),
        _ProviderRule(
            "vllm",
            "VLLM",
            re.compile(r"(localhost|127\.0\.0\.1|\[::1\]):8000", re.I),
        ),
        _ProviderRule("local", "Local", re.compile(r"localhost|127\.0\.0\.1|\[::1\]", re.I)),
        _ProviderRule("openai", "OpenAI", re.compile(r"api\.openai\.com|openai\.com", re.I)),
        _ProviderRule("openrouter", "OpenRouter", re.compile(r"openrouter\.ai", re.I)),
        _ProviderRule("qwen", "Qwen", re.compile(r"dashscope|aliyuncs\.com", re.I)),
        _ProviderRule("gemini", "Gemini", re.compile(r"generativelanguage\.googleapis\.com", re.I)),
        _ProviderRule("anthropic", "Anthropic", re.compile(r"anthropic\.com", re.I)),
    ),
    "web_search": (
        _ProviderRule("tavily", "Tavily", re.compile(r"tavily\.com", re.I)),
        _ProviderRule("exa", "Exa", re.compile(r"exa\.ai", re.I)),
        _ProviderRule("serpapi", "SerpAPI", re.compile(r"serpapi\.com", re.I)),
        _ProviderRule(
            "bing",
            "Bing",
            re.compile(r"bing\.microsoft\.com|api\.bing\.microsoft", re.I),
        ),
    ),
    "data_source": (
        _ProviderRule("tushare", "Tushare", re.compile(r"tushare", re.I)),
        _ProviderRule("akshare", "AKShare", re.compile(r"akshare", re.I)),
    ),
    "embedding": (
        _ProviderRule(
            "openai_compatible",
            "OpenAI Compatible",
            re.compile(r"openai\.com|/embeddings?", re.I),
        ),
        _ProviderRule("dashscope", "DashScope", re.compile(r"dashscope|aliyuncs\.com", re.I)),
        _ProviderRule("jina", "Jina", re.compile(r"jina\.ai", re.I)),
    ),
    "rerank": (
        _ProviderRule("jina", "Jina", re.compile(r"jina\.ai", re.I)),
        _ProviderRule("cohere", "Cohere", re.compile(r"cohere\.ai", re.I)),
    ),
}

_LABELS_BY_PROVIDER: dict[str, str] = {
    rule.provider_id: rule.label for rules in _RULES.values() for rule in rules
}


def provider_category_for_config(
    provider_type: str,
    provider_name: str,
    non_sensitive_config: dict[str, object] | None,
) -> ProviderCategory:
    """Return the normalized provider category for old and new config shapes.

    Args:
        provider_type: str: .
        provider_name: str: .
        non_sensitive_config: dict[str, object] | None: .

    Returns:
        ProviderCategory: .
    """
    config = non_sensitive_config or {}
    configured = str(config.get("provider_category") or "").strip().lower()
    if configured in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[configured]

    type_key = provider_type.strip().lower()
    if type_key in _CATEGORY_ALIASES:
        return _CATEGORY_ALIASES[type_key]

    name_key = provider_name.strip().lower()
    return _PROVIDER_NAME_CATEGORY.get(name_key, name_key or "custom")


def detect_provider_from_url(
    category: ProviderCategory,
    base_url: str | None,
    *,
    fallback_provider_name: str | None = None,
) -> ProviderDetection:
    """Detect provider metadata from URL, falling back to Custom when unknown.

    Args:
        category: ProviderCategory: .
        base_url: str | None: .
        fallback_provider_name: str | None: .

    Returns:
        ProviderDetection: .
    """
    normalized_category = _CATEGORY_ALIASES.get(category.strip().lower(), category)
    url = (base_url or "").strip()
    for rule in _RULES.get(normalized_category, ()):
        if url and rule.pattern.search(url):
            return ProviderDetection(
                category=normalized_category,
                provider_id=rule.provider_id,
                label=rule.label,
                router_rule_id=f"{normalized_category}.{rule.rule_id}",
                is_custom=False,
            )

    fallback = (fallback_provider_name or "").strip().lower()
    if fallback in _PROVIDER_NAME_CATEGORY:
        return ProviderDetection(
            category=normalized_category,
            provider_id=fallback,
            label=_LABELS_BY_PROVIDER.get(fallback, fallback.title()),
            router_rule_id=f"{normalized_category}.{fallback}",
            is_custom=False,
        )

    return ProviderDetection(
        category=normalized_category,
        provider_id="custom",
        label="Custom",
        router_rule_id=f"{normalized_category}.custom",
        is_custom=True,
    )


def enrich_provider_config_metadata(config: object) -> dict[str, object]:
    """Return non-sensitive router metadata for a ProviderConfigVersion-like object.

    Args:
        config: object: .

    Returns:
        dict[str, object]: .
    """
    non_sensitive_config = dict(getattr(config, "non_sensitive_config", {}) or {})
    category = provider_category_for_config(
        str(getattr(config, "provider_type")),
        str(getattr(config, "provider_name")),
        non_sensitive_config,
    )
    detected = detect_provider_from_url(
        category,
        getattr(config, "base_url", None),
        fallback_provider_name=str(getattr(config, "provider_name")),
    )
    return {
        **non_sensitive_config,
        "provider_category": detected.category,
        "detected_provider": detected.provider_id,
        "detected_label": detected.label,
        "router_rule_id": detected.router_rule_id,
        "is_custom_provider": detected.is_custom,
    }
