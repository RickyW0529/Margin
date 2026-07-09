"""Filing acquisition and original snapshot tests — 0301 acceptance."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from margin.news.acquirer import (
    BaseConnector,
    ComplianceError,
    DocumentParser,
    Downloader,
    DownloadError,
    FilingAcquirer,
    ParseError,
    SecurityMapper,
    SnapshotStore,
    SourceNotFoundError,
    SourceRegistry,
)
from margin.news.models import (
    SourceDescriptor,
    SourceLevel,
    compute_content_hash,
    make_document_event,
)


class TestSourceLevel:
    """Tests for source authority level ordering.."""

    def test_l1_is_highest(self):
        """L1 must rank higher than L5.

        Returns:
            Any: .
        """
        assert SourceLevel.L1 < SourceLevel.L5

    def test_levels_1_to_5(self):
        """Level values must span from 1 to 5.

        Returns:
            Any: .
        """
        assert SourceLevel.L1 == 1
        assert SourceLevel.L5 == 5


class TestComputeContentHash:
    """Tests for content hash computation.."""

    def test_string_hash(self):
        """String input must produce a sha256-prefixed hash.

        Returns:
            Any: .
        """
        h = compute_content_hash("hello")
        assert h.startswith("sha256:")

    def test_bytes_hash(self):
        """Bytes input must produce a sha256-prefixed hash.

        Returns:
            Any: .
        """
        h = compute_content_hash(b"hello")
        assert h.startswith("sha256:")

    def test_deterministic(self):
        """Hashing the same input must produce the same digest.

        Returns:
            Any: .
        """
        assert compute_content_hash("test") == compute_content_hash("test")


class TestMakeDocumentEvent:
    """Tests for document event factory behavior.."""

    def test_basic_event(self):
        """Factory must populate level, title, hash, event id and document id.

        Returns:
            Any: .
        """
        event = make_document_event(
            source_url="https://example.com/filing.pdf",
            source_name="sse",
            source_level=SourceLevel.L1,
            title="某公司公告",
            content="公告正文",
        )
        assert event.source_level == SourceLevel.L1
        assert event.title == "某公司公告"
        assert event.content_hash.startswith("sha256:")
        assert event.event_id.startswith("evt_")
        assert event.document_id.startswith("doc_")

    def test_auto_hash_from_content(self):
        """Factory must compute the content hash from body text when omitted.

        Returns:
            Any: .
        """
        event = make_document_event(
            source_url="https://example.com",
            source_name="sse",
            source_level=SourceLevel.L1,
            title="test",
            content="some content",
        )
        expected = compute_content_hash("some content")
        assert event.content_hash == expected

    def test_can_change_research_state_l1(self):
        """L1 events must be allowed to change research state.

        Returns:
            Any: .
        """
        event = make_document_event(
            source_url="u", source_name="s", source_level=SourceLevel.L1, title="t"
        )
        assert event.can_change_research_state is True

    def test_cannot_change_research_state_l4(self):
        """L4 events must not be allowed to change research state.

        Returns:
            Any: .
        """
        event = make_document_event(
            source_url="u", source_name="s", source_level=SourceLevel.L4, title="t"
        )
        assert event.can_change_research_state is False

    def test_frozen(self):
        """Event fields must be immutable after creation.

        Returns:
            Any: .
        """
        event = make_document_event(
            source_url="u", source_name="s", source_level=SourceLevel.L1, title="t"
        )
        with pytest.raises(Exception):
            event.title = "changed"

    def test_symbols_are_deeply_immutable(self):
        """Frozen events must not expose a mutable symbols collection.

        Returns:
            Any: .
        """
        event = make_document_event(
            source_url="u",
            source_name="s",
            source_level=SourceLevel.L1,
            title="t",
            symbols=["000001.SZ"],
        )

        assert event.symbols == ("000001.SZ",)
        with pytest.raises((AttributeError, TypeError, ValidationError)):
            event.symbols.append("600000.SH")

    def test_timestamps_are_normalized_to_utc(self):
        """Naive event timestamps must be normalized to timezone-aware UTC values.

        Returns:
            Any: .
        """
        event = make_document_event(
            source_url="u",
            source_name="s",
            source_level=SourceLevel.L1,
            title="t",
            published_at=datetime(2026, 6, 18, 9, 30),
        )

        assert event.published_at.tzinfo == UTC
        assert event.available_at.tzinfo == UTC
        assert event.retrieved_at.tzinfo == UTC


class TestSourceRegistry:
    """Tests for source registry registration and lookup.."""

    def test_register_and_get(self):
        """Registered descriptors must be retrievable by name.

        Returns:
            Any: .
        """
        registry = SourceRegistry()
        desc = SourceDescriptor(name="sse", source_type="exchange", default_level=SourceLevel.L1)
        registry.register(desc)
        assert registry.get("sse") is desc

    def test_get_not_found(self):
        """Lookup of an unknown source must raise SourceNotFoundError.

        Returns:
            Any: .
        """
        registry = SourceRegistry()
        with pytest.raises(SourceNotFoundError):
            registry.get("nonexistent")

    def test_list_sources(self):
        """list_sources must return the names of all registered sources.

        Returns:
            Any: .
        """
        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="sse", source_type="exchange", default_level=SourceLevel.L1)
        )
        registry.register(
            SourceDescriptor(name="media", source_type="media", default_level=SourceLevel.L4)
        )
        assert set(registry.list_sources()) == {"sse", "media"}

    def test_list_by_type(self):
        """list_by_type must return only sources of the requested type.

        Returns:
            Any: .
        """
        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="sse", source_type="exchange", default_level=SourceLevel.L1)
        )
        registry.register(
            SourceDescriptor(name="szse", source_type="exchange", default_level=SourceLevel.L1)
        )
        registry.register(
            SourceDescriptor(name="media", source_type="media", default_level=SourceLevel.L4)
        )
        assert set(registry.list_by_type("exchange")) == {"sse", "szse"}


class TestSnapshotStore:
    """Tests for snapshot persistence and retrieval.."""

    def test_default_base_dir_is_project_relative(self, tmp_path, monkeypatch):
        """Default snapshots must be written under the project-relative .margin directory.

        Args:
            tmp_path: Any: .
            monkeypatch: Any: .

        Returns:
            Any: .
        """
        monkeypatch.chdir(tmp_path)
        store = SnapshotStore()
        snapshot = store.save("url", b"data", content_type="text/plain")
        assert store._base_dir == Path(".margin/snapshots")
        assert not store._base_dir.is_absolute()
        assert snapshot.storage_path is not None
        assert Path(snapshot.storage_path) == (
            Path(".margin/snapshots") / f"{snapshot.snapshot_id}.txt"
        )

    def test_save_and_read(self, tmp_path):
        """Snapshots must be persisted and readable by id and extension.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        store = SnapshotStore(base_dir=tmp_path)
        content = b"<html>hello</html>"
        snapshot = store.save(
            source_url="https://example.com",
            content=content,
            content_type="text/html",
            http_status=200,
        )
        assert snapshot.content_hash.startswith("sha256:")
        assert snapshot.content_type == "html"
        assert snapshot.raw_size == len(content)

        read_back = store.read(snapshot.snapshot_id, "html")
        assert read_back == content

    def test_read_nonexistent(self, tmp_path):
        """Reading a missing snapshot must return None.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        store = SnapshotStore(base_dir=tmp_path)
        assert store.read("nonexistent", "html") is None

    def test_detect_extension(self, tmp_path):
        """Content types must be mapped to the correct file extension.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        store = SnapshotStore(base_dir=tmp_path)
        for ct, ext in [
            ("application/pdf", "pdf"),
            ("text/html", "html"),
            ("application/json", "json"),
            ("text/csv", "csv"),
            ("text/plain", "txt"),
        ]:
            snap = store.save("url", b"data", content_type=ct)
            assert snap.content_type == ext


