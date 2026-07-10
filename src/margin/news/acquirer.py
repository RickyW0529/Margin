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
from urllib.parse import urljoin, urlparse

from margin.core.ssrf import SSRFError, assert_public_http_url
from margin.documents.pipeline import DocumentNormalizationPipeline, DocumentPipelineRequest
from margin.news.models import (
    DocumentEvent,
    DocumentStatus,
    RawSnapshot,
    SourceDescriptor,
    compute_content_hash,
    make_document_event,
    utc_now,
)
from margin.settings import get_settings

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DownloadError(Exception):
    """Raised when a download fails.."""


class ParseError(Exception):
    """Raised when parsing a document fails.."""


class SourceNotFoundError(KeyError):
    """Raised when a requested source is not registered in the registry.."""


class ComplianceError(Exception):
    """Raised when a compliance boundary is hit (robots/paywall/copyright restrictions).."""


# ---------------------------------------------------------------------------
# 0301.1 Connector protocol
# ---------------------------------------------------------------------------


class BaseConnector(ABC):
    """Abstract base class for source connectors (architecture §6.2 Connector).."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the human-readable name of the data source.

        Returns:
            str: .
        """

    @abstractmethod
    def fetch(self, url: str, **kwargs: Any) -> tuple[bytes, str, int]:
        """Fetch raw content from the given URL.

        Args:
            url: str: .
            **kwargs: Any: .

        Returns:
            tuple[bytes, str, int]: .
        """


class HTTPConnector(BaseConnector):
    """Generic HTTP connector with SSRF guards on every fetch."""

    def __init__(
        self,
        name: str = "http",
        *,
        allow_local: bool | None = None,
        resolve_dns: bool | None = None,
    ) -> None:
        """Initialize the HTTP connector.

        Args:
            name: Connector source name.
            allow_local: Override for local/loopback allowance; defaults to settings.
            resolve_dns: Override for DNS resolution; defaults to settings.
        """
        self._name = name
        self._allow_local = allow_local
        self._resolve_dns = resolve_dns

    @property
    def source_name(self) -> str:
        """Return the connector's source name.

        Returns:
            str: .
        """
        return self._name

    def fetch(self, url: str, **kwargs: Any) -> tuple[bytes, str, int]:
        """Fetch the URL using requests when available, falling back to urllib.

        Args:
            url: Absolute http(s) URL.
            **kwargs: Forwarded to the underlying HTTP client.

        Returns:
            tuple[bytes, str, int]: Body, content-type, status code.

        Raises:
            DownloadError: When the URL fails SSRF checks or the request fails.
        """
        try:
            self._assert_safe_url(url)
        except SSRFError as exc:
            raise DownloadError(str(exc)) from exc

        request_kwargs = dict(kwargs)
        timeout = request_kwargs.pop("timeout", 30)
        try:
            import requests
        except ImportError:
            return self._fetch_urllib(url, timeout=timeout)

        # Do not follow redirects blindly into private networks.
        request_kwargs.setdefault("allow_redirects", False)
        resp = requests.get(url, timeout=timeout, **request_kwargs)
        if 300 <= resp.status_code < 400:
            location = resp.headers.get("Location")
            if location:
                redirect_url = urljoin(getattr(resp, "url", url) or url, location)
                try:
                    self._assert_safe_url(redirect_url)
                except SSRFError as exc:
                    raise DownloadError(str(exc)) from exc
                resp = requests.get(
                    redirect_url,
                    timeout=timeout,
                    allow_redirects=False,
                    **{k: v for k, v in request_kwargs.items() if k != "allow_redirects"},
                )
        content_type = resp.headers.get("Content-Type", "text/html")
        return resp.content, content_type, resp.status_code

    def _assert_safe_url(self, url: str) -> None:
        """Validate a fetch URL against the shared SSRF policy."""
        settings = get_settings()
        allow_local = (
            self._allow_local
            if self._allow_local is not None
            else settings.allow_local_provider_urls
        )
        resolve_dns = (
            self._resolve_dns if self._resolve_dns is not None else settings.resolve_provider_dns
        )
        assert_public_http_url(
            url,
            allow_local=allow_local,
            resolve_dns=resolve_dns,
        )

    def _fetch_urllib(self, url: str, *, timeout: float | int = 30) -> tuple[bytes, str, int]:
        """Fetch the URL using urllib as a fallback.

        Args:
            url: str: .

        Returns:
            tuple[bytes, str, int]: .
        """
        from urllib.error import HTTPError
        from urllib.request import HTTPRedirectHandler, Request, build_opener

        class _NoRedirect(HTTPRedirectHandler):
            """Disable urllib's implicit redirect handling."""

            def redirect_request(
                self,
                req: Any,
                fp: Any,
                code: int,
                msg: str,
                headers: Any,
                newurl: str,
            ) -> None:
                """Return ``None`` so callers can validate redirect targets."""
                return None

        opener = build_opener(_NoRedirect)
        req = Request(url, headers={"User-Agent": "Margin/0.1"})
        try:
            resp = opener.open(req, timeout=timeout)
        except HTTPError as exc:
            if 300 <= exc.code < 400:
                location = exc.headers.get("Location")
                if location:
                    redirect_url = urljoin(getattr(exc, "url", url) or url, location)
                    try:
                        self._assert_safe_url(redirect_url)
                    except SSRFError as ssrf_exc:
                        raise DownloadError(str(ssrf_exc)) from ssrf_exc
                    redirect_req = Request(redirect_url, headers={"User-Agent": "Margin/0.1"})
                    with opener.open(redirect_req, timeout=timeout) as redirect_resp:
                        return _read_urllib_response(redirect_resp)
            raise
        with resp:
            return _read_urllib_response(resp)


