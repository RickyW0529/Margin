"""Source registry and filing acquirer — Source Registry + Connector + Downloader + Snapshot.

Corresponds to specs 03 §3 interface contract and architecture §6.2 acquisition components.
Corresponds to plans 0301:
  0301.1 Source Registry and Connector
  0301.2 Scheduler and Downloader
  0301.3 Snapshot and format detection
  0301.4 Body/table parsing and security mapping
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

from margin.news.models import (
    DocumentEvent,
    DocumentStatus,
    RawSnapshot,
    SourceDescriptor,
    compute_content_hash,
    make_document_event,
    utc_now,
)

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DownloadError(Exception):
    """Raised when a download fails."""


class ParseError(Exception):
    """Raised when parsing a document fails."""


class SourceNotFoundError(KeyError):
    """Raised when a requested source is not registered in the registry."""


class ComplianceError(Exception):
    """Raised when a compliance boundary is hit (robots/paywall/copyright restrictions)."""


# ---------------------------------------------------------------------------
# 0301.1 Connector protocol
# ---------------------------------------------------------------------------


class BaseConnector(ABC):
    """Abstract base class for source connectors (architecture §6.2 Connector).

    Subclasses implement the `fetch` method to return raw content.
    Supports sources such as APIs, RSS feeds, web pages, and files.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the human-readable name of the data source."""

    @abstractmethod
    def fetch(self, url: str, **kwargs: Any) -> tuple[bytes, str, int]:
        """Fetch raw content from the given URL.

        Args:
            url: Target URL to fetch.
            **kwargs: Additional arguments forwarded to the underlying transport.

        Returns:
            A tuple of (raw bytes, content_type, http_status).
        """


class HTTPConnector(BaseConnector):
    """Generic HTTP connector.

    In the MVP, uses `requests` or `urllib` to fetch public pages.
    Does not bypass robots.txt, login walls, paywalls, or anti-scraping
    mechanisms (architecture §6.2.1).
    """

    def __init__(self, name: str = "http") -> None:
        self._name = name

    @property
    def source_name(self) -> str:
        """Return the connector's source name."""
        return self._name

    def fetch(self, url: str, **kwargs: Any) -> tuple[bytes, str, int]:
        """Fetch the URL using requests when available, falling back to urllib.

        Args:
            url: Target URL to fetch.
            **kwargs: Additional arguments passed to the HTTP request.

        Returns:
            A tuple of (raw bytes, content_type, http_status).
        """
        try:
            import requests
        except ImportError:
            return self._fetch_urllib(url)

        request_kwargs = dict(kwargs)
        timeout = request_kwargs.pop("timeout", 30)
        resp = requests.get(url, timeout=timeout, **request_kwargs)
        content_type = resp.headers.get("Content-Type", "text/html")
        return resp.content, content_type, resp.status_code

    def _fetch_urllib(self, url: str) -> tuple[bytes, str, int]:
        """Fetch the URL using urllib as a fallback.

        Args:
            url: Target URL to fetch.

        Returns:
            A tuple of (raw bytes, content_type, http_status).
        """
        from urllib.request import Request, urlopen

        req = Request(url, headers={"User-Agent": "Margin/0.1"})
        with urlopen(req, timeout=30) as resp:
            content = resp.read()
            content_type = resp.headers.get("Content-Type", "text/html")
            return content, content_type, resp.status


# ---------------------------------------------------------------------------
# 0301.1 Source Registry
# ---------------------------------------------------------------------------


