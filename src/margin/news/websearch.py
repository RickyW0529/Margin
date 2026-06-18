"""WebSearch Provider — configurable web search provider.

Implements spec 03 §3 interface contract and architecture §6.2.1 WebSearch Provider
with news compliance requirements.

Corresponds to plan 0302:
  0302.1 WebSearchProvider integration — user-configured API key.
  0302.2 Search result snapshot — persist query/URL/title/snippet/crawl time/
      original content snapshot hash.
  0302.3 Compliance boundary enforcement — do not bypass robots, paywalls,
      or anti-scraping; do not include copyright-restricted full text in open
      source sample data.
  0302.4 Original content verification — only enter evidence library when the
      result resolves to accessible original content or a compliant snapshot.

Compliance constraints (architecture §6.2.1):
- The user supplies their own API key.
- The system persists the search query, returned URL, title, snippet, crawl time,
  and original content snapshot hash.
- A result enters the RAG evidence library only when it resolves to accessible
  original content or a compliant snapshot.
- Do not bypass robots.txt, login walls, paywalls, or anti-scraping mechanisms.
- Do not submit copyright-restricted full text to open source sample data.
- L4/L5 sources may only trigger investigation or provide auxiliary explanation;
  they cannot alone change research or portfolio state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from margin.core.provider import (
    BaseProvider,
    HealthCheckResult,
    ProviderDescriptor,
    ProviderStatus,
    ProviderType,
)
from margin.news.acquirer import (
    ComplianceError,
    DocumentParser,
    Downloader,
    DownloadError,
    ParseError,
    SnapshotStore,
    SourceRegistry,
)
from margin.news.models import (
    DocumentEvent,
    RawSnapshot,
    SourceLevel,
    compute_content_hash,
    make_document_event,
    utc_now,
)

# ---------------------------------------------------------------------------
# Search result models
# ---------------------------------------------------------------------------


class SearchResult(BaseModel):
    """A single web search result.

    Attributes:
        url: Result URL.
        title: Result title.
        snippet: Result snippet or abstract.
        source_level: Source level assigned to the result (web search defaults to L4).
        has_accessible_original: Whether accessible original content is available.
        content_hash: Hash of the original content snapshot, if available.
    """

    url: str
    title: str
    snippet: str
    source_level: SourceLevel = SourceLevel.L4
    has_accessible_original: bool = False
    content_hash: str | None = None
    snapshot_id: str | None = None

    model_config = {"frozen": True}


class SearchQueryRecord(BaseModel):
    """Search query record (architecture §6.2.1: persist query/URL/title/snippet/
    crawl time/original content snapshot hash).

    Immutable after persistence; used for audit and compliance tracing.

    Attributes:
        query_id: Unique identifier for the query record.
        query: Search query string.
        results: List of search results.
        searched_at: Timestamp when the search was performed.
        api_provider: Name of the API provider that served the query.
        result_count: Number of results returned.
    """

    query_id: str
    query: str
    results: tuple[SearchResult, ...] = Field(default_factory=tuple)
    searched_at: datetime = Field(default_factory=utc_now)
    api_provider: str
    result_count: int = 0

    model_config = {"frozen": True}


class VerifiedContent(BaseModel):
    """Accessible original content and its immutable snapshot metadata."""

    result: SearchResult
    snapshot: RawSnapshot
    title: str
    content: str

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# WebSearch Provider
# ---------------------------------------------------------------------------


class WebSearchProvider(BaseProvider):
    """WebSearch Provider — configurable web search provider.

    The user supplies their own API key (referenced through SecretManager).
    Supports multiple search APIs via injected ``search_func``.
    The MVP does not bind a specific search service; plugability is achieved
    through function injection.

    Compliance constraints:
    - Do not bypass robots.txt, login walls, paywalls, or anti-scraping
      mechanisms.
    - Do not submit copyright-restricted full text to open source sample data.
    - A result enters the RAG evidence library only when it resolves to
      accessible original content or a compliant snapshot.
    """

    def __init__(
        self,
        name: str = "websearch",
        secret_ref: str = "websearch_api_key",
        search_func: Any = None,
    ) -> None:
        """Initialize the web search provider.

        Args:
            name: Provider name used in descriptors and logging.
            secret_ref: Secret manager reference for the API key.
            search_func: Callable ``(query, max_results) -> list[dict]`` that
                performs the actual search. Defaults to None.
        """
        self._secret_ref = secret_ref
        self._api_key: str | None = None
        self._search_func = search_func
        self._descriptor = ProviderDescriptor(
            name=name,
            version="1.0.0",
            provider_type=ProviderType.WEB_SEARCH,
            capabilities=["search"],
            secret_refs=[secret_ref],
            config={"license": "User-configured API key"},
        )

    @property
    def descriptor(self) -> ProviderDescriptor:
        """Return the provider descriptor.

        Returns:
            ProviderDescriptor with metadata, capabilities, and secret refs.
        """
        return self._descriptor

    def set_api_key(self, api_key: str) -> None:
        """Set the API key (injected by Registry after ``resolve_secrets``).

        Args:
            api_key: Resolved API key string.
        """
        self._api_key = api_key

    def configure_secrets(self, secrets: dict[str, str]) -> None:
        """Configure the API key through the standard ProviderRegistry hook."""
        api_key = secrets.get(self._secret_ref)
        if api_key:
            self.set_api_key(api_key)

    @property
    def api_key_configured(self) -> bool:
        """Return whether the configured secret reference has been resolved."""
        return bool(self._api_key)

    def set_search_func(self, search_func: Any) -> None:
        """Set the search function (enables swapping search APIs).

        Args:
            search_func: Callable ``(query, max_results) -> list[dict]``.
        """
        self._search_func = search_func

    def healthcheck(self) -> HealthCheckResult:
        """Check whether the provider is ready to serve search requests.

        Returns:
            HealthCheckResult: DEGRADED when no search function is configured,
            HEALTHY otherwise.
        """
        if self._search_func is None:
            return HealthCheckResult(
                provider_name=self._descriptor.name,
                status=ProviderStatus.DEGRADED,
                checked_at=utc_now(),
                message="No search function configured",
            )
        return HealthCheckResult(
            provider_name=self._descriptor.name,
            status=ProviderStatus.HEALTHY,
            checked_at=utc_now(),
            message="search function configured",
        )

    def search(
        self,
        query: str,
        max_results: int = 10,
        source_level: SourceLevel = SourceLevel.L4,
    ) -> SearchQueryRecord:
        """Execute a search and return the query record.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            source_level: Default source level for returned results (web search
                defaults to L4).

        Returns:
            SearchQueryRecord containing the result list and audit fields.

        Raises:
            RuntimeError: If no search function has been configured.
        """
        import uuid

        if self._search_func is None:
            raise RuntimeError("No search function configured")

        raw_results = self._search_func(query, max_results=max_results)

        results: list[SearchResult] = []
        for raw in raw_results[:max_results]:
            results.append(
                SearchResult(
                    url=raw.get("url", ""),
                    title=raw.get("title", ""),
                    snippet=raw.get("snippet", ""),
                    source_level=source_level,
                    has_accessible_original=False,
                )
            )

        return SearchQueryRecord(
            query_id=f"sq_{uuid.uuid4().hex[:12]}",
            query=query,
            results=tuple(results),
            api_provider=self._descriptor.name,
            result_count=len(results),
        )


# ---------------------------------------------------------------------------
# 0302.3 / 0302.4 compliance boundary enforcement and original content
# verification
# ---------------------------------------------------------------------------


class ComplianceChecker:
    """Compliance boundary checker (architecture §6.2.1).

    Checks:
    - Do not bypass robots.txt, paywalls, or anti-scraping (HTTP 401/403 ->
      reject).
    - Do not include copyright-restricted full text in open source sample data.
    - WebSearch results must resolve to accessible original content or a
      compliant snapshot.
    - Search snippets alone cannot be cited as evidence.

    Attributes:
        BLOCKED_DOMAINS: Set of blocked domain strings.
        PAYWALL_INDICATORS: Substrings that indicate paywalled content.
    """

    BLOCKED_DOMAINS: set[str] = set()

    PAYWALL_INDICATORS = [
        "subscribe to read",
        "subscribe to continue",
        "premium content",
        "登录后查看",
        "付费阅读",
    ]

    @staticmethod
    def check_url(url: str) -> None:
        """Check whether the URL belongs to a blocked domain.

        Args:
            url: URL to validate.

        Raises:
            ComplianceError: If the URL matches a blocked domain.
        """
        from urllib.parse import urlparse

        domain = urlparse(url).netloc.lower()
        for blocked in ComplianceChecker.BLOCKED_DOMAINS:
            if blocked in domain:
                raise ComplianceError(
                    f"URL '{url}' is in blocked domain list: {blocked}"
                )

    @staticmethod
    def check_content_for_paywall(content: str) -> bool:
        """Check whether the content contains paywall indicators.

        Args:
            content: Text content to inspect.

        Returns:
            True if a paywall indicator is detected (content should not enter
            the evidence library).
        """
        lower = content.lower()
        return any(indicator in lower for indicator in ComplianceChecker.PAYWALL_INDICATORS)

    @staticmethod
    def check_http_status(status: int) -> None:
        """Check the HTTP status code; 401/403 trigger compliance rejection.

        Args:
            status: HTTP response status code.

        Raises:
            ComplianceError: If ``status`` is 401 or 403.
        """
        if status in (401, 403):
            raise ComplianceError(
                f"HTTP {status}: access denied — login wall or paywall, not bypassed"
            )


class OriginalContentVerifier:
    """Original content verifier (architecture §6.2.1: 0302.4).

    WebSearch results must resolve to accessible original content or a compliant
    snapshot; search snippets alone are insufficient.
    """

    def __init__(
        self,
        registry: SourceRegistry,
        snapshot_store: SnapshotStore,
    ) -> None:
        """Initialize the verifier with a downloader backed by the registry and
        snapshot store.

        Args:
            registry: Source registry used by the downloader.
            snapshot_store: Snapshot store used to read downloaded snapshots.
        """
        self._downloader = Downloader(registry, snapshot_store)
        self._snapshot_store = snapshot_store
        self._parser = DocumentParser()
        self._compliance = ComplianceChecker

    def verify_and_snapshot(
        self,
        result: SearchResult,
    ) -> VerifiedContent | None:
        """Verify that a search result resolves to accessible original content
        and persist a snapshot.

        Args:
            result: Search result to verify.

        Returns:
            Verified original content with snapshot metadata, or None when the
            result is inaccessible, non-compliant, or cannot be parsed.
        """
        try:
            self._compliance.check_url(result.url)
            snapshot = self._downloader.download("websearch", result.url)
            content = self._snapshot_store.read_snapshot(snapshot)
            if content is None:
                return None

            text = content.decode("utf-8", errors="replace")
            if self._compliance.check_content_for_paywall(text):
                self._snapshot_store.delete(snapshot)
                return None

            parsed = self._parser.parse(snapshot, content)
            original_content = str(parsed.get("content") or "").strip()
            if parsed.get("parse_note") or not original_content:
                return None

            verified_result = result.model_copy(
                update={
                    "has_accessible_original": True,
                    "content_hash": snapshot.content_hash,
                    "snapshot_id": snapshot.snapshot_id,
                }
            )
            return VerifiedContent(
                result=verified_result,
                snapshot=snapshot,
                title=str(parsed.get("title") or result.title),
                content=original_content,
            )
        except (ComplianceError, DownloadError, ParseError):
            return None

    def verify_batch(
        self,
        results: list[SearchResult],
    ) -> list[VerifiedContent | None]:
        """Verify a batch of search results.

        Args:
            results: List of search results to verify.

        Returns:
            One verification result per input result; inaccessible items are None.
        """
        verified: list[VerifiedContent | None] = []
        for result in results:
            verified.append(self.verify_and_snapshot(result))
        return verified


# ---------------------------------------------------------------------------
# 0302 integration: WebSearch service
# ---------------------------------------------------------------------------


class WebSearchService:
    """WebSearch service — integrates provider, compliance checks, and original
    content verification.

    Example:
        provider = WebSearchProvider(search_func=my_search_api)
        service = WebSearchService(provider, registry, snapshot_store)
        record, events = service.search_and_acquire(
            "平安银行 公告", max_results=5
        )
    """

    def __init__(
        self,
        provider: WebSearchProvider,
        registry: SourceRegistry,
        snapshot_store: SnapshotStore,
    ) -> None:
        """Initialize the service.

        Args:
            provider: Configured web search provider.
            registry: Source registry for content acquisition.
            snapshot_store: Snapshot store for persisting downloaded content.
        """
        self._provider = provider
        self._verifier = OriginalContentVerifier(registry, snapshot_store)

    def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> SearchQueryRecord:
        """Execute a search and return the query record.

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.

        Returns:
            SearchQueryRecord containing the results and audit fields.
        """
        return self._provider.search(query, max_results=max_results)

    def search_and_acquire(
        self,
        query: str,
        max_results: int = 10,
        source_level: SourceLevel = SourceLevel.L4,
    ) -> tuple[SearchQueryRecord, list[DocumentEvent]]:
        """Search and acquire original content, returning the query record and
        document events for successfully acquired results.

        Only results that resolve to accessible original content or a compliant
        snapshot generate document events (architecture §6.2.1).

        Args:
            query: Search query string.
            max_results: Maximum number of results to return.
            source_level: Source level assigned to returned results.

        Returns:
            Tuple of (query record, list of document events).
        """
        record = self._provider.search(
            query, max_results=max_results, source_level=source_level
        )

        verified = self._verifier.verify_batch(record.results)

        events: list[DocumentEvent] = []
        audited_results: list[SearchResult] = []
        for result, verified_content in zip(record.results, verified, strict=True):
            if verified_content is None:
                audited_results.append(result)
                continue

            audited_result = verified_content.result
            audited_results.append(audited_result)
            event = make_document_event(
                source_url=audited_result.url,
                source_name=self._provider.descriptor.name,
                source_level=audited_result.source_level,
                title=verified_content.title or audited_result.title,
                content=verified_content.content,
                content_hash=compute_content_hash(verified_content.content),
                doc_type="news",
                published_at=verified_content.snapshot.downloaded_at,
                available_at=verified_content.snapshot.downloaded_at,
                snapshot_id=verified_content.snapshot.snapshot_id,
                snapshot_hash=verified_content.snapshot.content_hash,
            )
            events.append(event)

        audited_record = record.model_copy(update={"results": tuple(audited_results)})
        return audited_record, events