class TestMockConnector(BaseConnector):
    """Mock connector returning a simple HTML filing page for tests.."""

    @property
    def source_name(self) -> str:
        """Return the fixed source name for this connector.

        Returns:
            str: .
        """
        return "mock"

    def fetch(self, url: str, **kwargs):
        """Return a mock HTML response.

        Args:
            url: str: .
            **kwargs: Any: .

        Returns:
            Any: .
        """
        html = "<html><head><title>Test Filing</title></head><body>公告正文 000001.SZ</body></html>"
        return html.encode("utf-8"), "text/html", 200


class TestDownloader:
    """Tests for document downloading.."""

    def test_download_success(self, tmp_path):
        """Successful downloads must return a snapshot with source URL and status.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="mock", source_type="exchange", default_level=SourceLevel.L1),
            connector=TestMockConnector(),
        )
        store = SnapshotStore(base_dir=tmp_path)
        downloader = Downloader(registry, store)

        snapshot = downloader.download("mock", "https://example.com/filing.html")
        assert snapshot.source_url == "https://example.com/filing.html"
        assert snapshot.http_status == 200

    def test_download_compliance_403(self, tmp_path):
        """HTTP 403 responses must be raised as ComplianceError.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """

        class ForbiddenConnector(BaseConnector):
            """Mock connector that simulates a 403 forbidden response.."""

            @property
            def source_name(self):
                """Return the fixed source name for this connector.

                Returns:
                    Any: .
                """
                return "forbidden"

            def fetch(self, url, **kwargs):
                """Return a 403 forbidden response.

                Args:
                    url: Any: .
                    **kwargs: Any: .

                Returns:
                    Any: .
                """
                return b"forbidden", "text/html", 403

        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="forbidden", source_type="web", default_level=SourceLevel.L4),
            connector=ForbiddenConnector(),
        )
        store = SnapshotStore(base_dir=tmp_path)
        downloader = Downloader(registry, store)

        with pytest.raises(ComplianceError, match="403"):
            downloader.download("forbidden", "https://paywall.com")

    def test_download_failure(self, tmp_path):
        """Network failures must be raised as DownloadError.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """

        class FailConnector(BaseConnector):
            """Mock connector that raises a network error.."""

            @property
            def source_name(self):
                """Return the fixed source name for this connector.

                Returns:
                    Any: .
                """
                return "fail"

            def fetch(self, url, **kwargs):
                """Simulate a connection failure.

                Args:
                    url: Any: .
                    **kwargs: Any: .

                Returns:
                    Any: .
                """
                raise ConnectionError("network down")

        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="fail", source_type="web", default_level=SourceLevel.L4),
            connector=FailConnector(),
        )
        store = SnapshotStore(base_dir=tmp_path)
        downloader = Downloader(registry, store)

        with pytest.raises(DownloadError, match="network down"):
            downloader.download("fail", "https://example.com")

    def test_download_rejects_non_success_status_without_snapshot(self, tmp_path):
        """Non-2xx responses must fail before an error page is persisted as evidence.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """

        class NotFoundConnector(BaseConnector):
            """A connector that simulates a 404 response.."""

            @property
            def source_name(self):
                """Return the source name.

                Returns:
                    Any: .
                """
                return "missing"

            def fetch(self, url, **kwargs):
                """Fetch a URL and return content with status code.

                Args:
                    url: Any: .
                    **kwargs: Any: .

                Returns:
                    Any: .
                """
                return b"not found", "text/html", 404

        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="missing", source_type="web", default_level=SourceLevel.L4),
            connector=NotFoundConnector(),
        )
        downloader = Downloader(registry, SnapshotStore(base_dir=tmp_path))

        with pytest.raises(DownloadError, match="404"):
            downloader.download("missing", "https://example.com/missing")
        assert list(tmp_path.iterdir()) == []

    def test_http_connector_accepts_explicit_timeout_once(self, monkeypatch):
        """Passing timeout must not send the keyword twice to requests.

        Args:
            monkeypatch: Any: .

        Returns:
            Any: .
        """
        captured = {}

        class Response:
            """Minimal fake HTTP response with fixed content and headers.."""

            content = b"ok"
            status_code = 200
            headers = {"Content-Type": "text/plain"}

        def fake_get(url, **kwargs):
            """Record request kwargs and return a fake response.

            Args:
                url: Any: .
                **kwargs: Any: .

            Returns:
                Any: .
            """
            captured.update(kwargs)
            return Response()

        monkeypatch.setattr("requests.get", fake_get)

        from margin.news.acquirer import HTTPConnector

        HTTPConnector().fetch("https://example.com", timeout=1)
        assert captured["timeout"] == 1


class TestDocumentParser:
    """Tests for HTML/text/JSON parsing.."""

    def test_parse_html(self, tmp_path):
        """HTML snapshots must be parsed into title and body content.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        store = SnapshotStore(base_dir=tmp_path)
        html = (
            "<html><head><title>公司公告</title></head>"
            "<body><p>000001.SZ 经营业绩</p></body></html>"
        ).encode()
        snapshot = store.save("url", html, "text/html")

        parsed = DocumentParser.parse(snapshot, html)
        assert parsed["title"] == "公司公告"
        assert "经营业绩" in parsed["content"]

    def test_parse_text(self, tmp_path):
        """Plain text snapshots must expose their content when parsed.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        store = SnapshotStore(base_dir=tmp_path)
        text = "简单文本内容".encode()
        snapshot = store.save("url", text, "text/plain")

        parsed = DocumentParser.parse(snapshot, text)
        assert "简单文本" in parsed["content"]

    def test_parse_json(self, tmp_path):
        """JSON snapshots must be parsed into title and content fields.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        store = SnapshotStore(base_dir=tmp_path)
        json_content = '{"title": "公告", "content": "正文"}'.encode()
        snapshot = store.save("url", json_content, "application/json")

        parsed = DocumentParser.parse(snapshot, json_content)
        assert parsed["title"] == "公告"


