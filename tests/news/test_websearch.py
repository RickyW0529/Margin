"""WebSearch Provider tests — 0302 acceptance."""

from __future__ import annotations

import pytest

from margin.core.provider import ProviderType
from margin.core.registry import ProviderRegistry
from margin.core.secret import SecretManager
from margin.news.acquirer import (
    BaseConnector,
    ComplianceError,
    SnapshotStore,
    SourceDescriptor,
    SourceRegistry,
)
from margin.news.models import SourceLevel
from margin.news.websearch import (
    ComplianceChecker,
    OriginalContentVerifier,
    SearchQueryRecord,
    SearchResult,
    WebSearchProvider,
    WebSearchService,
)


class TestWebSearchProvider:
    """Tests for the WebSearch provider."""

    def test_descriptor(self):
        """Provider descriptor must expose name, type and required secret refs."""
        provider = WebSearchProvider()
        assert provider.descriptor.name == "websearch"
        assert provider.descriptor.provider_type == ProviderType.WEB_SEARCH
        assert "websearch_api_key" in provider.descriptor.secret_refs

    def test_healthcheck_no_search_func(self):
        """Healthcheck must report degraded when no search function is configured."""
        provider = WebSearchProvider()
        result = provider.healthcheck()
        assert result.status.value == "degraded"

    def test_healthcheck_with_search_func(self):
        """Healthcheck must report healthy when a search function is configured."""
        provider = WebSearchProvider(search_func=lambda q, **k: [])
        result = provider.healthcheck()
        assert result.status.value == "healthy"

    def test_search_returns_record(self):
        """Search must return a record containing the query and parsed results."""

        def mock_search(query, max_results=10):
            return [
                {"url": "https://a.com", "title": "A", "snippet": "snippet A"},
                {"url": "https://b.com", "title": "B", "snippet": "snippet B"},
            ]

        provider = WebSearchProvider(search_func=mock_search)
        record = provider.search("test query", max_results=5)

        assert isinstance(record, SearchQueryRecord)
        assert record.query == "test query"
        assert len(record.results) == 2
        assert record.results[0].url == "https://a.com"
        assert record.result_count == 2

    def test_search_max_results_limit(self):
        """Search must cap returned results to the requested max_results."""

        def mock_search(query, max_results=10):
            return [
                {"url": f"https://{i}.com", "title": str(i), "snippet": ""}
                for i in range(20)
            ]

        provider = WebSearchProvider(search_func=mock_search)
        record = provider.search("test", max_results=5)
        assert len(record.results) == 5

    def test_search_no_func_raises(self):
        """Search must raise RuntimeError when no search function is configured."""
        provider = WebSearchProvider()
        with pytest.raises(RuntimeError, match="No search function"):
            provider.search("test")

    def test_search_record_frozen(self):
        """Search records must be immutable after creation."""

        def mock_search(query, max_results=10):
            return [{"url": "https://a.com", "title": "A", "snippet": ""}]

        provider = WebSearchProvider(search_func=mock_search)
        record = provider.search("test")
        with pytest.raises(Exception):
            record.query = "changed"

    def test_registry_injects_configured_api_key(self, tmp_path):
        """ProviderRegistry must inject the WebSearch secret through its standard hook."""
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        (secret_dir / "websearch_api_key").write_text("configured-key")
        provider = WebSearchProvider(search_func=lambda q, **k: [])

        ProviderRegistry(
            secret_manager=SecretManager(secrets_dir=secret_dir)
        ).register(provider)

        assert provider.api_key_configured is True