def _read_urllib_response(resp: Any) -> tuple[bytes, str, int]:
    """Read a urllib response into the connector return tuple."""
    content = resp.read()
    content_type = resp.headers.get("Content-Type", "text/html")
    return content, content_type, resp.status


# ---------------------------------------------------------------------------
# 0301.1 Source Registry
# ---------------------------------------------------------------------------


class SourceRegistry:
    """Registry for source descriptors and their connectors (architecture §6.2 Source
    Registry)..
    """

    def __init__(self) -> None:
        """Initialize an empty source registry.

        Returns:
            None: .
        """
        self._sources: dict[str, SourceDescriptor] = {}
        self._connectors: dict[str, BaseConnector] = {}

    def register(
        self,
        descriptor: SourceDescriptor,
        connector: BaseConnector | None = None,
    ) -> None:
        """Register a source descriptor and an optional connector.

        Args:
            descriptor: SourceDescriptor: .
            connector: BaseConnector | None: .

        Returns:
            None: .
        """
        self._sources[descriptor.name] = descriptor
        if connector is not None:
            self._connectors[descriptor.name] = connector

    def get(self, name: str) -> SourceDescriptor:
        """Return the descriptor for the named source.

        Args:
            name: str: .

        Returns:
            SourceDescriptor: .
        """
        if name not in self._sources:
            raise SourceNotFoundError(f"Source '{name}' not registered")
        return self._sources[name]

    def get_connector(self, name: str) -> BaseConnector | None:
        """Return the connector registered for the named source, if any.

        Args:
            name: str: .

        Returns:
            BaseConnector | None: .
        """
        return self._connectors.get(name)

    def list_sources(self) -> list[str]:
        """Return a list of all registered source names.

        Returns:
            list[str]: .
        """
        return list(self._sources.keys())

    def list_by_type(self, source_type: str) -> list[str]:
        """Return source names filtered by source type.

        Args:
            source_type: str: .

        Returns:
            list[str]: .
        """
        return [name for name, s in self._sources.items() if s.source_type == source_type]


# ---------------------------------------------------------------------------
# 0301.2 / 0301.3 Downloader + Snapshot
# ---------------------------------------------------------------------------