class TestSecurityMapper:
    """Tests for security symbol extraction.."""

    def test_map_sz_symbol(self):
        """Shenzhen symbols in text must be extracted.

        Returns:
            Any: .
        """
        symbols = SecurityMapper.map_symbols("关于 000001.SZ 的公告")
        assert "000001.SZ" in symbols

    def test_map_sh_symbol(self):
        """Shanghai symbols in text must be extracted.

        Returns:
            Any: .
        """
        symbols = SecurityMapper.map_symbols("600000.SH 年报披露")
        assert "600000.SH" in symbols

    def test_map_multiple(self):
        """Multiple symbols in the same text must all be extracted.

        Returns:
            Any: .
        """
        symbols = SecurityMapper.map_symbols("000001.SZ 和 600000.SH 的联合公告")
        assert "000001.SZ" in symbols
        assert "600000.SH" in symbols

    def test_map_none(self):
        """Text without symbols must produce an empty list.

        Returns:
            Any: .
        """
        symbols = SecurityMapper.map_symbols("没有代码的标题")
        assert symbols == []

    def test_map_from_content(self):
        """Symbols in optional content must also be extracted.

        Returns:
            Any: .
        """
        symbols = SecurityMapper.map_symbols("公告", "相关证券：000001.SZ")
        assert "000001.SZ" in symbols