class TestComplianceChecker:
    """Tests for compliance checks on URLs and content."""

    def test_check_url_not_blocked(self):
        """Allowed URLs must pass the domain blocklist check."""
        ComplianceChecker.check_url("https://example.com")

    def test_check_url_blocked(self):
        """URLs on the blocklist must raise ComplianceError."""
        ComplianceChecker.BLOCKED_DOMAINS.add("paywall.com")
        try:
            with pytest.raises(ComplianceError, match="blocked domain"):
                ComplianceChecker.check_url("https://paywall.com/article")
        finally:
            ComplianceChecker.BLOCKED_DOMAINS.discard("paywall.com")

    def test_check_content_paywall_english(self):
        """English paywall phrases must be detected in content."""
        assert ComplianceChecker.check_content_for_paywall(
            "Please subscribe to read the full article"
        ) is True

    def test_check_content_paywall_chinese(self):
        """Chinese paywall phrases must be detected in content."""
        assert ComplianceChecker.check_content_for_paywall(
            "这是付费阅读内容"
        ) is True

    def test_check_content_no_paywall(self):
        """Content without paywall markers must not be flagged."""
        assert ComplianceChecker.check_content_for_paywall(
            "公司发布年度报告，净利润增长20%"
        ) is False

    def test_check_http_403(self):
        """HTTP 403 status must raise ComplianceError."""
        with pytest.raises(ComplianceError, match="403"):
            ComplianceChecker.check_http_status(403)

    def test_check_http_200_ok(self):
        """HTTP 200 status must pass without error."""
        ComplianceChecker.check_http_status(200)


class TestOriginalContentVerifier:
    """Tests for verifying and snapshotting original web content."""

    def _setup_registry(self, tmp_path, connector=None):
        """Create a registry and snapshot store for verifier tests.

        Args:
            tmp_path: Temporary path fixture for the snapshot store directory.
            connector: Optional connector to register for the websearch source.

        Returns:
            A tuple of (registry, store).
        """
        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(
                name="websearch",
                source_type="websearch",
                default_level=SourceLevel.L4,
            ),
            connector=connector,
        )
        store = SnapshotStore(base_dir=tmp_path)
        return registry, store

    def test_verify_success(self, tmp_path):
        """Public HTML content must be accepted and snapshotted."""

        class GoodConnector(BaseConnector):
            """Mock connector returning public HTML content.

            Attributes:
                source_name: Fixed source identifier.
            """

            @property
            def source_name(self):
                return "websearch"

            def fetch(self, url, **kwargs):
                """Return public HTML with HTTP 200.

                Args:
                    url: Target URL (ignored).
                    **kwargs: Additional fetch arguments (ignored).

                Returns:
                    A tuple of (response_bytes, content_type, http_status).
                """
                return "<html><body>公开内容</body></html>".encode(), "text/html", 200

        registry, store = self._setup_registry(tmp_path, GoodConnector())
        verifier = OriginalContentVerifier(registry, store)

        result = SearchResult(
            url="https://example.com/news",
            title="News",
            snippet="snippet",
        )
        verified = verifier.verify_and_snapshot(result)
        assert verified is not None
        assert verified.snapshot.content_hash.startswith("sha256:")
        assert verified.content == "公开内容"
        assert verified.result.has_accessible_original is True
        assert verified.result.snapshot_id == verified.snapshot.snapshot_id

    def test_verify_paywall_rejected(self, tmp_path):
        """Paywalled content must be rejected and not snapshotted."""

        class PaywallConnector(BaseConnector):
            """Mock connector returning paywalled content.

            Attributes:
                source_name: Fixed source identifier.
            """

            @property
            def source_name(self):
                return "websearch"

            def fetch(self, url, **kwargs):
                """Return paywalled HTML with HTTP 200.

                Args:
                    url: Target URL (ignored).
                    **kwargs: Additional fetch arguments (ignored).

                Returns:
                    A tuple of (response_bytes, content_type, http_status).
                """
                return b"Please subscribe to read more", "text/html", 200

        registry, store = self._setup_registry(tmp_path, PaywallConnector())
        verifier = OriginalContentVerifier(registry, store)

        result = SearchResult(url="https://pay.com", title="P", snippet="s")
        verified = verifier.verify_and_snapshot(result)
        assert verified is None
        assert list(tmp_path.iterdir()) == []

    def test_verify_403_rejected(self, tmp_path):
        """HTTP 403 responses must be rejected."""

        class ForbiddenConnector(BaseConnector):
            """Mock connector returning a 403 forbidden response.

            Attributes:
                source_name: Fixed source identifier.
            """

            @property
            def source_name(self):
                return "websearch"

            def fetch(self, url, **kwargs):
                """Return a 403 forbidden response.

                Args:
                    url: Target URL (ignored).
                    **kwargs: Additional fetch arguments (ignored).

                Returns:
                    A tuple of (response_bytes, content_type, http_status).
                """
                return b"forbidden", "text/html", 403

        registry, store = self._setup_registry(tmp_path, ForbiddenConnector())
        verifier = OriginalContentVerifier(registry, store)

        result = SearchResult(url="https://deny.com", title="D", snippet="s")
        verified = verifier.verify_and_snapshot(result)
        assert verified is None

    def test_verify_batch(self, tmp_path):
        """Batch verification must return results for every input search result."""

        class GoodConnector(BaseConnector):
            """Mock connector returning public content.

            Attributes:
                source_name: Fixed source identifier.
            """

            @property
            def source_name(self):
                return "websearch"

            def fetch(self, url, **kwargs):
                """Return public content with HTTP 200.

                Args:
                    url: Target URL (ignored).
                    **kwargs: Additional fetch arguments (ignored).

                Returns:
                    A tuple of (response_bytes, content_type, http_status).
                """
                return b"<html><body>public content</body></html>", "text/html", 200

        registry, store = self._setup_registry(tmp_path, GoodConnector())
        verifier = OriginalContentVerifier(registry, store)

        results = [
            SearchResult(url="https://a.com", title="A", snippet="s"),
            SearchResult(url="https://b.com", title="B", snippet="s"),
        ]
        verified = verifier.verify_batch(results)
        assert len(verified) == 2
        assert all(item is not None for item in verified)


