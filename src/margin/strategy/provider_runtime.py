"""Resolve executable Provider adapters from frozen active configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from margin.core.secret_store import SecretStore, SecretValue
from margin.strategy.models import ProviderConfigVersion
from margin.strategy.provider_router import provider_category_for_config

T = TypeVar("T")


@dataclass(frozen=True)
class RuntimeBoundProvider(Generic[T]):
    """Executable adapter bound to a frozen Provider config version."""

    adapter: T
    config_version_id: str


@dataclass(frozen=True)
class ResolvedProviderRuntime:
    """Active non-sensitive config plus an optional masked secret value."""

    config: ProviderConfigVersion
    secret: SecretValue | None


class ProviderRuntimeResolver:
    """Resolve one executable Provider version for trusted runtime consumers."""

    def __init__(
        self,
        repository: object,
        secret_store: SecretStore,
        *,
        owner_id: str = "local-admin",
    ) -> None:
        """Initialize the resolver."""
        self._repository = repository
        self._secret_store = secret_store
        self._owner_id = owner_id

    def resolve(self, provider_name: str) -> ResolvedProviderRuntime:
        """Return the single active config and its frozen secret version."""
        normalized_name = provider_name.strip().lower()
        matches = [
            config
            for config in self._repository.list_active_provider_configs(
                self._owner_id
            )
            if config.provider_name.strip().lower() == normalized_name
        ]
        if not matches:
            raise LookupError(
                f"active provider config not found: {normalized_name}"
            )
        if len(matches) != 1:
            raise RuntimeError(
                f"multiple active provider configs found: {normalized_name}"
            )
        return self._resolve_config(matches[0], normalized_name)

    def resolve_category(self, provider_category: str) -> ResolvedProviderRuntime:
        """Return the single active config for a provider category."""
        normalized_category = provider_category.strip().lower()
        matches = [
            config
            for config in self._repository.list_active_provider_configs(
                self._owner_id
            )
            if provider_category_for_config(
                config.provider_type,
                config.provider_name,
                config.non_sensitive_config,
            )
            == normalized_category
        ]
        if not matches:
            raise LookupError(
                f"active provider config not found: {normalized_category}"
            )
        if len(matches) != 1:
            raise RuntimeError(
                f"multiple active provider configs found: {normalized_category}"
            )
        return self._resolve_config(matches[0], normalized_category)

    def _resolve_config(
        self,
        config: ProviderConfigVersion,
        lookup_name: str,
    ) -> ResolvedProviderRuntime:
        """Resolve one config and its frozen secret."""
        secret_required = bool(
            config.non_sensitive_config.get("secret_required", True)
        )
        if config.secret_version_id is None:
            if secret_required:
                raise RuntimeError(
                    f"active provider secret not configured: {lookup_name}"
                )
            return ResolvedProviderRuntime(config=config, secret=None)

        metadata = self._secret_store.metadata(config.secret_version_id)
        if metadata.status != "active":
            raise RuntimeError(
                f"active provider references inactive secret: {lookup_name}"
            )
        if not _secret_ref_matches_config(metadata.ref.provider_name, config):
            raise RuntimeError(
                f"provider secret reference mismatch: {lookup_name}"
            )
        return ResolvedProviderRuntime(
            config=config,
            secret=self._secret_store.resolve(metadata.ref),
        )


class ProviderRuntimeFactory:
    """Construct real adapters exclusively from active versioned configuration."""

    def __init__(self, resolver: ProviderRuntimeResolver) -> None:
        """Initialize the factory."""
        self._resolver = resolver

    def build_llm(self) -> RuntimeBoundProvider:
        """Build an OpenAI-compatible LLM adapter."""
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
        """Build an OpenAI-compatible embedding adapter."""
        from margin.vector.providers.openai_embedding import OpenAIEmbeddingProvider

        runtime = self._resolver.resolve_category("embedding")
        dimension = int(
            runtime.config.non_sensitive_config.get("dimension", 1536)
        )
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
        """Build the Tavily WebSearch adapter."""
        from margin.news.providers.tavily import TavilySearchAdapter

        runtime = self._resolver.resolve_category("web_search")
        return RuntimeBoundProvider(
            adapter=TavilySearchAdapter(
                api_key=_required_secret(runtime),
                base_url=(
                    runtime.config.base_url
                    or "https://api.tavily.com/search"
                ),
            ),
            config_version_id=runtime.config.version_id,
        )

    def build_tushare(self) -> RuntimeBoundProvider:
        """Build the Tushare market-data adapter."""
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
        """Build the explicitly active secretless AKShare adapter."""
        from margin.data.providers.akshare_provider import AKShareProvider

        runtime = self._resolver.resolve("akshare")
        return RuntimeBoundProvider(
            adapter=AKShareProvider(),
            config_version_id=runtime.config.version_id,
        )

    def build_rerank(self) -> RuntimeBoundProvider:
        """Build the configured HTTP rerank adapter."""
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
    """Return plaintext only at the final trusted adapter-construction boundary."""
    if runtime.secret is None:
        raise RuntimeError(
            f"provider secret not configured: {runtime.config.provider_name}"
        )
    return runtime.secret.get_secret_value()


def _secret_ref_matches_config(
    secret_provider_name: str,
    config: ProviderConfigVersion,
) -> bool:
    """Return true when a secret is bound to the provider or config version."""
    normalized_secret_provider = secret_provider_name.strip().lower()
    return normalized_secret_provider in {
        config.provider_name.strip().lower(),
        config.version_id.strip().lower(),
    }