class SourceRegistry:
    """Registry for source descriptors and their connectors (architecture §6.2 Source Registry).

    Manages source descriptors and the connectors used to fetch them.
    """

    def __init__(self) -> None:
        self._sources: dict[str, SourceDescriptor] = {}
        self._connectors: dict[str, BaseConnector] = {}

    def register(
        self,
        descriptor: SourceDescriptor,
        connector: BaseConnector | None = None,
    ) -> None:
        """Register a source descriptor and an optional connector.

        Args:
            descriptor: Metadata describing the source.
            connector: Connector used to fetch from the source, if any.
        """
        self._sources[descriptor.name] = descriptor
        if connector is not None:
            self._connectors[descriptor.name] = connector

    def get(self, name: str) -> SourceDescriptor:
        """Return the descriptor for the named source.

        Args:
            name: Source identifier.

        Returns:
            The registered source descriptor.

        Raises:
            SourceNotFoundError: If the source is not registered.
        """
        if name not in self._sources:
            raise SourceNotFoundError(f"Source '{name}' not registered")
        return self._sources[name]

    def get_connector(self, name: str) -> BaseConnector | None:
        """Return the connector registered for the named source, if any.

        Args:
            name: Source identifier.

        Returns:
            The connector, or None if no connector was registered.
        """
        return self._connectors.get(name)

    def list_sources(self) -> list[str]:
        """Return a list of all registered source names.

        Returns:
            List of source identifiers.
        """
        return list(self._sources.keys())

    def list_by_type(self, source_type: str) -> list[str]:
        """Return source names filtered by source type.

        Args:
            source_type: Type of source to filter by.

        Returns:
            List of source identifiers matching the requested type.
        """
        return [
            name for name, s in self._sources.items()
            if s.source_type == source_type
        ]


# ---------------------------------------------------------------------------
# 0301.2 / 0301.3 Downloader + Snapshot
# ---------------------------------------------------------------------------