class TestFilingAcquirer:
    """Tests for the filing acquirer orchestrator.."""

    def test_acquire_success(self, tmp_path):
        """A successful acquire must build an event with metadata and symbols.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="sse", source_type="exchange", default_level=SourceLevel.L1),
            connector=TestMockConnector(),
        )
        store = SnapshotStore(base_dir=tmp_path)
        acquirer = FilingAcquirer(registry, store)

        event = acquirer.acquire("sse", "https://example.com/filing.html")
        assert event.source_name == "sse"
        assert event.source_level == SourceLevel.L1
        assert event.title == "Test Filing"
        assert "000001.SZ" in event.symbols
        assert event.snapshot_id is not None

    def test_acquire_batch(self, tmp_path):
        """Batch acquire must return one event per input URL.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """
        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="mock", source_type="exchange", default_level=SourceLevel.L1),
            connector=TestMockConnector(),
        )
        store = SnapshotStore(base_dir=tmp_path)
        acquirer = FilingAcquirer(registry, store)

        events = acquirer.acquire_batch(
            "mock",
            ["https://example.com/1", "https://example.com/2"],
        )
        assert len(events) == 2

    def test_acquire_skips_failed(self, tmp_path):
        """Batch acquire must omit events for URLs that fail to download.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """

        class FailConnector(BaseConnector):
            """Mock connector that always raises a connection error.."""

            @property
            def source_name(self):
                """Return the fixed source name for this connector.

                Returns:
                    Any: .
                """
                return "fail"

            def fetch(self, url, **kwargs):
                """Simulate a connection failure.

                Args:
                    url: Any: .
                    **kwargs: Any: .

                Returns:
                    Any: .
                """
                raise ConnectionError("down")

        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="fail", source_type="web", default_level=SourceLevel.L4),
            connector=FailConnector(),
        )
        store = SnapshotStore(base_dir=tmp_path)
        acquirer = FilingAcquirer(registry, store)

        events = acquirer.acquire_batch("fail", ["https://example.com"])
        assert len(events) == 0

    def test_parse_failure_preserves_snapshot_but_blocks_state_change(self, tmp_path):
        """A preserved raw snapshot must not make an unparsed filing actionable.

        Args:
            tmp_path: Any: .

        Returns:
            Any: .
        """

        class FailingParser:
            """Fake parser that always raises ``ParseError``.."""

            def parse(self, snapshot):
                """Reject every snapshot with a parse error.

                Args:
                    snapshot: Any: .

                Returns:
                    Any: .
                """
                raise ParseError("cannot parse")

        registry = SourceRegistry()
        registry.register(
            SourceDescriptor(name="mock", source_type="exchange", default_level=SourceLevel.L1),
            connector=TestMockConnector(),
        )
        acquirer = FilingAcquirer(
            registry,
            SnapshotStore(base_dir=tmp_path),
            parser=FailingParser(),
        )

        event = acquirer.acquire("mock", "https://example.com/filing")

        assert event.snapshot_id is not None
        assert event.processing_status.value == "parse_failed"
        assert event.can_change_research_state is False
