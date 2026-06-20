"""Production adapters for the rule-based research tools."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from margin.data.providers.akshare_provider import AKShareProvider
from margin.news.acquirer import HTTPConnector, SnapshotStore, SourceRegistry
from margin.news.models import (
    SourceDescriptor,
    SourceLevel,
    make_document_event,
)
from margin.news.providers.tavily import TavilySearchAdapter
from margin.news.websearch import (
    OriginalContentVerifier,
    SearchResult,
    WebSearchProvider,
)
from margin.research.tools import (
    DocumentCollectorTool,
    FactorTool,
    FinancialTool,
    MarketDataTool,
    PortfolioTool,
    ToolRegistry,
    WebSearchTool,
)
from margin.settings import MarginSettings
from margin.vector.embedding import EmbeddingPipeline
from margin.vector.persistent_pipeline import PersistentEmbeddingPipeline

if TYPE_CHECKING:
    from margin.vector.repository import VectorRepository

if TYPE_CHECKING:
    from margin.news.repository import NewsRepository


def build_production_tool_registry(
    settings: MarginSettings,
    *,
    market_data_provider: Any | None = None,
    embedding_provider: Any | None = None,
    news_repository: NewsRepository | None = None,
    snapshot_store: SnapshotStore | None = None,
    vector_repository: VectorRepository | None = None,
) -> ToolRegistry:
    """Build the production tool registry with usable read-only adapters.

    Args:
        settings: Application settings including the web search API key.
        market_data_provider: Optional market data provider. Defaults to ``AKShareProvider``.
        embedding_provider: Optional embedding provider for vector retrieval.
        news_repository: Optional repository for persisting search records and snapshots.
        snapshot_store: Optional store for document snapshots.
        vector_repository: Optional repository for persistent vector retrieval.

    Returns:
        A ``ToolRegistry`` configured with production adapters.
    """
    market_provider = market_data_provider or AKShareProvider()
    pipeline = (
        PersistentEmbeddingPipeline(
            embedding_provider=embedding_provider,
            repository=vector_repository,
        )
        if embedding_provider is not None and vector_repository is not None
        else EmbeddingPipeline(embedding_provider=embedding_provider)
    )
    registry = ToolRegistry()
    registry.register_defaults(pipeline)

    bar_cache: dict[str, list[dict[str, Any]]] = {}

    def load_bars(symbol: str) -> list[dict[str, Any]]:
        if symbol not in bar_cache:
            end = datetime.now(UTC)
            try:
                bar_cache[symbol] = list(
                    market_provider.get_bars(
                        [symbol],
                        end - timedelta(days=120),
                        end,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                bar_cache[symbol] = [
                    {
                        "symbol": symbol,
                        "date": end,
                        "close": 0.0,
                        "available_at": end,
                        "degraded": True,
                        "error": type(exc).__name__,
                    }
                ]
        return bar_cache[symbol]

    def market_data(params: dict[str, Any]) -> dict[str, Any]:
        symbol = str(params["symbol"])
        bars = load_bars(symbol)
        if not bars:
            raise RuntimeError(f"no market data available for {symbol}")
        return max(bars, key=lambda item: item["date"])

    def factors(params: dict[str, Any]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for value in params.get("symbols", []):
            symbol = str(value)
            bars = sorted(load_bars(symbol), key=lambda item: item["date"])
            if not bars:
                continue
            first_close = float(bars[0]["close"])
            last_close = float(bars[-1]["close"])
            scores[symbol] = (
                0.0
                if first_close == 0
                else round((last_close / first_close) - 1.0, 6)
            )
        if not scores:
            raise RuntimeError("no factor inputs available")
        return scores

    def financials(params: dict[str, Any]) -> list[dict[str, Any]]:
        symbols = [str(value) for value in params.get("symbols", [])]
        if not symbols and params.get("symbol"):
            symbols = [str(params["symbol"])]
        end = datetime.now(UTC)
        return list(
            market_provider.get_financials(
                symbols,
                end - timedelta(days=550),
                end,
            )
        )

    def portfolio_constraints(params: dict[str, Any]) -> dict[str, Any]:
        current_weight = float(params.get("current_weight", 0.0))
        max_weight = float(params.get("max_weight", 0.1))
        violations = []
        if current_weight > max_weight:
            violations.append(
                f"{params.get('symbol', '')} weight {current_weight:.4f} "
                f"exceeds {max_weight:.4f}"
            )
        return {
            "violations": violations,
            "current_weight": current_weight,
            "max_weight": max_weight,
        }

    registry.register(MarketDataTool(market_data))
    registry.register(FactorTool(factors))
    registry.register(FinancialTool(financials))
    registry.register(PortfolioTool(portfolio_constraints))

    websearch_key = (
        settings.websearch_api_key.get_secret_value().strip()
        if settings.websearch_api_key is not None
        else ""
    )
    if websearch_key:
        adapter = TavilySearchAdapter(api_key=websearch_key)
        provider = WebSearchProvider(search_func=adapter.search)

        source_registry = SourceRegistry()
        source_registry.register(
            SourceDescriptor(
                name="websearch",
                source_type="websearch",
                default_level=SourceLevel.L4,
                rate_limit_per_min=30,
            ),
            HTTPConnector("websearch"),
        )
        resolved_snapshot_store = snapshot_store or SnapshotStore()
        verifier = OriginalContentVerifier(
            source_registry,
            resolved_snapshot_store,
        )

        def websearch(params: dict[str, Any]) -> dict[str, Any]:
            record = provider.search(
                str(params["query"]),
                max_results=int(params.get("max_results", 10)),
            )
            if news_repository is not None:
                news_repository.add_search_record(record)
            return {
                "query_id": record.query_id,
                "results": [
                    result.model_dump(mode="json") for result in record.results
                ],
            }

        def collect_document(params: dict[str, Any]) -> dict[str, Any]:
            source = SearchResult.model_validate(params["source"])
            verified = verifier.verify_and_snapshot(source)
            if verified is None:
                raise RuntimeError("original content is unavailable or non-compliant")
            event = make_document_event(
                source_url=source.url,
                source_name="websearch",
                source_level=source.source_level,
                title=verified.title,
                content=verified.content,
                doc_type="news",
                published_at=verified.snapshot.downloaded_at,
                available_at=verified.snapshot.downloaded_at,
                snapshot_id=verified.snapshot.snapshot_id,
                snapshot_hash=verified.snapshot.content_hash,
            )
            if news_repository is not None:
                news_repository.add_snapshot(verified.snapshot)
                news_repository.add_document_event(event)
            return {
                "url": source.url,
                "title": verified.title,
                "content_hash": event.content_hash,
                "snapshot_id": verified.snapshot.snapshot_id,
                "snapshot_hash": verified.snapshot.content_hash,
            }

        registry.register(WebSearchTool(websearch))
        registry.register(DocumentCollectorTool(collect_document))

    return registry