class SnapshotStore:
    """Storage for immutable raw snapshots (architecture §6.2 Snapshot).

    In the MVP, snapshots are persisted to the local file system.
    Each snapshot records a content hash and is immutable once stored.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base_dir = base_dir or Path.home() / ".margin" / "snapshots"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def save(
        self,
        source_url: str,
        content: bytes,
        content_type: str,
        http_status: int | None = None,
    ) -> RawSnapshot:
        """Persist a raw content snapshot and return its metadata.

        Args:
            source_url: Original URL the content was fetched from.
            content: Raw byte content to persist.
            content_type: MIME type or extension hint for the content.
            http_status: Optional HTTP status code from the download.

        Returns:
            A RawSnapshot describing the persisted snapshot.
        """
        import uuid

        content_hash = compute_content_hash(content)
        ext = self._detect_extension(content_type)
        snapshot_id = f"snp_{uuid.uuid4().hex[:12]}"
        filename = f"{snapshot_id}.{ext}"
        file_path = self._base_dir / filename
        file_path.write_bytes(content)

        return RawSnapshot(
            snapshot_id=snapshot_id,
            source_url=source_url,
            content_hash=content_hash,
            content_type=ext,
            raw_size=len(content),
            storage_path=str(file_path),
            downloaded_at=utc_now(),
            http_status=http_status,
        )

    def read(self, snapshot_id: str, content_type: str) -> bytes | None:
        """Read the raw bytes of a previously saved snapshot.

        Args:
            snapshot_id: Unique snapshot identifier.
            content_type: File extension used when the snapshot was saved.

        Returns:
            The snapshot bytes, or None if the snapshot file does not exist.
        """
        file_path = self._base_dir / f"{snapshot_id}.{content_type}"
        if file_path.is_file():
            return file_path.read_bytes()
        return None

    def read_snapshot(self, snapshot: RawSnapshot) -> bytes | None:
        """Read a snapshot using its immutable metadata."""
        return self.read(snapshot.snapshot_id, snapshot.content_type)

    def delete(self, snapshot: RawSnapshot) -> None:
        """Delete a snapshot rejected by compliance checks."""
        if snapshot.storage_path is None:
            return
        path = Path(snapshot.storage_path)
        if path.is_file():
            path.unlink()

    @staticmethod
    def _detect_extension(content_type: str) -> str:
        """Map a content type string to a canonical file extension.

        Args:
            content_type: Content-Type header value or MIME string.

        Returns:
            Canonical extension such as pdf, html, json, csv, xml, or txt.
        """
        ct = content_type.lower()
        if "pdf" in ct:
            return "pdf"
        if "html" in ct:
            return "html"
        if "json" in ct:
            return "json"
        if "csv" in ct:
            return "csv"
        if "xml" in ct:
            return "xml"
        return "txt"


class Downloader:
    """Downloader that fetches raw content through a connector and stores snapshots.

    Uses a connector to fetch content and persists it through SnapshotStore.
    Respects compliance boundaries: does not bypass robots.txt, login walls,
    or paywalls.
    """

    def __init__(
        self,
        registry: SourceRegistry,
        snapshot_store: SnapshotStore,
    ) -> None:
        self._registry = registry
        self._snapshot_store = snapshot_store

    def download(
        self,
        source_name: str,
        url: str,
        **kwargs: Any,
    ) -> RawSnapshot:
        """Download a URL from a registered source and persist a snapshot.

        Args:
            source_name: Identifier of the registered source.
            url: Target URL to download.
            **kwargs: Additional arguments forwarded to the connector.

        Returns:
            A RawSnapshot describing the persisted content.

        Raises:
            SourceNotFoundError: If the source is not registered.
            DownloadError: If the download fails.
            ComplianceError: If a compliance boundary is triggered.
        """
        self._registry.get(source_name)
        connector = self._registry.get_connector(source_name)
        if connector is None:
            connector = HTTPConnector(source_name)

        try:
            content, content_type, status = connector.fetch(url, **kwargs)
        except Exception as exc:
            raise DownloadError(f"Failed to download '{url}': {exc}") from exc

        if status in (401, 403):
            raise ComplianceError(
                f"Access denied (HTTP {status}) for '{url}': "
                "possible login wall or paywall — not bypassed"
            )
        if status < 200 or status >= 300:
            raise DownloadError(f"Failed to download '{url}': HTTP {status}")
        if not content:
            raise DownloadError(f"Failed to download '{url}': empty response body")

        return self._snapshot_store.save(
            source_url=url,
            content=content,
            content_type=content_type,
            http_status=status,
        )


# ---------------------------------------------------------------------------
# 0301.4 Document parsing and security mapping
# ---------------------------------------------------------------------------


class DocumentParser:
    """Document parser (architecture §6.3 format detection -> body/table parsing).

    Supports PDF, HTML, and plain text formats.
    On parse failures, preserves the raw snapshot and records a note instead of
    silently dropping the document (architecture §25).
    """

    @staticmethod
    def parse(snapshot: RawSnapshot, content: bytes | None = None) -> dict[str, Any]:
        """Parse a snapshot's content and return structured fields.

        Args:
            snapshot: Snapshot metadata including content type and storage path.
            content: Optional raw bytes; if omitted, read from storage_path.

        Returns:
            A dictionary containing title, content, and doc_type.

        Raises:
            ParseError: If parsing fails.
        """
        ct = snapshot.content_type

        if ct == "html":
            return DocumentParser._parse_html(snapshot, content)
        if ct == "pdf":
            return DocumentParser._parse_pdf(snapshot, content)
        if ct in ("json", "csv", "xml"):
            return DocumentParser._parse_structured(snapshot, content)
        return DocumentParser._parse_text(snapshot, content)

    @staticmethod
    def _parse_html(snapshot: RawSnapshot, content: bytes | None = None) -> dict[str, Any]:
        """Parse HTML and extract title and body text.

        Args:
            snapshot: Snapshot metadata including content type and storage path.
            content: Optional raw bytes; if omitted, read from storage_path.

        Returns:
            A dictionary containing title, content, and doc_type.

        Raises:
            ParseError: If HTML parsing fails.
        """
        try:
            from html.parser import HTMLParser

            raw = content or b""
            if not raw and snapshot.storage_path:
                raw = Path(snapshot.storage_path).read_bytes()
            text = raw.decode("utf-8", errors="replace")

            title = DocumentParser._extract_html_title(text)

            class TextExtractor(HTMLParser):
                """Extract visible body text while ignoring script/style tags."""

                def __init__(self):
                    super().__init__()
                    self._in_body = False
                    self._in_script = False
                    self._text_parts: list[str] = []

                def handle_starttag(self, tag, attrs):
                    """Track when the parser enters body/script/style tags."""
                    if tag == "body":
                        self._in_body = True
                    if tag in ("script", "style"):
                        self._in_script = True

                def handle_endtag(self, tag):
                    """Track when the parser exits body/script/style tags."""
                    if tag == "body":
                        self._in_body = False
                    if tag in ("script", "style"):
                        self._in_script = False

                def handle_data(self, data):
                    """Collect non-empty text segments inside the body tag."""
                    if self._in_body and not self._in_script:
                        stripped = data.strip()
                        if stripped:
                            self._text_parts.append(stripped)

            extractor = TextExtractor()
            extractor.feed(text)
            body_text = "\n".join(extractor._text_parts)

            return {
                "title": title or snapshot.source_url,
                "content": body_text[:50000],
                "doc_type": "filing" if "公告" in title else "news",
            }
        except Exception as exc:
            raise ParseError(f"HTML parse failed: {exc}") from exc

    @staticmethod
    def _parse_pdf(snapshot: RawSnapshot, content: bytes | None = None) -> dict[str, Any]:
        """Parse PDF content, falling back to a placeholder if pymupdf is missing.

        Args:
            snapshot: Snapshot metadata including content type and storage path.
            content: Optional raw bytes; if omitted, read from storage_path.

        Returns:
            A dictionary containing title, content, doc_type, and optionally a
            parse_note when the PDF library is unavailable.
        """
        raw = content or b""
        if not raw and snapshot.storage_path:
            raw = Path(snapshot.storage_path).read_bytes()

        try:
            import pymupdf as fitz  # noqa: F401

            doc = fitz.open(stream=raw, filetype="pdf")
            text_parts: list[str] = []
            for page in doc:
                text_parts.append(page.get_text())
            full_text = "\n".join(text_parts)
            title = full_text[:200].split("\n")[0] if full_text else snapshot.source_url
            return {
                "title": title.strip(),
                "content": full_text[:50000],
                "doc_type": "filing",
            }
        except ImportError:
            return {
                "title": snapshot.source_url,
                "content": "",
                "doc_type": "filing",
                "parse_note": "PDF parsing requires pymupdf; raw snapshot preserved",
            }

    @staticmethod
    def _parse_structured(snapshot: RawSnapshot, content: bytes | None = None) -> dict[str, Any]:
        """Parse structured data formats such as JSON, CSV, or XML.

        Args:
            snapshot: Snapshot metadata including content type and storage path.
            content: Optional raw bytes; if omitted, read from storage_path.

        Returns:
            A dictionary containing title, content, and doc_type.
        """
        import json

        raw = content or b""
        if not raw and snapshot.storage_path:
            raw = Path(snapshot.storage_path).read_bytes()
        text = raw.decode("utf-8", errors="replace")

        try:
            data = json.loads(text)
            title = data.get("title", data.get("name", snapshot.source_url))
            content_str = json.dumps(data, ensure_ascii=False, indent=2)
            return {
                "title": str(title),
                "content": content_str[:50000],
                "doc_type": "filing",
            }
        except (json.JSONDecodeError, ValueError):
            return {
                "title": snapshot.source_url,
                "content": text[:50000],
                "doc_type": "filing",
            }

    @staticmethod
    def _parse_text(snapshot: RawSnapshot, content: bytes | None = None) -> dict[str, Any]:
        """Parse plain text content.

        Args:
            snapshot: Snapshot metadata including content type and storage path.
            content: Optional raw bytes; if omitted, read from storage_path.

        Returns:
            A dictionary containing title, content, and doc_type.
        """
        raw = content or b""
        if not raw and snapshot.storage_path:
            raw = Path(snapshot.storage_path).read_bytes()
        text = raw.decode("utf-8", errors="replace")
        title = text[:200].split("\n")[0] if text else snapshot.source_url
        return {
            "title": title.strip(),
            "content": text[:50000],
            "doc_type": "news",
        }

    @staticmethod
    def _extract_html_title(html: str) -> str:
        """Extract the content of the HTML <title> tag.

        Args:
            html: HTML source text.

        Returns:
            The title string, or an empty string if no title tag is found.
        """
        lower = html.lower()
        start = lower.find("<title>")
        if start < 0:
            return ""
        end = lower.find("</title>", start)
        if end < 0:
            return ""
        return html[start + 7 : end].strip()


class SecurityMapper:
    """Security entity mapper (architecture §6.3 security entity mapping).

    Identifies security codes in a document title and body, mapping them to
    standardized symbols.
    """

    CODE_PATTERNS = [
        r"\b(\d{6})\.SZ\b",
        r"\b(\d{6})\.SH\b",
        r"\bSZ(\d{6})\b",
        r"\bSH(\d{6})\b",
        r"\b(\d{6})\b",
    ]

    @staticmethod
    def map_symbols(title: str, content: str | None = None) -> list[str]:
        """Identify security codes in the title and body, returning standardized symbols.

        Args:
            title: Document title.
            content: Document body text, if available.

        Returns:
            Sorted list of normalized security symbols.
        """
        import re

        from margin.data.standardize import normalize_symbol

        text = f"{title} {content or ''}"
        found: set[str] = set()

        for pattern in SecurityMapper.CODE_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                normalized = normalize_symbol(match)
                if "." in normalized:
                    found.add(normalized)

        return sorted(found)


# ---------------------------------------------------------------------------
# 0301 Integration: Filing Acquirer
# ---------------------------------------------------------------------------


class FilingAcquirer:
    """Filing acquirer integrating Source Registry, Downloader, Snapshot, Parser, and Mapper.

    Corresponds to architecture §6.3 document processing pipeline:
      discover URL/API record -> download raw text -> save raw snapshot -> format detection
      -> body/table parsing -> deduplication -> security entity mapping -> time and source level
      -> enqueue for vectorization

    Example:
        registry = SourceRegistry()
        registry.register(SourceDescriptor(name="sse", ...))
        acquirer = FilingAcquirer(registry, snapshot_store)
        event = acquirer.acquire("sse", "https://...")
    """

    def __init__(
        self,
        registry: SourceRegistry,
        snapshot_store: SnapshotStore,
        parser: DocumentParser | None = None,
        security_mapper: SecurityMapper | None = None,
    ) -> None:
        self._registry = registry
        self._downloader = Downloader(registry, snapshot_store)
        self._parser = parser or DocumentParser()
        self._mapper = security_mapper or SecurityMapper()

    def acquire(
        self,
        source_name: str,
        url: str,
        title_override: str | None = None,
        published_at: datetime | None = None,
        **kwargs: Any,
    ) -> DocumentEvent:
        """Acquire a single URL and return a normalized document event.

        Pipeline: download -> snapshot -> parse -> security mapping -> publish document event.

        Args:
            source_name: Identifier of the registered source.
            url: Target URL to acquire.
            title_override: Optional title to override the parsed title.
            published_at: Optional publication timestamp.
            **kwargs: Additional arguments forwarded to the downloader.

        Returns:
            A DocumentEvent containing metadata, content, and mapped symbols.

        Raises:
            DownloadError: If the download fails.
            ParseError: If parsing fails (the snapshot is still preserved).
            ComplianceError: If a compliance boundary is triggered.
        """
        descriptor = self._registry.get(source_name)
        snapshot = self._downloader.download(source_name, url, **kwargs)

        processing_status = DocumentStatus.READY
        processing_error = None
        try:
            parsed = self._parser.parse(snapshot)
        except ParseError:
            parsed = {
                "title": title_override or url,
                "content": None,
                "doc_type": "filing",
                "parse_note": "parse failed, raw snapshot preserved",
            }
            processing_status = DocumentStatus.PARSE_FAILED
            processing_error = parsed["parse_note"]

        if parsed.get("parse_note"):
            processing_status = DocumentStatus.PARSE_FAILED
            processing_error = parsed["parse_note"]

        title = title_override or parsed.get("title", url)
        content = parsed.get("content")
        doc_type = parsed.get("doc_type", "filing")

        symbols = self._mapper.map_symbols(title, content)

        event = make_document_event(
            source_url=url,
            source_name=source_name,
            source_level=descriptor.default_level,
            title=title,
            content=content,
            content_hash=compute_content_hash(content or title),
            symbols=symbols,
            doc_type=doc_type,
            published_at=published_at,
            available_at=snapshot.downloaded_at,
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.content_hash,
            processing_status=processing_status,
            processing_error=processing_error,
        )
        return event

    def acquire_batch(
        self,
        source_name: str,
        urls: list[str],
        **kwargs: Any,
    ) -> list[DocumentEvent]:
        """Acquire a batch of URLs, skipping URLs that fail to download.

        Args:
            source_name: Identifier of the registered source.
            urls: List of target URLs to acquire.
            **kwargs: Additional arguments forwarded to `acquire`.

        Returns:
            List of successfully acquired DocumentEvent objects.
        """
        events: list[DocumentEvent] = []
        for url in urls:
            try:
                event = self.acquire(source_name, url, **kwargs)
                events.append(event)
            except (DownloadError, ComplianceError):
                continue
        return events