class SnapshotStore:
    """Storage for immutable raw snapshots (architecture §6.2 Snapshot).."""

    def __init__(self, base_dir: Path | None = None) -> None:
        """Initialize the snapshot store.

        Args:
            base_dir: Path | None: .

        Returns:
            None: .
        """
        self._base_dir = base_dir or Path(".margin") / "snapshots"
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
            source_url: str: .
            content: bytes: .
            content_type: str: .
            http_status: int | None: .

        Returns:
            RawSnapshot: .
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
            snapshot_id: str: .
            content_type: str: .

        Returns:
            bytes | None: .
        """
        file_path = self._base_dir / f"{snapshot_id}.{content_type}"
        if file_path.is_file():
            return file_path.read_bytes()
        return None

    def read_snapshot(self, snapshot: RawSnapshot) -> bytes | None:
        """Read a snapshot using its immutable metadata.

        Args:
            snapshot: RawSnapshot: .

        Returns:
            bytes | None: .
        """
        return self.read(snapshot.snapshot_id, snapshot.content_type)

    def delete(self, snapshot: RawSnapshot) -> None:
        """Delete a snapshot rejected by compliance checks.

        Args:
            snapshot: RawSnapshot: .

        Returns:
            None: .
        """
        if snapshot.storage_path is None:
            return
        path = Path(snapshot.storage_path)
        if path.is_file():
            path.unlink()

    @staticmethod
    def _detect_extension(content_type: str) -> str:
        """Map a content type string to a canonical file extension.

        Args:
            content_type: str: .

        Returns:
            str: .
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
        if "wordprocessingml" in ct or "msword" in ct:
            return "docx"
        if "spreadsheetml" in ct or "excel" in ct:
            return "xlsx"
        if "presentationml" in ct or "powerpoint" in ct:
            return "pptx"
        if "markdown" in ct:
            return "md"
        if "xml" in ct:
            return "xml"
        return "txt"


