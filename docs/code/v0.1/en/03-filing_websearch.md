# Module 03 - Filing & WebSearch (`margin.news`)

## Table of Contents

1. [Module Overview](#module-overview)
2. [File-Level Summaries](#file-level-summaries)
3. [Domain Models](#domain-models)
4. [Acquisition Layer](#acquisition-layer)
5. [Web Search Layer](#web-search-layer)
6. [Deduplication & Compliance Grading](#deduplication--compliance-grading)
7. [Repository & Outbox](#repository--outbox)
8. [Structured Parsing](#structured-parsing)
9. [Robots.txt Compliance](#robotstxt-compliance)
10. [Cross-Module Usage Notes](#cross-module-usage-notes)

---

## Module Overview

The `margin.news` package (also referred to as Module 03, "Filing & WebSearch") is responsible for discovering, downloading, normalizing, deduplicating, and staging external documents before they are consumed by downstream research, vectorization, and portfolio monitoring pipelines.

It implements the acquisition, web search, deduplication, and source-leveling requirements defined in Margin v0.1 architecture section 6 and the 0301/0302/0303 plans.

### Responsibilities

| Responsibility | Description |
| --- | --- |
| Source management | Register sources, assign default trust levels, and bind connectors that fetch raw content. |
| Incremental discovery | Discover URLs/API records from exchange announcement connectors and resume safely using persisted cursors. |
| Download & snapshot | Download original content through connectors and persist immutable raw snapshots with content hashes. |
| Format detection & parsing | Detect content type (PDF, HTML, JSON, CSV, XML, text) and extract title, body text, and structured blocks. |
| Security mapping | Extract security symbols from titles and body text using exchange code patterns. |
| Web search | Execute user-configured web searches, persist query audit records, and verify accessible original content. |
| Compliance enforcement | Respect robots.txt, reject paywalled or blocked content, and refuse to bypass login walls or anti-scraping mechanisms. |
| Deduplication | Detect duplicates by URL, content hash, title/date, SimHash, vector similarity, and repost-chain detection. |
| Quality scoring | Score events on authority, completeness, timeliness, and uniqueness. |
| Persistence | Store cursors, snapshots, document events, search records, duplicate decisions, repost edges, and outbox messages in PostgreSQL. |
| Outbox publishing | Enqueue ready document events for vector indexing via a transactional outbox. |

### Pipeline Flow

1. Discover a URL or API record.
2. Download the original content.
3. Persist an immutable raw snapshot.
4. Identify the format.
5. Extract body text and tables.
6. Deduplicate against existing records.
7. Map securities entities.
8. Assign timestamps and source level.
9. Publish a `DocumentEvent` to the vectorization queue.

---

## File-Level Summaries

| File | Purpose |
| --- | --- |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/__init__.py` | Package exports. Re-exports public classes and functions from acquisition, deduplication, models, and web search modules. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/acquirer.py` | Source registry, connectors, downloader, snapshot store, document parser, security mapper, and the `FilingAcquirer` integration class. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/connectors.py` | Fixture-testable adapters for SSE and SZSE announcement discovery. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/db_models.py` | SQLAlchemy ORM models for cursors, snapshots, document events, outbox, search records, dedup records, and repost edges. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/dedup.py` | Multi-layer deduplication (URL, hash, title/date, SimHash, vector similarity, repost chains) and L1-L5 quality scoring. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/discovery.py` | `DiscoveredDocument` model and `DiscoveryConnector` protocol for incremental source discovery. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/models.py` | Core domain models: `SourceLevel`, `DocumentStatus`, `RawSnapshot`, `DocumentEvent`, `SourceDescriptor`, and factory helpers. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/outbox.py` | `DocumentEventPublisher` and `OutboxConsumer` facades over repository persistence. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/parsed.py` | Block-oriented parsed document models and `StructuredDocumentParser` for HTML, CSV, JSON, PDF, and text. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/providers/__init__.py` | Provider package docstring; third-party adapters live under this package. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/providers/tavily.py` | `TavilySearchAdapter`, a concrete HTTP adapter for the Tavily search API. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/repository.py` | `NewsRepository` and domain record models for PostgreSQL-backed persistence. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/robots.py` | `RobotsChecker` and `RobotsRules` for robots.txt longest-prefix Allow/Disallow compliance. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/scheduler.py` | `IncrementalAcquisitionRunner` and `AcquisitionRunResult` for restart-safe incremental acquisition. |
| `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/websearch.py` | Web search models, `WebSearchProvider`, `ComplianceChecker`, `OriginalContentVerifier`, and `WebSearchService`. |

---

## Domain Models

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/models.py`.

### `SourceLevel`

`IntEnum` defining source priority from L1 (highest trust) to L5 (lowest trust).

| Member | Value | Meaning |
| --- | --- | --- |
| `L1` | 1 | Exchange announcements, regulatory filings, and periodic reports. |
| `L2` | 2 | Official IR channels, earnings calls, and formal management guidance. |
| `L3` | 3 | Hard industry data such as prices, sales volumes, inventory, and tenders. |
| `L4` | 4 | Authoritative media and professional research; may only trigger investigation or provide supporting context. |
| `L5` | 5 | Social media and unverified sources; may only trigger investigation. |

### `DocumentStatus`

`StrEnum` controlling whether a document may be used as evidence.

| Member | Value |
| --- | --- |
| `READY` | `"ready"` |
| `PARSE_FAILED` | `"parse_failed"` |

### Helper Functions

| Function | Signature | Description |
| --- | --- | --- |
| `utc_now` | `() -> datetime` | Return the current timezone-aware UTC timestamp. |
| `ensure_utc` | `(value: datetime) -> datetime` | Normalize a datetime to timezone-aware UTC, assuming UTC for naive values. |
| `compute_content_hash` | `(content: str \| bytes) -> str` | Compute a SHA-256 hash prefixed with `sha256:`. |
| `make_document_event` | `(...kwargs...) -> DocumentEvent` | Factory that auto-generates `event_id`, `document_id`, and content hash. |

### `RawSnapshot`

Immutable snapshot of downloaded original content.

| Attribute | Type | Description |
| --- | --- | --- |
| `snapshot_id` | `str` | Unique snapshot identifier. |
| `source_url` | `str` | URL from which the content was retrieved. |
| `content_hash` | `str` | Cryptographic hash of the raw content. |
| `content_type` | `str` | Format category: `pdf`, `html`, `json`, `csv`, `text`, etc. |
| `raw_size` | `int` | Size of the raw content in bytes. |
| `storage_path` | `str \| None` | Path or URI where the raw content is stored. |
| `downloaded_at` | `datetime` | Timestamp when the download occurred. |
| `http_status` | `int \| None` | HTTP response status code. |

| Validator | Purpose |
| --- | --- |
| `normalize_downloaded_at` | Normalizes `downloaded_at` to UTC. |

### `DocumentEvent`

Normalized document event published after acquisition and enrichment.

| Attribute | Type | Description |
| --- | --- | --- |
| `event_id` | `str` | Unique identifier for this event. |
| `document_id` | `str` | Unique identifier for the logical document. |
| `source_url` | `str` | URL of the original source. |
| `source_name` | `str` | Human-readable name of the source. |
| `source_level` | `SourceLevel` | Trust level of the source. |
| `title` | `str` | Document title. |
| `content` | `str \| None` | Extracted body text, if available. |
| `content_hash` | `str` | Hash of the normalized content. |
| `snapshot_id` | `str \| None` | Reference to the immutable raw snapshot. |
| `snapshot_hash` | `str \| None` | Hash of the immutable raw snapshot. |
| `symbols` | `tuple[str, ...]` | Security symbols mentioned in the document. |
| `doc_type` | `str` | Document category: `filing`, `news`, `report`, `ir`, `industry`, `user_file`. |
| `published_at` | `datetime` | Official publication timestamp. |
| `available_at` | `datetime` | Timestamp when the document became available to the system. |
| `retrieved_at` | `datetime` | Timestamp when the document was retrieved. |
| `processing_status` | `DocumentStatus` | `READY` or `PARSE_FAILED`. |
| `processing_error` | `str \| None` | Error message when processing fails. |
| `is_original` | `bool` | Whether this event is the original record rather than a duplicate. |
| `duplicate_of` | `str \| None` | Canonical event ID if this event is a duplicate. |

| Property/Validator | Purpose |
| --- | --- |
| `normalize_event_timestamp` | Normalizes `published_at`, `available_at`, and `retrieved_at` to UTC. |
| `can_change_research_state` | Returns `True` when status is `READY` and `source_level <= L3`. |

### `SourceDescriptor`

Registered source descriptor used by the source registry.

| Attribute | Type | Description |
| --- | --- | --- |
| `name` | `str` | Unique source name. |
| `source_type` | `str` | Category: `exchange`, `ir`, `media`, `rss`, `websearch`, `user`. |
| `default_level` | `SourceLevel` | Default trust level for documents from this source. |
| `url_pattern` | `str \| None` | URL pattern or base URL. |
| `requires_auth` | `bool` | Whether authentication is required. |
| `rate_limit_per_min` | `int` | Maximum requests per minute. |
| `config` | `dict[str, Any]` | Source-specific configuration. |

---

## Acquisition Layer

Defined primarily in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/acquirer.py`, with exchange-specific discovery adapters in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/connectors.py` and incremental scheduling in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/scheduler.py`.

### Exceptions

| Exception | Raised When |
| --- | --- |
| `DownloadError` | A download fails. |
| `ParseError` | Parsing a document fails. |
| `SourceNotFoundError` | A requested source is not registered in the registry. |
| `ComplianceError` | A compliance boundary is hit (robots.txt, paywall, copyright restriction). |

### `BaseConnector`

Abstract base class for source connectors.

| Abstract Member | Signature | Description |
| --- | --- | --- |
| `source_name` | `property -> str` | Human-readable source name. |
| `fetch` | `(url: str, **kwargs: Any) -> tuple[bytes, str, int]` | Fetch raw content and return `(raw bytes, content_type, http_status)`. |

### `HTTPConnector`

Generic HTTP connector that uses `requests` when available, falling back to `urllib`.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(name: str = "http") -> None` | Initialize with a source name. |
| `source_name` | `property -> str` | Return the connector's source name. |
| `fetch` | `(url: str, **kwargs: Any) -> tuple[bytes, str, int]` | Fetch the URL and return content, content type, and status. |
| `_fetch_urllib` | `(url: str) -> tuple[bytes, str, int]` | Fallback fetch using `urllib` with a `Margin/0.1` user agent. |

### `SourceRegistry`

Registry for source descriptors and their connectors.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `() -> None` | Initialize empty descriptor and connector maps. |
| `register` | `(descriptor: SourceDescriptor, connector: BaseConnector \| None = None) -> None` | Register a source descriptor and optional connector. |
| `get` | `(name: str) -> SourceDescriptor` | Return the descriptor for a source; raise `SourceNotFoundError` if missing. |
| `get_connector` | `(name: str) -> BaseConnector \| None` | Return the connector for a source, if any. |
| `list_sources` | `() -> list[str]` | Return all registered source names. |
| `list_by_type` | `(source_type: str) -> list[str]` | Return source names filtered by type. |

### `SnapshotStore`

Storage for immutable raw snapshots on the local file system.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(base_dir: Path \| None = None) -> None` | Initialize store; defaults to `~/.margin/snapshots`. |
| `save` | `(source_url: str, content: bytes, content_type: str, http_status: int \| None = None) -> RawSnapshot` | Persist raw content and return snapshot metadata. |
| `read` | `(snapshot_id: str, content_type: str) -> bytes \| None` | Read snapshot bytes by ID and extension. |
| `read_snapshot` | `(snapshot: RawSnapshot) -> bytes \| None` | Read a snapshot using its metadata. |
| `delete` | `(snapshot: RawSnapshot) -> None` | Delete a snapshot file rejected by compliance checks. |
| `_detect_extension` | `(content_type: str) -> str` | Map a content type to a canonical extension (`pdf`, `html`, `json`, `csv`, `xml`, `txt`). |

### `Downloader`

Fetches raw content through a connector and stores snapshots.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(registry: SourceRegistry, snapshot_store: SnapshotStore) -> None` | Initialize with registry and snapshot store. |
| `download` | `(source_name: str, url: str, **kwargs: Any) -> RawSnapshot` | Download a URL from a registered source and persist a snapshot. Raises `SourceNotFoundError`, `DownloadError`, or `ComplianceError`. |

### `DocumentParser`

Parses snapshots into structured fields (`title`, `content`, `doc_type`).

| Method | Signature | Description |
| --- | --- | --- |
| `parse` | `(snapshot: RawSnapshot, content: bytes \| None = None) -> dict[str, Any]` | Route to format-specific parser based on `snapshot.content_type`. |
| `_parse_html` | `(snapshot: RawSnapshot, content: bytes \| None = None) -> dict[str, Any]` | Extract title and visible body text from HTML. |
| `_parse_pdf` | `(snapshot: RawSnapshot, content: bytes \| None = None) -> dict[str, Any]` | Extract text with `pymupdf`; returns a parse note if the library is missing. |
| `_parse_structured` | `(snapshot: RawSnapshot, content: bytes \| None = None) -> dict[str, Any]` | Parse JSON, CSV, or XML; JSON is loaded as a structured object. |
| `_parse_text` | `(snapshot: RawSnapshot, content: bytes \| None = None) -> dict[str, Any]` | Parse plain text using first line as title. |
| `_extract_html_title` | `(html: str) -> str` | Extract the content of the HTML `<title>` tag. |

### `SecurityMapper`

Identifies security codes in a title and body, mapping them to standardized symbols.

| Attribute/Method | Description |
| --- | --- |
| `CODE_PATTERNS` | Regex list covering `\d{6}.SZ`, `\d{6}.SH`, `SZ\d{6}`, `SH\d{6}`, and bare `\d{6}`. |
| `map_symbols(title, content=None) -> list[str]` | Return sorted list of normalized symbols found in the text. |

### `FilingAcquirer`

Integration class that orchestrates registry, downloader, snapshot store, parser, and mapper.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(registry: SourceRegistry, snapshot_store: SnapshotStore, parser: DocumentParser \| None = None, security_mapper: SecurityMapper \| None = None) -> None` | Initialize the integrated acquirer. |
| `acquire` | `(source_name: str, url: str, title_override: str \| None = None, published_at: datetime \| None = None, **kwargs: Any) -> DocumentEvent` | Acquire a single URL and return a normalized `DocumentEvent`. |
| `acquire_batch` | `(source_name: str, urls: list[str], **kwargs: Any) -> list[DocumentEvent]` | Acquire a batch of URLs, skipping failures. |

### Exchange Announcement Connectors

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/connectors.py`.

#### Module Helpers

| Function | Signature | Description |
| --- | --- | --- |
| `_default_client` | `() -> httpx.Client` | Return a default `httpx.Client` with a 30-second timeout. |
| `_parse_datetime` | `(value: str) -> datetime` | Parse common Chinese exchange datetime formats and normalize to UTC. |

#### `SSEAnnouncementConnector`

Fixture-testable adapter for Shanghai Stock Exchange announcement discovery.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(*, endpoint: str, client: Any \| None = None) -> None` | Initialize with SSE endpoint and optional HTTP client. |
| `discover` | `(cursor: str \| None, limit: int) -> list[DiscoveredDocument]` | Fetch and map an SSE announcement page. |

#### `SZSEAnnouncementConnector`

Fixture-testable adapter for Shenzhen Stock Exchange announcement discovery.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(*, endpoint: str, base_url: str = "https://disc.szse.cn", client: Any \| None = None) -> None` | Initialize with SZSE endpoint, base URL, and optional HTTP client. |
| `discover` | `(cursor: str \| None, limit: int) -> list[DiscoveredDocument]` | Fetch and map an SZSE announcement page; resolves relative `attachPath` values to absolute URLs. |

### Incremental Scheduling

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/scheduler.py`.

#### `AcquisitionRunResult`

Summary of one incremental acquisition run.

| Attribute | Type | Description |
| --- | --- | --- |
| `discovered` | `int` | Number of documents discovered. |
| `published` | `int` | Number of documents successfully published. |
| `failed` | `int` | Number of documents that failed acquisition. |

#### `IncrementalAcquisitionRunner`

Runs discovery, acquisition, publishing, and cursor advancement.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(*, repository: NewsRepository, acquirer: Any, publisher: DocumentEventPublisher, cursor_key: str = "announcements") -> None` | Initialize runner. |
| `run_once` | `(source_name: str, connector: DiscoveryConnector, *, limit: int = 100) -> AcquisitionRunResult` | Run one restart-safe incremental pass: read cursor, discover, acquire, publish, and advance cursor per document. |

---

## Web Search Layer

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/websearch.py`, with the Tavily adapter in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/providers/tavily.py`.

### Web Search Models

#### `SearchResult`

A single web search result.

| Attribute | Type | Description |
| --- | --- | --- |
| `url` | `str` | Result URL. |
| `title` | `str` | Result title. |
| `snippet` | `str` | Result snippet or abstract. |
| `source_level` | `SourceLevel` | Assigned source level; defaults to `L4`. |
| `has_accessible_original` | `bool` | Whether accessible original content is available. |
| `content_hash` | `str \| None` | Hash of the original content snapshot. |
| `snapshot_id` | `str \| None` | Identifier of the downloaded snapshot. |

#### `SearchQueryRecord`

Immutable audit record for a web search query.

| Attribute | Type | Description |
| --- | --- | --- |
| `query_id` | `str` | Unique query identifier. |
| `query` | `str` | Search query string. |
| `results` | `tuple[SearchResult, ...]` | Search results. |
| `searched_at` | `datetime` | Timestamp when the search was performed. |
| `api_provider` | `str` | Name of the API provider. |
| `result_count` | `int` | Number of results returned. |

#### `VerifiedContent`

Accessible original content and its immutable snapshot metadata.

| Attribute | Type | Description |
| --- | --- | --- |
| `result` | `SearchResult` | Updated search result with `has_accessible_original=True`. |
| `snapshot` | `RawSnapshot` | Snapshot of the downloaded original content. |
| `title` | `str` | Parsed title. |
| `content` | `str` | Parsed body text. |

### `WebSearchProvider`

Configurable web search provider. Supports multiple search APIs via injected `search_func`.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(name: str = "websearch", secret_ref: str = "websearch_api_key", search_func: Any = None) -> None` | Initialize provider with secret reference and optional search function. |
| `descriptor` | `property -> ProviderDescriptor` | Return provider metadata, capabilities, and secret refs. |
| `set_api_key` | `(api_key: str) -> None` | Set the resolved API key. |
| `configure_secrets` | `(secrets: dict[str, str]) -> None` | Standard hook to configure API key from a secrets mapping. |
| `api_key_configured` | `property -> bool` | Return whether the API key has been resolved. |
| `set_search_func` | `(search_func: Any) -> None` | Inject the search function `(query, max_results) -> list[dict]`. |
| `healthcheck` | `() -> HealthCheckResult` | Return `DEGRADED` if no search function is configured, otherwise `HEALTHY`. |
| `search` | `(query: str, max_results: int = 10, source_level: SourceLevel = SourceLevel.L4) -> SearchQueryRecord` | Execute a search and return the query record. |

### `ComplianceChecker`

Enforces web search compliance boundaries.

| Attribute | Description |
| --- | --- |
| `BLOCKED_DOMAINS` | Set of blocked domain strings. |
| `PAYWALL_INDICATORS` | Substrings indicating paywalled content (English and Chinese). |

| Method | Signature | Description |
| --- | --- | --- |
| `check_url` | `(url: str) -> None` | Raise `ComplianceError` if the URL matches a blocked domain. |
| `check_content_for_paywall` | `(content: str) -> bool` | Return `True` if paywall indicators are present. |
| `check_http_status` | `(status: int) -> None` | Raise `ComplianceError` for HTTP 401 or 403. |

### `OriginalContentVerifier`

Verifies that search results resolve to accessible original content and persists snapshots.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(registry: SourceRegistry, snapshot_store: SnapshotStore) -> None` | Initialize verifier with downloader, snapshot store, parser, and compliance checker. |
| `verify_and_snapshot` | `(result: SearchResult) -> VerifiedContent \| None` | Download, parse, and verify a single result; return `None` if inaccessible or non-compliant. |
| `verify_batch` | `(results: list[SearchResult]) -> list[VerifiedContent \| None]` | Verify a batch of search results. |

### `WebSearchService`

Integration service combining provider, compliance checks, and original content verification.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(provider: WebSearchProvider, registry: SourceRegistry, snapshot_store: SnapshotStore, repository: NewsRepository \| None = None) -> None` | Initialize the service. |
| `search` | `(query: str, max_results: int = 10) -> SearchQueryRecord` | Execute a search and return the query record. |
| `search_and_acquire` | `(query: str, max_results: int = 10, source_level: SourceLevel = SourceLevel.L4, searched_at: datetime \| None = None) -> tuple[SearchQueryRecord, list[DocumentEvent]]` | Search, verify, persist audit record, and return document events for verified results. |

### `TavilySearchAdapter`

Concrete HTTP adapter for the Tavily search API.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(api_key: str \| None = None, *, client: Any \| None = None, base_url: str = "https://api.tavily.com/search", timeout: float = 30.0) -> None` | Initialize adapter; reads `MARGIN_WEBSEARCH_API_KEY` from environment if key is omitted. |
| `descriptor` | `property -> ProviderDescriptor` | Return provider descriptor. |
| `search` | `(query: str, max_results: int = 10) -> list[dict[str, str]]` | Execute a Tavily search and return raw `url`/`title`/`snippet` dictionaries. |
| `healthcheck` | `() -> HealthCheckResult` | Run a lightweight search health check. |

---

## Deduplication & Compliance Grading

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/dedup.py`.

### SimHash Helpers

| Function | Signature | Description |
| --- | --- | --- |
| `_tokenize` | `(text: str) -> list[str]` | Tokenize English words and individual Chinese characters. |
| `_hash64` | `(token: str) -> int` | Hash a token to a 64-bit integer using MD5. |
| `compute_simhash` | `(text: str) -> int` | Compute a 64-bit SimHash fingerprint. |
| `hamming_distance` | `(a: int, b: int) -> int` | Count differing bits between two fingerprints. |
| `simhash_similarity` | `(a: int, b: int) -> float` | Compute similarity in `[0, 1]` from Hamming distance. |

### `DedupResult`

Result container produced by the deduplication pipeline.

| Attribute | Type | Description |
| --- | --- | --- |
| `unique_events` | `list[DocumentEvent]` | Events that passed all deduplication checks. |
| `duplicate_count` | `int` | Number of duplicate events detected. |
| `duplicates` | `list[dict[str, Any]]` | Metadata for each duplicate, including `event_id`, `source_url`, `reason`, and `duplicate_of`. |

| Property | Description |
| --- | --- |
| `total_count` | Sum of unique events and duplicate events. |

### `Deduplicator`

Multi-layer deduplicator implementing architecture section 6.4.

Checks are applied in order:

1. URL uniqueness.
2. Content hash.
3. Title and publication date.
4. Body SimHash against previously seen events.
5. Vector similarity (optional).
6. Repost-chain detection, keeping the earliest reliable source.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(simhash_threshold: int = 3, title_similarity_threshold: float = 0.85, vector_similarity_func: Callable \| None = None, vector_similarity_threshold: float = 0.92) -> None` | Initialize with configurable thresholds. |
| `seed` | `(events: list[DocumentEvent]) -> None` | Seed with already-known canonical events. |
| `find_duplicate` | `(event: DocumentEvent) -> tuple[str, DocumentEvent] \| None` | Public duplicate probe used by persistent processors. |
| `record_event` | `(event: DocumentEvent) -> None` | Record a canonical event after it is persisted. |
| `deduplicate` | `(events: list[DocumentEvent]) -> DedupResult` | Run multi-layer deduplication on a batch of events. |
| `_check_duplicate` | `(event: DocumentEvent) -> tuple[str, DocumentEvent] \| None` | Internal single-event duplicate check. |
| `_record_seen` | `(event: DocumentEvent) -> None` | Record a unique event for future duplicate checks. |

### `QualityScore`

Source quality score for a document event.

| Attribute | Type | Description |
| --- | --- | --- |
| `event_id` | `str` | Identifier of the evaluated event. |
| `source_level` | `SourceLevel` | Source level of the evaluated event. |
| `completeness` | `float` | Content completeness in `[0, 1]`. |
| `timeliness` | `float` | Recency score in `[0, 1]`. |
| `uniqueness` | `float` | Originality score in `[0, 1]`. |
| `authority` | `float` | Authority score in `[0, 1]`. |
| `total_score` | `float` | Weighted aggregate score in `[0, 1]`. |

### `QualityScorer`

Scores events on authority, completeness, timeliness, and uniqueness.

Authority mapping:

| SourceLevel | Authority Score |
| --- | --- |
| `L1` | 1.0 |
| `L2` | 0.8 |
| `L3` | 0.6 |
| `L4` | 0.4 |
| `L5` | 0.2 |

Total score weights: authority 0.40, completeness 0.25, timeliness 0.20, uniqueness 0.15.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(timeliness_decay_days: float = 30.0) -> None` | Initialize scorer with timeliness decay period. |
| `score` | `(event: DocumentEvent) -> QualityScore` | Compute a quality score for a single event. |
| `score_batch` | `(events: list[DocumentEvent]) -> list[QualityScore]` | Compute quality scores for a batch of events. |

### `NewsProcessor`

Combines deduplication and quality scoring in memory.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(deduplicator: Deduplicator \| None = None, quality_scorer: QualityScorer \| None = None) -> None` | Initialize processor. |
| `process` | `(events: list[DocumentEvent]) -> DedupResult` | Deduplicate a batch of events. |
| `score` | `(event: DocumentEvent) -> QualityScore` | Score a single event. |
| `score_batch` | `(events: list[DocumentEvent]) -> list[QualityScore]` | Score a batch of events. |
| `process_and_score` | `(events: list[DocumentEvent]) -> tuple[DedupResult, list[QualityScore]]` | Run deduplication and scoring in one call. |
| `filter_by_level` | `(events: list[DocumentEvent], min_level: SourceLevel = SourceLevel.L1, max_level: SourceLevel = SourceLevel.L3) -> list[DocumentEvent]` | Filter events by source level range. |

### `PersistentNewsProcessor`

Deduplicates against persisted canonical events and records every duplicate decision and repost edge.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(repository: NewsRepository, *, simhash_threshold: int = 3, vector_similarity_func: Callable \| None = None, vector_similarity_threshold: float = 0.92, quality_scorer: QualityScorer \| None = None) -> None` | Initialize with repository and thresholds. |
| `process` | `(events: list[DocumentEvent]) -> DedupResult` | Seed from repository, deduplicate, persist unique events, duplicate records, and repost edges. |
| `score` | `(event: DocumentEvent) -> QualityScore` | Compute quality score for an event. |

---

## Repository & Outbox

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/repository.py` and `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/outbox.py`. SQLAlchemy row models are in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/db_models.py`.

### Domain Records

#### `OutboxMessage`

| Attribute | Type | Description |
| --- | --- | --- |
| `outbox_id` | `int` | Primary key of the outbox row. |
| `event_id` | `str` | Foreign key to the document event. |
| `topic` | `str` | Destination topic or queue name. |
| `attempts` | `int` | Number of delivery attempts already made. |

#### `DedupRecord`

| Attribute | Type | Description |
| --- | --- | --- |
| `duplicate_event_id` | `str` | Identifier of the duplicate event. |
| `canonical_event_id` | `str` | Identifier of the canonical event. |
| `reason` | `str` | Short reason code. |
| `similarity_score` | `float \| None` | Optional similarity score. |
| `created_at` | `datetime` | Timestamp of the decision. |

#### `RepostEdge`

| Attribute | Type | Description |
| --- | --- | --- |
| `parent_event_id` | `str` | Canonical parent event identifier. |
| `child_event_id` | `str` | Repost child event identifier. |
| `reason` | `str` | Short reason code. |
| `created_at` | `datetime` | Timestamp of the edge. |

### `NewsRepository`

SQLAlchemy-backed persistence boundary.

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(session_factory: Callable[[], Session]) -> None` | Initialize with a session factory. |
| `upsert_cursor` | `(source_name: str, cursor_key: str, cursor_value: str) -> None` | Create or update an incremental source cursor. |
| `get_cursor` | `(source_name: str, cursor_key: str) -> str \| None` | Read an incremental source cursor. |
| `add_snapshot` | `(snapshot: RawSnapshot) -> None` | Persist immutable snapshot metadata idempotently. |
| `get_snapshot` | `(snapshot_id: str) -> RawSnapshot \| None` | Fetch snapshot metadata. |
| `add_document_event` | `(event: DocumentEvent, *, publishable: bool = True, topic: str = "vector_index") -> None` | Persist a document event and enqueue it when ready. |
| `get_document_event` | `(event_id: str) -> DocumentEvent \| None` | Fetch a document event by ID. |
| `list_unique_events` | `() -> list[DocumentEvent]` | List canonical events (not marked as duplicates), ordered by source level and publication time. |
| `claim_outbox` | `(topic: str, limit: int = 50) -> list[OutboxMessage]` | Claim pending outbox messages using `SKIP LOCKED`. |
| `mark_outbox_delivered` | `(outbox_id: int) -> None` | Mark a claimed message as delivered. |
| `mark_outbox_failed` | `(outbox_id: int, error: str) -> None` | Mark a message as failed and record the error. |
| `add_search_record` | `(record: SearchQueryRecord) -> None` | Persist a web search query and result rows idempotently. |
| `get_search_record` | `(query_id: str) -> SearchQueryRecord \| None` | Fetch a search query with ordered results. |
| `add_dedup_record` | `(*, duplicate_event_id: str, canonical_event_id: str, reason: str, similarity_score: float \| None = None) -> None` | Persist a duplicate decision idempotently. |
| `get_dedup_record` | `(duplicate_event_id: str) -> DedupRecord \| None` | Fetch a persisted duplicate decision. |
| `add_repost_edge` | `(*, parent_event_id: str, child_event_id: str, reason: str) -> None` | Persist a repost edge idempotently. |
| `list_repost_chain` | `(parent_event_id: str) -> list[RepostEdge]` | List direct repost edges for a canonical event. |

### Row Mapping Helpers

| Function | Description |
| --- | --- |
| `_snapshot_to_row` | Map `RawSnapshot` to `RawSnapshotRow`. |
| `_snapshot_from_row` | Map `RawSnapshotRow` to `RawSnapshot`. |
| `_event_to_row` | Map `DocumentEvent` to `DocumentEventRow`. |
| `_event_from_row` | Map `DocumentEventRow` to `DocumentEvent`. |
| `_search_query_to_row` | Map `SearchQueryRecord` to `SearchQueryRow`. |
| `_search_result_to_row` | Map `SearchResult` to `SearchResultRow`. |
| `_search_result_from_row` | Map `SearchResultRow` to `SearchResult`. |
| `_dedup_from_row` | Map `DedupRecordRow` to `DedupRecord`. |
| `_repost_from_row` | Map `RepostEdgeRow` to `RepostEdge`. |

### Outbox Facades

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/outbox.py`.

#### `DocumentEventPublisher`

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(repository: NewsRepository) -> None` | Initialize publisher. |
| `persist_pending` | `(event: DocumentEvent) -> None` | Persist one event and create an outbox row when it is indexable. |

#### `OutboxConsumer`

| Method | Signature | Description |
| --- | --- | --- |
| `__init__` | `(repository: NewsRepository) -> None` | Initialize consumer. |
| `claim_batch` | `(topic: str, limit: int = 50) -> list[OutboxMessage]` | Claim pending messages. |
| `mark_delivered` | `(outbox_id: int) -> None` | Mark a message delivered. |
| `mark_failed` | `(outbox_id: int, error: str) -> None` | Mark a message failed. |

---

## Structured Parsing

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/parsed.py`.

### `ParsedBlock`

A parsed source block with exact source locator metadata.

| Attribute | Type | Description |
| --- | --- | --- |
| `block_id` | `str` | Unique block identifier. |
| `block_type` | `Literal["heading", "paragraph", "table_row", "page", "json_row", "text"]` | Semantic block type. |
| `text` | `str` | Extracted text content. |
| `page` | `int \| None` | Optional page number. |
| `section` | `str \| None` | Optional section or heading context. |
| `paragraph_index` | `int \| None` | Optional paragraph index within the section. |
| `table_id` | `str \| None` | Optional table identifier. |
| `row_id` | `str \| None` | Optional row identifier. |
| `quote_span` | `tuple[int, int] \| None` | Character span (start, end) of the text in the original source. |

### `ParsedDocument`

| Attribute | Type | Description |
| --- | --- | --- |
| `document_id` | `str` | Unique parsed document identifier. |
| `source_url` | `str \| None` | Optional original source URL. |
| `title` | `str \| None` | Optional document title. |
| `blocks` | `tuple[ParsedBlock, ...]` | Ordered parsed blocks. |
| `parse_status` | `str` | `ready` or `failed`. |
| `parse_error` | `str \| None` | Error message when parsing fails. |

### `StructuredDocumentParser`

Parser that emits ordered blocks for HTML, CSV, JSON, PDF, and plain text.

| Method | Signature | Description |
| --- | --- | --- |
| `parse_html` | `(html: str \| bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | Parse HTML headings and paragraphs. |
| `parse_csv` | `(content: str \| bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | Parse CSV rows into table blocks. |
| `parse_json` | `(content: str \| bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | Parse JSON objects or arrays into row blocks. |
| `parse_pdf` | `(content: bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | Parse PDF pages into page blocks using `pypdf`. |
| `parse_text` | `(content: str \| bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | Parse plain text paragraphs. |

---

## Robots.txt Compliance

Defined in `/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/robots.py`.

### `RobotsFetcher` Protocol

| Method | Signature | Description |
| --- | --- | --- |
| `__call__` | `(url: str) -> tuple[int, bytes]` | Fetch a robots.txt URL and return `(status, body)`. |

### `_default_fetcher`

| Function | Signature | Description |
| --- | --- | --- |
| `_default_fetcher` | `(url: str) -> tuple[int, bytes]` | Fetch robots.txt using `httpx` with redirects enabled and a 10-second timeout. |

### `RobotsRules`

Parsed robots rules for one origin.

| Attribute | Type | Description |
| --- | --- | --- |
| `allows` | `list[str]` | Allow path prefixes. |
| `disallows` | `list[str]` | Disallow path prefixes. |

| Method | Signature | Description |
| --- | --- | --- |
| `can_fetch` | `(path: str) -> bool` | Apply longest-prefix Allow/Disallow semantics. |

### `RobotsChecker`

Cached robots.txt checker.

| Attribute | Type | Description |
| --- | --- | --- |
| `fetcher` | `RobotsFetcher` | Callable used to retrieve robots.txt. |
| `user_agent` | `str` | User-agent string to match; currently wildcard `*`. |
| `_cache` | `dict[str, RobotsRules]` | Per-origin parsed rules cache. |

| Method | Signature | Description |
| --- | --- | --- |
| `__post_init__` | `() -> None` | Initialize the per-origin rules cache. |
| `allowed` | `(url: str) -> bool` | Return whether `url` can be fetched under robots.txt. |
| `assert_allowed` | `(url: str) -> None` | Raise `ComplianceError` if the URL is not allowed. |
| `_parser_for` | `(scheme: str, netloc: str) -> RobotsRules` | Fetch, parse, and cache robots.txt for an origin. |
| `_parse_rules` | `(content: str) -> RobotsRules` | Parse a robots.txt body into Allow/Disallow rules for user-agent `*`. |

---

## Cross-Module Usage Notes

### Package Exports

`/Users/wangruiqi/PycharmProjects/Margin/src/margin/news/__init__.py` re-exports the most commonly used symbols for convenience:

- Acquisition: `BaseConnector`, `ComplianceError`, `DocumentParser`, `Downloader`, `DownloadError`, `FilingAcquirer`, `HTTPConnector`, `ParseError`, `SecurityMapper`, `SnapshotStore`, `SourceNotFoundError`, `SourceRegistry`.
- Deduplication: `Deduplicator`, `DedupResult`, `NewsProcessor`, `PersistentNewsProcessor`, `QualityScore`, `QualityScorer`, `compute_simhash`, `hamming_distance`, `simhash_similarity`.
- Models: `DocumentEvent`, `DocumentStatus`, `RawSnapshot`, `SourceDescriptor`, `SourceLevel`, `compute_content_hash`, `make_document_event`.
- Web search: `ComplianceChecker`, `OriginalContentVerifier`, `SearchQueryRecord`, `SearchResult`, `VerifiedContent`, `WebSearchProvider`, `WebSearchService`.

### Downstream Consumers

- Vector indexing workers consume `DocumentOutboxRow` messages produced by `NewsRepository.add_document_event`.
- Research and holdings monitoring modules consume `DocumentEvent` records with `processing_status == READY` and `source_level <= L3` for state-changing evidence.
- L4/L5 events (e.g., web search results, social media) may only trigger investigation or provide auxiliary explanation.

### Compliance Boundaries

- `Downloader` raises `ComplianceError` on HTTP 401/403.
- `HTTPConnector` does not bypass robots.txt, login walls, paywalls, or anti-scraping mechanisms.
- `ComplianceChecker` blocks configured domains and detects paywall indicators.
- `OriginalContentVerifier` deletes non-compliant snapshots and returns `None` for inaccessible results.
- `RobotsChecker` enforces longest-prefix Allow/Disallow rules from `robots.txt`.

### Persistence Conventions

- Snapshots and document events are immutable once written; updates are modeled as new events.
- Duplicate decisions are recorded in `dedup_records` and repost relationships in `repost_edges`.
- Search queries and results are persisted for audit and compliance tracing.
- Outbox rows use PostgreSQL `SKIP LOCKED` for safe worker claiming.

### Typical Acquisition Flow

```python
from margin.news.acquirer import SourceRegistry, SourceDescriptor, FilingAcquirer, SnapshotStore
from margin.news.models import SourceLevel

registry = SourceRegistry()
registry.register(SourceDescriptor(name="sse", source_type="exchange", default_level=SourceLevel.L1))

snapshot_store = SnapshotStore()
acquirer = FilingAcquirer(registry, snapshot_store)
event = acquirer.acquire("sse", "https://example.com/announcement.pdf")
```

### Typical Web Search Flow

```python
from margin.news.providers.tavily import TavilySearchAdapter
from margin.news.websearch import WebSearchProvider, WebSearchService
from margin.news.acquirer import SourceRegistry, SnapshotStore

adapter = TavilySearchAdapter()
provider = WebSearchProvider(search_func=adapter.search)
registry = SourceRegistry()
snapshot_store = SnapshotStore()
service = WebSearchService(provider, registry, snapshot_store)

record, events = service.search_and_acquire("平安银行 公告", max_results=5)
```