class TestWebSearchService:
    """Tests for the high-level web search service."""

    def test_search_and_acquire(self, tmp_path):
        """Search results must be converted to document events with L4 level."""

        class GoodConnector(BaseConnector):
            """Mock connector returning public news HTML.

            Attributes:
                source_name: Fixed source identifier.
            """

            @property
            def source_name(self):
                return "websearch"

            def fetch(self, url, **kwargs):
                """Return public news HTML with HTTP 200.

                Args:
                    url: Target URL (ignored).
                    **kwargs: Additional fetch arguments (ignored).

                Returns:
                    A tuple of (response_bytes, content_type, http_status).
                """
                return "<html><body>公开新闻内容</body></html>".encode(), "text/html", 200

        def mock_search(query, max_results=10):
            return [
                {"url": "https://a.com/news", "title": "News A", "snippet": "A"},
                {"url": "https://b.com/news", "title": "News B", "snippet": "B"},
            ]

        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(
                name="websearch",
                source_type="websearch",
                default_level=SourceLevel.L4,
            ),
            connector=GoodConnector(),
        )
        store = SnapshotStore(base_dir=tmp_path)

        provider = WebSearchProvider(search_func=mock_search)
        service = WebSearchService(provider, registry, store)

        record, events = service.search_and_acquire("test query", max_results=5)

        assert record.result_count == 2
        assert len(events) == 2
        assert events[0].source_level == SourceLevel.L4
        assert events[0].can_change_research_state is False
        assert events[0].content == "公开新闻内容"
        assert events[0].content != record.results[0].snippet
        assert events[0].snapshot_id == record.results[0].snapshot_id
        assert events[0].snapshot_hash == record.results[0].content_hash
        assert record.results[0].has_accessible_original is True

    def test_search_and_acquire_filters_paywall(self, tmp_path):
        """Paywalled search results must be filtered out from acquired events."""

        class PaywallConnector(BaseConnector):
            """Mock connector returning paywalled content.

            Attributes:
                source_name: Fixed source identifier.
            """

            @property
            def source_name(self):
                return "websearch"

            def fetch(self, url, **kwargs):
                """Return paywalled HTML with HTTP 200.

                Args:
                    url: Target URL (ignored).
                    **kwargs: Additional fetch arguments (ignored).

                Returns:
                    A tuple of (response_bytes, content_type, http_status).
                """
                return b"subscribe to read full article", "text/html", 200

        def mock_search(query, max_results=10):
            return [
                {"url": "https://pay.com", "title": "Paywalled", "snippet": "s"},
            ]

        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(
                name="websearch",
                source_type="websearch",
                default_level=SourceLevel.L4,
            ),
            connector=PaywallConnector(),
        )
        store = SnapshotStore(base_dir=tmp_path)

        provider = WebSearchProvider(search_func=mock_search)
        service = WebSearchService(provider, registry, store)

        record, events = service.search_and_acquire("test", max_results=5)

        assert len(events) == 0
