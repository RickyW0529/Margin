"""News acquisition package: filings retrieval, web search, deduplication, and source leveling.

This package aggregates connectors, parsers, deduplication utilities, web search services,
and Pydantic data models used to fetch, normalize, and stage news and regulatory documents
before they are sent to downstream indexing and research pipelines.
"""

from margin.news.acquirer import (
    BaseConnector,
    ComplianceError,
    DocumentParser,
    Downloader,
    DownloadError,
    FilingAcquirer,
    HTTPConnector,
    ParseError,
    SecurityMapper,
    SnapshotStore,
    SourceNotFoundError,
    SourceRegistry,
)
from margin.news.dedup import (
    Deduplicator,
    DedupResult,
    NewsProcessor,
    QualityScore,
    QualityScorer,
    compute_simhash,
    hamming_distance,
    simhash_similarity,
)
from margin.news.models import (
    DocumentEvent,
    DocumentStatus,
    RawSnapshot,
    SourceDescriptor,
    SourceLevel,
    compute_content_hash,
    make_document_event,
)
from margin.news.websearch import (
    ComplianceChecker,
    OriginalContentVerifier,
    SearchQueryRecord,
    SearchResult,
    VerifiedContent,
    WebSearchProvider,
    WebSearchService,
)

__all__ = [
    "BaseConnector",
    "ComplianceChecker",
    "ComplianceError",
    "DedupResult",
    "Deduplicator",
    "DocumentEvent",
    "DocumentStatus",
    "DocumentParser",
    "DownloadError",
    "Downloader",
    "FilingAcquirer",
    "HTTPConnector",
    "NewsProcessor",
    "OriginalContentVerifier",
    "ParseError",
    "QualityScore",
    "QualityScorer",
    "RawSnapshot",
    "SearchQueryRecord",
    "SearchResult",
    "SecurityMapper",
    "SnapshotStore",
    "SourceDescriptor",
    "SourceLevel",
    "SourceNotFoundError",
    "SourceRegistry",
    "WebSearchProvider",
    "WebSearchService",
    "VerifiedContent",
    "compute_content_hash",
    "compute_simhash",
    "hamming_distance",
    "make_document_event",
    "simhash_similarity",
]