class Downloader:
    """Downloader that fetches raw content through a connector and stores snapshots.."""

    def __init__(
        self,
        registry: SourceRegistry,
        snapshot_store: SnapshotStore,
    ) -> None:
        """Initialize the downloader.

        Args:
            registry: SourceRegistry: .
            snapshot_store: SnapshotStore: .

        Returns:
            None: .
        """
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
            source_name: str: .
            url: str: .
            **kwargs: Any: .

        Returns:
            RawSnapshot: .
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
    """Document parser (architecture §6.3 format detection -> body/table parsing).."""

    @staticmethod
    def parse(snapshot: RawSnapshot, content: bytes | None = None) -> dict[str, Any]:
        """Parse a snapshot's content and return structured fields.

        Args:
            snapshot: RawSnapshot: .
            content: bytes | None: .

        Returns:
            dict[str, Any]: .
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
            snapshot: RawSnapshot: .
            content: bytes | None: .

        Returns:
            dict[str, Any]: .
        """
        try:
            from html.parser import HTMLParser

            raw = content or b""
            if not raw and snapshot.storage_path:
                raw = Path(snapshot.storage_path).read_bytes()
            text = raw.decode("utf-8", errors="replace")

            title = DocumentParser._extract_html_title(text)

            class TextExtractor(HTMLParser):
                """Extract visible body text while ignoring script/style tags.."""

                def __init__(self):
                    """Initialize the instance.

                    Returns:
                        Any: .
                    """
                    super().__init__()
                    self._in_body = False
                    self._in_script = False
                    self._text_parts: list[str] = []

                def handle_starttag(self, tag, attrs):
                    """Track when the parser enters body/script/style tags.

                    Args:
                        tag: Any: .
                        attrs: Any: .

                    Returns:
                        Any: .
                    """
                    if tag == "body":
                        self._in_body = True
                    if tag in ("script", "style"):
                        self._in_script = True

                def handle_endtag(self, tag):
                    """Track when the parser exits body/script/style tags.

                    Args:
                        tag: Any: .

                    Returns:
                        Any: .
                    """
                    if tag == "body":
                        self._in_body = False
                    if tag in ("script", "style"):
                        self._in_script = False

                def handle_data(self, data):
                    """Collect non-empty text segments inside the body tag.

                    Args:
                        data: Any: .

                    Returns:
                        Any: .
                    """
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
            snapshot: RawSnapshot: .
            content: bytes | None: .

        Returns:
            dict[str, Any]: .
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
            snapshot: RawSnapshot: .
            content: bytes | None: .

        Returns:
            dict[str, Any]: .
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
            snapshot: RawSnapshot: .
            content: bytes | None: .

        Returns:
            dict[str, Any]: .
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
            html: str: .

        Returns:
            str: .
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
    """Security entity mapper (architecture §6.3 security entity mapping).."""

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
            title: str: .
            content: str | None: .

        Returns:
            list[str]: .
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
    """Filing acquirer integrating Source Registry, Downloader, Snapshot, Parser, and Mapper.."""

    def __init__(
        self,
        registry: SourceRegistry,
        snapshot_store: SnapshotStore,
        parser: DocumentParser | None = None,
        security_mapper: SecurityMapper | None = None,
        normalization_pipeline: Any | None = None,
    ) -> None:
        """Initialize the filing acquirer.

        Args:
            registry: SourceRegistry: .
            snapshot_store: SnapshotStore: .
            parser: DocumentParser | None: .
            security_mapper: SecurityMapper | None: .
            normalization_pipeline: Shared canonical document normalization pipeline.

        Returns:
            None: .
        """
        self._registry = registry
        self._downloader = Downloader(registry, snapshot_store)
        self._snapshot_store = snapshot_store
        self._legacy_parser = parser
        self._normalization_pipeline = normalization_pipeline or DocumentNormalizationPipeline()
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

        Args:
            source_name: str: .
            url: str: .
            title_override: str | None: .
            published_at: datetime | None: .
            **kwargs: Any: .

        Returns:
            DocumentEvent: .
        """
        descriptor = self._registry.get(source_name)
        snapshot = self._downloader.download(source_name, url, **kwargs)
        document_id = _document_id_for_snapshot(snapshot.snapshot_id)

        processing_status = DocumentStatus.READY
        processing_error = None
        try:
            if self._legacy_parser is not None:
                parsed = self._legacy_parser.parse(snapshot)
            else:
                raw_content = self._snapshot_store.read_snapshot(snapshot)
                if raw_content is None:
                    raise ParseError("raw snapshot content is unavailable")
                normalized = self._normalization_pipeline.normalize(
                    DocumentPipelineRequest(
                        document_id=document_id,
                        content=raw_content,
                        source_url=url,
                        content_type=snapshot.content_type,
                        filename=Path(urlparse(url).path).name or None,
                    )
                )
                if normalized.conversion.parse_status != "ready" or not normalized.final_markdown:
                    reason = ",".join(normalized.conversion.warnings) or "normalization_failed"
                    raise ParseError(reason)
                parsed = {
                    "title": _title_from_markdown(normalized.final_markdown, url),
                    "content": normalized.final_markdown,
                    "doc_type": "filing",
                }
        except Exception as exc:  # noqa: BLE001 - parser failures must preserve the raw snapshot
            parsed = {
                "title": title_override or url,
                "content": None,
                "doc_type": "filing",
                "parse_note": f"parse failed, raw snapshot preserved: {exc}",
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
            document_id=document_id,
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
            source_name: str: .
            urls: list[str]: .
            **kwargs: Any: .

        Returns:
            list[DocumentEvent]: .
        """
        events: list[DocumentEvent] = []
        for url in urls:
            try:
                event = self.acquire(source_name, url, **kwargs)
                events.append(event)
            except (DownloadError, ComplianceError):
                continue
        return events


def _document_id_for_snapshot(snapshot_id: str) -> str:
    """Return a stable canonical document ID for one immutable snapshot."""
    return f"doc_{snapshot_id}"


def _title_from_markdown(markdown: str, fallback: str) -> str:
    """Extract a readable title from canonical Markdown."""
    for line in markdown.splitlines():
        value = line.strip()
        if value.startswith("#"):
            title = value.lstrip("# ").strip()
            if title:
                return title
    for line in markdown.splitlines():
        title = line.strip().lstrip("# ").strip()
        if title:
            return title[:500]
    return fallback
