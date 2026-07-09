"""Resolve executable Provider adapters from frozen active configuration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

from margin.core.secret_store import SecretStore, SecretValue
from margin.strategy.models import ProviderConfigVersion
from margin.strategy.provider_router import provider_category_for_config

T = TypeVar("T")

_DEFAULT_PROVIDER_CAPABILITIES: dict[str, frozenset[str]] = {
    "tushare": frozenset(
        {
            "market_quote",
            "financials",
            "daily_basic",
            "index_constituents",
            "suspensions",
            "limit_prices",
            "quant_required_financials",
        }
    ),
    "akshare": frozenset(
        {
            "market_quote",
            "financials",
        }
    ),
}


@dataclass(frozen=True)
class RuntimeBoundProvider(Generic[T]):
    """Executable adapter bound to a frozen Provider config version.."""

    adapter: T
    config_version_id: str


@dataclass(frozen=True)
class ResolvedProviderRuntime:
    """Active non-sensitive config plus an optional masked secret value.."""

    config: ProviderConfigVersion
    secret: SecretValue | None


class ProviderRuntimeResolver:
    """Resolve one executable Provider version for trusted runtime consumers.."""

    def __init__(
        self,
        repository: object,
        secret_store: SecretStore,
        *,
        owner_id: str = "local-admin",
    ) -> None:
        """Initialize the resolver.

        Args:
            repository: object: .
            secret_store: SecretStore: .
            owner_id: str: .

        Returns:
            None: .
        """
        self._repository = repository
        self._secret_store = secret_store
        self._owner_id = owner_id

    def resolve(self, provider_name: str) -> ResolvedProviderRuntime:
        """Return the single active config and its frozen secret version.

        Args:
            provider_name: str: .

        Returns:
            ResolvedProviderRuntime: .
        """
        normalized_name = provider_name.strip().lower()
        matches = [
            config
            for config in self._repository.list_active_provider_configs(self._owner_id)
            if _runtime_provider_name_for_config(config) == normalized_name
        ]
        if not matches:
            raise LookupError(f"active provider config not found: {normalized_name}")
        if len(matches) != 1:
            raise RuntimeError(f"multiple active provider configs found: {normalized_name}")
        return self._resolve_config(matches[0], normalized_name)

    def resolve_category(self, provider_category: str) -> ResolvedProviderRuntime:
        """Return the single active config for a provider category.

        Args:
            provider_category: str: .

        Returns:
            ResolvedProviderRuntime: .
        """
        normalized_category = provider_category.strip().lower()
        matches = [
            config
            for config in self._repository.list_active_provider_configs(self._owner_id)
            if provider_category_for_config(
                config.provider_type,
                config.provider_name,
                config.non_sensitive_config,
            )
            == normalized_category
        ]
        if not matches:
            raise LookupError(f"active provider config not found: {normalized_category}")
        if len(matches) != 1:
            raise RuntimeError(f"multiple active provider configs found: {normalized_category}")
        return self._resolve_config(matches[0], normalized_category)

    def resolve_capability(
        self,
        provider_category: str,
        capability: str,
    ) -> ResolvedProviderRuntime:
        """Return the active provider config that supports a capability.

        Args:
            provider_category: str: .
            capability: str: .

        Returns:
            ResolvedProviderRuntime: .
        """
        normalized_category = provider_category.strip().lower()
        normalized_capability = capability.strip().lower()
        matches = [
            config
            for config in self._repository.list_active_provider_configs(self._owner_id)
            if provider_category_for_config(
                config.provider_type,
                config.provider_name,
                config.non_sensitive_config,
            )
            == normalized_category
            and normalized_capability in provider_capabilities_for_config(config)
        ]
        if not matches:
            raise LookupError(
                f"active provider config not found for capability: "
                f"{normalized_category}.{normalized_capability}"
            )
        if len(matches) != 1:
            raise RuntimeError(
                f"multiple active provider configs found for capability: "
                f"{normalized_category}.{normalized_capability}"
            )
        return self._resolve_config(
            matches[0],
            f"{normalized_category}.{normalized_capability}",
        )

    def _resolve_config(
        self,
        config: ProviderConfigVersion,
        lookup_name: str,
    ) -> ResolvedProviderRuntime:
        """Resolve one config and its frozen secret.

        Args:
            config: ProviderConfigVersion: .
            lookup_name: str: .

        Returns:
            ResolvedProviderRuntime: .
        """
        secret_required = bool(config.non_sensitive_config.get("secret_required", True))
        if config.secret_version_id is None:
            if secret_required:
                raise RuntimeError(f"active provider secret not configured: {lookup_name}")
            return ResolvedProviderRuntime(config=config, secret=None)

        metadata = self._secret_store.metadata(config.secret_version_id)
        if metadata.status != "active":
            raise RuntimeError(f"active provider references inactive secret: {lookup_name}")
        if not _secret_ref_matches_config(metadata.ref.provider_name, config):
            raise RuntimeError(f"provider secret reference mismatch: {lookup_name}")
        return ResolvedProviderRuntime(
            config=config,
            secret=self._secret_store.resolve(metadata.ref),
        )


class ProviderRuntimeFactory:
    """Construct real adapters exclusively from active versioned configuration.."""

    def __init__(self, resolver: ProviderRuntimeResolver) -> None:
        """Initialize the factory.

        Args:
            resolver: ProviderRuntimeResolver: .

        Returns:
            None: .
        """
        self._resolver = resolver

    def build_llm(self) -> RuntimeBoundProvider:
        """Build an OpenAI-compatible LLM adapter.

        Returns:
            RuntimeBoundProvider: .
        """
        from margin.research.llm import LLMProvider

        runtime = self._resolver.resolve_category("llm")
        return RuntimeBoundProvider(
            adapter=LLMProvider(
                name=runtime.config.provider_name,
                api_key=_required_secret(runtime),
                base_url=runtime.config.base_url,
                model=runtime.config.model_name,
            ),
            config_version_id=runtime.config.version_id,
        )

    def build_embedding(self) -> RuntimeBoundProvider:
        """Build an OpenAI-compatible embedding adapter.

        Returns:
            RuntimeBoundProvider: .
        """
        from margin.vector.providers.openai_embedding import OpenAIEmbeddingProvider

        runtime = self._resolver.resolve_category("embedding")
        dimension = int(runtime.config.non_sensitive_config.get("dimension", 1536))
        return RuntimeBoundProvider(
            adapter=OpenAIEmbeddingProvider(
                api_key=_required_secret(runtime),
                base_url=runtime.config.base_url,
                model=runtime.config.model_name,
                dimension=dimension,
            ),
            config_version_id=runtime.config.version_id,
        )

    def build_websearch(self) -> RuntimeBoundProvider:
        """Build the Tavily WebSearch adapter.

        Returns:
            RuntimeBoundProvider: .
        """
        from margin.news.providers.tavily import TavilySearchAdapter

        runtime = self._resolver.resolve_category("web_search")
        return RuntimeBoundProvider(
            adapter=TavilySearchAdapter(
                api_key=_required_secret(runtime),
                base_url=(runtime.config.base_url or "https://api.tavily.com/search"),
            ),
            config_version_id=runtime.config.version_id,
        )

    def build_tushare(self) -> RuntimeBoundProvider:
        """Build the Tushare market-data adapter.

        Returns:
            RuntimeBoundProvider: .
        """
        from margin.data.providers.tushare_provider import TushareProvider

        runtime = self._resolver.resolve("tushare")
        return RuntimeBoundProvider(
            adapter=TushareProvider(
                token=_required_secret(runtime),
                http_url=runtime.config.base_url,
            ),
            config_version_id=runtime.config.version_id,
        )

    def build_akshare(self) -> RuntimeBoundProvider:
        """Build the explicitly active secretless AKShare adapter.

        Returns:
            RuntimeBoundProvider: .
        """
        from margin.data.providers.akshare_provider import AKShareProvider

        runtime = self._resolver.resolve("akshare")
        return RuntimeBoundProvider(
            adapter=AKShareProvider(),
            config_version_id=runtime.config.version_id,
        )

    def build_market_data(self, capability: str) -> RuntimeBoundProvider:
        """Build a market-data adapter by declared capability.

        Args:
            capability: str: .

        Returns:
            RuntimeBoundProvider: .
        """
        runtime = self._resolver.resolve_capability("data_source", capability)
        provider_name = _runtime_provider_name_for_config(runtime.config)
        if provider_name == "tushare":
            from margin.data.providers.tushare_provider import TushareProvider

            return RuntimeBoundProvider(
                adapter=TushareProvider(
                    token=_required_secret(runtime),
                    http_url=runtime.config.base_url,
                ),
                config_version_id=runtime.config.version_id,
            )
        if provider_name == "akshare":
            from margin.data.providers.akshare_provider import AKShareProvider

            return RuntimeBoundProvider(
                adapter=AKShareProvider(),
                config_version_id=runtime.config.version_id,
            )
        raise RuntimeError(f"unsupported market-data provider: {provider_name}")

    def build_rerank(self) -> RuntimeBoundProvider:
        """Build the configured HTTP rerank adapter.

        Returns:
            RuntimeBoundProvider: .
        """
        from margin.vector.providers.rerank import HTTPRerankProvider

        runtime = self._resolver.resolve_category("rerank")
        return RuntimeBoundProvider(
            adapter=HTTPRerankProvider(
                api_key=_required_secret(runtime),
                base_url=runtime.config.base_url,
                model=runtime.config.model_name,
            ),
            config_version_id=runtime.config.version_id,
        )


def _required_secret(runtime: ResolvedProviderRuntime) -> str:
    """Return plaintext only at the final trusted adapter-construction boundary.

    Args:
        runtime: ResolvedProviderRuntime: .

    Returns:
        str: .
    """
    if runtime.secret is None:
        raise RuntimeError(f"provider secret not configured: {runtime.config.provider_name}")
    return runtime.secret.get_secret_value()


def provider_capabilities_for_config(config: ProviderConfigVersion) -> frozenset[str]:
    """Return normalized provider capabilities for a config version.

    Args:
        config: ProviderConfigVersion: .

    Returns:
        frozenset[str]: .
    """
    configured = config.non_sensitive_config.get("capabilities")
    if configured:
        return frozenset(_normalize_capabilities(configured))
    provider_name = _runtime_provider_name_for_config(config)
    return _DEFAULT_PROVIDER_CAPABILITIES.get(provider_name, frozenset())


def _runtime_provider_name_for_config(config: ProviderConfigVersion) -> str:
    """Return the executable provider name after URL/category detection."""
    detected_provider = str(
        config.non_sensitive_config.get("detected_provider") or ""
    ).strip().lower()
    if detected_provider in _DEFAULT_PROVIDER_CAPABILITIES:
        return detected_provider
    return config.provider_name.strip().lower()


def _normalize_capabilities(value: object) -> Iterable[str]:
    """Yield normalized capability names from config metadata.

    Args:
        value: object: .

    Yields:
        Any: .
    """
    if isinstance(value, str):
        raw_items = value.split(",")
    elif isinstance(value, Iterable):
        raw_items = value
    else:
        raw_items = ()
    for item in raw_items:
        normalized = str(item).strip().lower()
        if normalized:
            yield normalized


def _secret_ref_matches_config(
    secret_provider_name: str,
    config: ProviderConfigVersion,
) -> bool:
    """Return true when a secret is bound to the provider or config version.

    Args:
        secret_provider_name: str: .
        config: ProviderConfigVersion: .

    Returns:
        bool: .
    """
    normalized_secret_provider = secret_provider_name.strip().lower()
    runtime_provider = _runtime_provider_name_for_config(config)
    return normalized_secret_provider in {
        config.provider_name.strip().lower(),
        config.version_id.strip().lower(),
        runtime_provider,
    }
