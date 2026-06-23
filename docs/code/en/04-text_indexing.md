# 04-text_indexing Module Documentation

## Table of Contents

- [1. Module Overview and Responsibilities](#1-module-overview-and-responsibilities)
- [2. File-Level Summaries](#2-file-level-summaries)
- [3. Domain Models](#3-domain-models)
  - [3.1 `Chunk`](#31-chunk)
  - [3.2 v0.2 Indexing Models](#32-v02-indexing-models)
  - [3.3 `RetrievalResult`](#33-retrievalresult)
  - [3.4 `DocType`](#34-doctype)
  - [3.5 Factory Functions](#35-factory-functions)
- [4. Chunkers](#4-chunkers)
  - [4.1 `BaseChunker`](#41-basechunker)
  - [4.2 `ReportChunker`](#42-reportchunker)
  - [4.3 `FilingChunker`](#43-filingchunker)
  - [4.4 `NewsChunker`](#44-newschunker)
  - [4.5 `IRChunker`](#45-irchunker)
  - [4.6 `UserNoteChunker`](#46-usernotechunker)
  - [4.7 `Chunker`](#47-chunker)
  - [4.8 `infer_doc_type`](#48-infer_doc_type)
  - [4.9 v0.2 Structured Parsers and `StructuredChunker`](#49-v02-structured-parsers-and-structuredchunker)
- [5. Embedding Pipeline](#5-embedding-pipeline)
  - [5.1 `EmbeddingProvider`](#51-embeddingprovider)
  - [5.2 `VectorStore`](#52-vectorstore)
  - [5.3 `BM25Index`](#53-bm25index)
  - [5.4 `IndexAuditor` and `IndexAuditRecord`](#54-indexauditor-and-indexauditrecord)
  - [5.5 `EmbeddingPipeline`](#55-embeddingpipeline)
  - [5.6 `OpenAIEmbeddingProvider`](#56-openaiembeddingprovider)
- [6. Persistent Pipeline](#6-persistent-pipeline)
  - [6.1 `PersistentEmbeddingPipeline`](#61-persistentembeddingpipeline)
  - [6.2 `PersistentIndexingPipeline`](#62-persistentindexingpipeline)
- [7. Retrieval](#7-retrieval)
  - [7.1 `SearchConstraints`](#71-searchconstraints)
  - [7.2 `HybridWeights`](#72-hybridweights)
  - [7.3 `HybridRetriever`](#73-hybridretriever)
  - [7.4 `Reranker`](#74-reranker)
  - [7.5 `RetrievalTool`](#75-retrievaltool)
  - [7.6 `HTTPRerankProvider`](#76-httprerankprovider)
- [8. Indexing Runner](#8-indexing-runner)
  - [8.1 `DocumentIndexingRunner`](#81-documentindexingrunner)
  - [8.2 `IndexingRunner`](#82-indexingrunner)
- [9. Repository](#9-repository)
  - [9.1 `VectorRepository`](#91-vectorrepository)
- [10. Cross-Module Usage Notes](#10-cross-module-usage-notes)
  - [10.1 Real Smoke](#101-real-smoke)

---

## 1. Module Overview and Responsibilities

The `04-text_indexing` module (implemented under `src/margin/vector/`) is responsible for transforming parsed financial documents into searchable vector and keyword indexes. It sits between document parsing (module 03) and downstream research agents (module 06).

Key responsibilities:

- **Recoverable outbox ingestion**: consume module 03 document outbox messages with lease/retry semantics.
- **Structured parsing**: parse HTML, PDF, CSV, JSON, and plain text into locatable blocks.
- **Document chunking**: split documents by type (annual reports, filings, news, IR records, industry reports, user notes) into semantically meaningful, locatable chunks.
- **Multi-security linking**: persist chunk/security relationships in `chunk_security_links`; chunk identity is no longer tied to a single symbol.
- **Embedding generation**: produce dense vector embeddings for chunks using pluggable providers.
- **Vector and keyword indexing**: store embeddings in a vector store (in-memory or PostgreSQL/pgvector) and keyword statistics in a BM25 index.
- **PIT hybrid retrieval**: combine dense vector similarity, BM25 keyword scoring, recency decay, source quality, and entity match while enforcing `available_at <= decision_at`.
- **Reranking**: optionally rerank retrieval results using a cross-encoder or HTTP reranking provider.
- **Auditing and replay**: record indexing operations and retrieval results for debugging, evaluation, and replay.
- **Cross-module integration**: consume document events from the module 03 outbox and expose retrieval tools to the multi-agent research layer.

---

## 2. File-Level Summaries

| File | Purpose |
|------|---------|
| `src/margin/vector/__init__.py` | Public package exports. Re-exports chunkers, embedding classes, models, and retrieval classes. |
| `src/margin/vector/models.py` | Domain models: `DocType`, `Chunk`, `SourceLocator`, `ChunkSecurityLink`, `IndexedDocument`, `EmbeddingKey`, `RetrievalResult`, plus helper functions. |
| `src/margin/vector/db_models.py` | SQLAlchemy ORM definitions for `ChunkRow`, `ChunkEmbeddingRow`, `ChunkSecurityLinkRow`, `IndexedDocumentRow`, `IndexAuditRecordRow`, and `RetrievalAuditRecordRow`. |
| `src/margin/vector/chunker.py` | Document-type-aware chunking logic, including `Chunker`, `BaseChunker`, and specializations such as `ReportChunker` and `NewsChunker`. |
| `src/margin/vector/parsers/` | HTML/PDF/CSV/JSON/Text parsers that emit structured blocks with `SourceLocator`. |
| `src/margin/vector/embedding.py` | In-memory embedding pipeline: `EmbeddingProvider`, `VectorStore`, `BM25Index`, `IndexAuditor`, and `EmbeddingPipeline`. |
| `src/margin/vector/providers/openai_embedding.py` | `OpenAIEmbeddingProvider`, an HTTP adapter for OpenAI-compatible `/embeddings` endpoints. |
| `src/margin/vector/providers/rerank.py` | `HTTPRerankProvider`, an HTTP adapter for Cohere-style or OpenAI-compatible `/rerank` endpoints. |
| `src/margin/vector/providers/__init__.py` | Package docstring for concrete vector provider adapters. |
| `src/margin/vector/persistent_pipeline.py` | `PersistentEmbeddingPipeline`, exposing persistent chunks/embeddings through the retrieval pipeline API. |
| `src/margin/vector/retrieval.py` | Hybrid retrieval and reranking: `HybridRetriever`, `Reranker`, `RetrievalTool`, `SearchConstraints`, and `HybridWeights`. |
| `src/margin/vector/indexing_runner.py` | `DocumentIndexingRunner`, a worker that consumes document outbox events and persists chunks/embeddings. |
| `src/margin/vector/repository.py` | `VectorRepository`, the PostgreSQL persistence boundary for chunks, embeddings, audits, and replay. |
| `scripts/smoke_text_indexing.py` | Token-safe real embedding/indexing smoke script for module 04. |

---

## 3. Domain Models

### 3.1 `Chunk`

Defined in `src/margin/vector/models.py`.

`Chunk` is the atomic unit of the text indexing layer. It stores a slice of source content together with provenance metadata and structural locators.

| Attribute | Type | Description |
|-----------|------|-------------|
| `chunk_id` | `str` | Stable identifier. v0.2 structured indexing uses `sha256(document_id, content_hash, parser_version, chunk_index)` and does not depend on symbol. |
| `document_id` | `str` | Identifier of the parent document. |
| `content` | `str` | Plain-text chunk content. |
| `content_hash` | `str` | SHA-256 hash of the content used for integrity checks. |
| `symbol` | `str \| None` | Optional ticker/security symbol. |
| `source_level` | `SourceLevel` | Source reliability level. Defaults to `L4`. |
| `doc_type` | `DocType` | Document category. Defaults to `UNKNOWN`. |
| `published_at` | `datetime` | Original publication timestamp in UTC. |
| `available_at` | `datetime` | Timestamp when the content became available in UTC. |
| `source_url` | `str \| None` | URL to the original source. |
| `source_name` | `str \| None` | Human-readable source name. |
| `snapshot_id` | `str \| None` | Identifier of the captured web snapshot. |
| `snapshot_hash` | `str \| None` | Hash of the captured snapshot. |
| `page` | `int \| None` | Page number in the source document. |
| `section` | `str \| None` | Section or chapter name. |
| `paragraph_index` | `int \| None` | Paragraph sequence number. |
| `table_id` | `str \| None` | Table identifier. |
| `row_id` | `str \| None` | Table row identifier. |
| `quote_span` | `tuple[int, int] \| None` | Character span for direct quoting. |
| `locator` | `SourceLocator` | Unified v0.2 locator for page, bbox, DOM path, paragraph, table, row/column, and quote span. |
| `trust_level` | `TrustLevel` | Prompt-safety trust label. WebSearch/news content is treated as untrusted source content. |
| `is_active` | `bool` | Whether the chunk is active. Persistent retrieval filters inactive chunks. |
| `embedding` | `tuple[float, ...] \| None` | Optional dense vector embedding. |
| `keywords` | `tuple[str, ...]` | Optional BM25/keyword terms. |
| `chunk_index` | `int` | Zero-based position within the document. |
| `total_chunks` | `int` | Total number of chunks produced for the document. |

| Method / Property | Signature | Description |
|-------------------|-----------|-------------|
| `normalize_timestamp` | `@field_validator("published_at", "available_at")` `classmethod` | Normalizes timestamp fields to UTC. |
| `has_locator` | `property` | Returns `True` when the chunk has a `source_url` and a precise `SourceLocator` or compatible legacy locator fields. |

### 3.2 v0.2 Indexing Models

| Model | Description |
|-------|-------------|
| `SourceLocator` | Unified locator with `page`, `bbox`, `section`, `dom_path`, `paragraph_index`, `table_id`, `row_id`, `column_id`, and `quote_span`. `has_precise_anchor` indicates whether evidence can be replayed to source. |
| `TrustLevel` | `trusted_official_content`, `trusted_structured_data`, `untrusted_source_content`, or `user_supplied_content`. |
| `IndexingRequest` | Immutable indexing request that requires `available_at` for PIT-safe indexing. |
| `ChunkSecurityLink` | Many-to-many link between `chunk_id` and `security_id`, with `link_type` and confidence. |
| `IndexedDocument` | Document-level parser/chunker/embedding audit with `parser_version`, `input_hash`, `chunk_ids`, and `embedding_keys`. |
| `EmbeddingKey` | Deterministic `sha256(chunk_id, provider_name, model_name, model_version)` audit key. |
| `make_stable_chunk_id` | Symbol-independent chunk ID helper. |

### 3.3 `RetrievalResult`

Defined in `src/margin/vector/models.py`.

A scored retrieval candidate returned by a search operation.

| Attribute | Type | Description |
|-----------|------|-------------|
| `chunk` | `Chunk` | The retrieved document chunk. |
| `score` | `float` | Final combined relevance score. |
| `vector_score` | `float` | Dense vector similarity score. |
| `keyword_score` | `float` | Sparse/BM25 keyword score. |
| `time_decay` | `float` | Recency/time-decay component. |
| `source_quality` | `float` | Source reliability/quality component. |
| `entity_match` | `float` | Entity match score. |
| `rank` | `int` | Final rank after reranking. |

### 3.4 `DocType`

Defined in `src/margin/vector/models.py`.

`StrEnum` used to select chunking and retrieval strategies.

| Member | Value | Description |
|--------|-------|-------------|
| `ANNUAL_REPORT` | `"annual_report"` | Annual financial report. |
| `QUARTERLY_REPORT` | `"quarterly_report"` | Quarterly financial report. |
| `FILING` | `"filing"` | Regulatory filing. |
| `NEWS` | `"news"` | News article or press release. |
| `IR` | `"ir"` | Investor relations material. |
| `INDUSTRY_REPORT` | `"industry_report"` | Third-party industry research report. |
| `USER_NOTE` | `"user_note"` | User-authored note. |
| `UNKNOWN` | `"unknown"` | Document type could not be determined. |

### 3.5 Factory Functions

Defined in `src/margin/vector/models.py`.

| Function | Signature | Description |
|----------|-----------|-------------|
| `compute_chunk_hash` | `(content: str) -> str` | Computes a deterministic `sha256:`-prefixed hash of the chunk content. |
| `make_chunk` | `(document_id: str, content: str, chunk_index: int = 0, total_chunks: int = 1, **kwargs: Any) -> Chunk` | Creates a `Chunk` with an auto-generated `chunk_id` and `content_hash`. Converts `embedding` and `keywords` to tuples. |
| `make_stable_chunk_id` | `(*, document_id, content_hash, parser_version, chunk_index) -> str` | v0.2 symbol-independent structured indexing ID helper. |

---

## 4. Chunkers

Defined in `src/margin/vector/chunker.py`.

### 4.1 `BaseChunker`

Generic chunker providing paragraph/sentence splitting utilities and helper methods for producing `Chunk` objects.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(max_chunk_size: int = 1000, overlap: int = 100) -> None` | Initializes the chunker. Raises `ValueError` if `max_chunk_size` is not positive or `overlap` is invalid. |
| `chunk` | `(event: DocumentEvent) -> list[Chunk]` | Abstract method; subclasses must implement. |
| `_split_paragraphs` | `(text: str) -> list[str]` | Splits text into paragraphs separated by blank lines. |
| `_split_sentences` | `(text: str) -> list[str]` | Splits text into sentences using Chinese and English punctuation. |
| `_merge_to_size` | `(parts: list[str]) -> list[str]` | Merges small parts into chunks that do not exceed `max_size`. Applies configured overlap. |
| `_split_oversized_part` | `(part: str) -> list[str]` | Splits a single oversized segment into sub-segments no longer than `max_size`. |
| `_make_chunks` | `(event: DocumentEvent, text_parts: list[str], doc_type: DocType, section_labels: list[str] \| None = None) -> list[Chunk]` | Generates `Chunk` objects from text parts and populates metadata, including `chunk_index`, `total_chunks`, and `section`. |

### 4.2 `ReportChunker`

Splits annual/quarterly reports and industry reports by section, table, and page.

| Method | Signature | Description |
|--------|-----------|-------------|
| `chunk` | `(event: DocumentEvent) -> list[Chunk]` | Chunks a report event by detected sections. |
| `_split_by_sections` | `(text: str) -> list[tuple[str, str]]` | Splits text by section markers (Chinese numerals, `Section \d+`, `Chapter \d+`, etc.) and returns `(section_label, section_text)` tuples. |

### 4.3 `FilingChunker`

Splits regulatory filings by matter and clause.

| Method | Signature | Description |
|--------|-----------|-------------|
| `chunk` | `(event: DocumentEvent) -> list[Chunk]` | Chunks a filing event by detected items. |
| `_split_by_items` | `(text: str) -> list[tuple[str, str]]` | Splits text by item markers (Chinese numerals, `第\d+条`, etc.) and returns `(item_label, item_text)` tuples. |

### 4.4 `NewsChunker`

Extracts title, lead, and body paragraphs from news articles.

| Method | Signature | Description |
|--------|-----------|-------------|
| `chunk` | `(event: DocumentEvent) -> list[Chunk]` | Creates chunks for title, lead paragraph, and remaining body paragraphs. |

### 4.5 `IRChunker`

Splits investor relations records by question-and-answer pairs.

| Method | Signature | Description |
|--------|-----------|-------------|
| `chunk` | `(event: DocumentEvent) -> list[Chunk]` | Chunks an IR event by Q&A pairs. Falls back to paragraph splitting when no Q&A markers are found. |
| `_split_qa` | `(text: str) -> list[tuple[str, str]]` | Splits text by question/answer markers and groups adjacent Q and A segments into pairs. |

### 4.6 `UserNoteChunker`

Splits user-authored notes by heading and paragraph.

| Method | Signature | Description |
|--------|-----------|-------------|
| `chunk` | `(event: DocumentEvent) -> list[Chunk]` | Chunks a user note by paragraphs, labeling each chunk as `para_i`. |

### 4.7 `Chunker`

Entry point dispatcher that selects a chunking strategy based on inferred document type.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(max_chunk_size: int = 1000, overlap: int = 100, custom_chunkers: dict[DocType, BaseChunker] \| None = None) -> None` | Initializes the dispatcher with optional custom per-type chunkers. |
| `chunk` | `(event: DocumentEvent) -> list[Chunk]` | Chunks an event using the matching strategy. Returns an empty list if the event is not `READY`. Raises `ChunkingError` on failure. |
| `_make_fallback_chunks` | `(event: DocumentEvent, doc_type: DocType) -> list[Chunk]` | Creates title-only fallback chunks when a ready document produces no body chunks. |
| `chunk_batch` | `(events: list[DocumentEvent]) -> list[Chunk]` | Chunks a batch of events, skipping documents that raise `ChunkingError`. |
| `chunk_parsed` | `(parsed: ParsedDocument, event: DocumentEvent) -> list[Chunk]` | Chunks structured parsed blocks while preserving source locators (`page`, `section`, `quote_span`, etc.). |
| `_split_block_text` | `(block: ParsedBlock) -> list[tuple[str, tuple[int, int] \| None]]` | Splits a parsed block's text and adjusts the quote span for each sub-piece. |

### 4.8 `infer_doc_type`

| Function | Signature | Description |
|----------|-----------|-------------|
| `infer_doc_type` | `(event: DocumentEvent) -> DocType` | Infers the document type from `event.doc_type` and `event.title` using explicit mappings and keyword heuristics. |

### 4.9 v0.2 Structured Parsers and `StructuredChunker`

The `src/margin/vector/parsers/` package emits structured `ParsedBlock` objects:

| Parser | Input | Locator support |
|--------|-------|-----------------|
| `HtmlParser` | HTML bytes | Headings, paragraphs, tables, DOM paths, paragraph indexes, table rows/columns. |
| `PdfParser` | PDF bytes | Page-level text blocks; raises `ParserUnavailable` when PDF dependencies are unavailable. |
| `CsvParser` | CSV bytes | Table id, row id, and column id. |
| `JsonParser` | JSON bytes | Flattened scalar paths as locators. |
| `PlainTextParser` | text bytes | Paragraph indexes and half-open `quote_span`. |

`StructuredChunker` consumes those blocks and returns `ChunkingResult(chunks, links)`:

- Chunk IDs use `make_stable_chunk_id(document_id, content_hash, parser_version, chunk_index)`.
- Table and text boundaries are not crossed.
- Security associations are emitted as `ChunkSecurityLink` rows.
- External WebSearch/news chunks should use `TrustLevel.UNTRUSTED_SOURCE_CONTENT`.

---

## 5. Embedding Pipeline

Defined in `src/margin/vector/embedding.py` unless otherwise noted.

### 5.1 `EmbeddingProvider`

Pluggable embedding provider. Ships with a deterministic hash-based pseudo-embedding for testing.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(name: str = "hash_embedding", version: str = "1.0.0", dim: int = 256, embed_func: Callable[[str], list[float]] \| None = None, secret_ref: str \| None = None) -> None` | Initializes the provider. Raises `ValueError` if `dim` is not positive. |
| `descriptor` | `property -> ProviderDescriptor` | Returns provider registry-compatible metadata. |
| `name` | `property -> str` | Returns the provider name. |
| `version` | `property -> str` | Returns the provider version. |
| `dim` | `property -> int` | Returns the configured embedding dimension. |
| `embed` | `(text: str) -> list[float]` | Generates an embedding vector for the given text. Raises `ValueError` on dimension mismatch. |
| `embed_batch` | `(texts: list[str]) -> list[list[float]]` | Generates embeddings for a batch of texts. |
| `set_embed_func` | `(func: Callable[[str], list[float]]) -> None` | Injects a real embedding model function. |
| `configure_secrets` | `(secrets: dict[str, str]) -> None` | Receives resolved credentials from `ProviderRegistry`. |
| `healthcheck` | `() -> HealthCheckResult` | Verifies the embedding function by embedding a health-check token. |
| `_hash_embed` | `(text: str) -> list[float]` | Internal deterministic hash-based pseudo-embedding. Unit-length but not semantically meaningful. |

### 5.2 `VectorStore`

In-memory vector store with a pgvector/Qdrant-compatible interface.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(dim: int = 256) -> None` | Initializes the store with expected vector dimension. |
| `upsert` | `(chunk: Chunk, vector: list[float]) -> None` | Writes or updates a chunk and its vector. Raises `ValueError` on dimension mismatch. |
| `upsert_batch` | `(items: list[tuple[Chunk, list[float]]]) -> int` | Batch-writes chunks and vectors, skipping mismatches. Returns the successful count. |
| `search` | `(query_vector: list[float], top_k: int = 10, filters: dict[str, Any] \| None = None) -> list[tuple[Chunk, float]]` | Returns the top-k chunks by cosine similarity, optionally filtered by metadata. |
| `get` | `(chunk_id: str) -> Chunk \| None` | Returns the chunk with the given ID or `None`. |
| `size` | `property -> int` | Returns the number of stored chunks. |
| `clear` | `() -> None` | Removes all chunks and vectors. |
| `_match_filters` | `@staticmethod (chunk: Chunk, filters: dict[str, Any] \| None) -> bool` | Checks whether a chunk matches the provided metadata filters. |

### 5.3 `BM25Index`

In-memory BM25 keyword index with Chinese-character and English-word tokenization.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(k1: float = 1.5, b: float = 0.75) -> None` | Initializes the index with BM25 parameters. |
| `upsert` | `(chunk: Chunk) -> None` | Writes or updates a chunk in the keyword index. |
| `upsert_batch` | `(chunks: list[Chunk]) -> int` | Batch-indexes chunks. Returns the number indexed. |
| `search` | `(query: str, top_k: int = 10, filters: dict[str, Any] \| None = None) -> list[tuple[Chunk, float]]` | Returns the top-k chunks by BM25 score, optionally filtered by metadata. |
| `size` | `property -> int` | Returns the number of indexed chunks. |
| `clear` | `() -> None` | Removes all indexed documents and resets statistics. |
| `_tokenize` | `@staticmethod (text: str) -> list[str]` | Tokenizes text into lowercase English words and individual Chinese characters. |

### 5.4 `IndexAuditor` and `IndexAuditRecord`

Records in-memory index operations for auditing.

**`IndexAuditRecord`** fields:

| Field | Type | Description |
|-------|------|-------------|
| `index_name` | `str` | Name of the index involved. |
| `index_version` | `str` | Version of the index. |
| `operation` | `str` | Operation type (`upsert`, `search`, `clear`). |
| `chunk_count` | `int` | Number of chunks affected. |
| `query_info` | `dict[str, Any]` | Query parameters for search operations. |
| `result_count` | `int` | Number of results returned. |
| `vector_count` | `int` | Number of chunks stored in the vector index. |
| `keyword_count` | `int` | Number of chunks stored in the keyword index. |
| `degraded` | `bool` | Whether the operation completed in a degraded state. |
| `error` | `str \| None` | Optional error message. |
| `timestamp` | `datetime` | UTC timestamp of the record. |

**`IndexAuditor`** methods:

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `() -> None` | Initializes an empty auditor. |
| `log_upsert` | `(index_name: str, index_version: str, chunk_count: int, *, vector_count: int = 0, keyword_count: int = 0, degraded: bool = False, error: str \| None = None) -> IndexAuditRecord` | Logs an indexing/upsert operation. |
| `log_search` | `(index_name: str, index_version: str, query_info: dict[str, Any], result_count: int, *, degraded: bool = False, error: str \| None = None) -> IndexAuditRecord` | Logs a search operation. |
| `records` | `property -> list[IndexAuditRecord]` | Returns a copy of all recorded audit entries. |

### 5.5 `EmbeddingPipeline`

Orchestrates embedding generation, vector storage, and keyword indexing.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(embedding_provider: EmbeddingProvider \| None = None, vector_store: VectorStore \| None = None, bm25_index: BM25Index \| None = None, auditor: IndexAuditor \| None = None) -> None` | Initializes the pipeline with default in-memory components. |
| `provider` | `property -> EmbeddingProvider` | Returns the configured embedding provider. |
| `vector_store` | `property -> VectorStore` | Returns the configured vector store. |
| `bm25_index` | `property -> BM25Index` | Returns the configured BM25 keyword index. |
| `auditor` | `property -> IndexAuditor` | Returns the configured auditor. |
| `index_chunks` | `(chunks: list[Chunk]) -> int` | Embeds and indexes chunks in both vector and keyword stores. Returns the keyword-indexed count. |
| `vector_search` | `(query_text: str, top_k: int = 10, filters: dict[str, Any] \| None = None) -> list[tuple[Chunk, float]]` | Searches the vector store using an embedding of the query text. |
| `keyword_search` | `(query: str, top_k: int = 10, filters: dict[str, Any] \| None = None) -> list[tuple[Chunk, float]]` | Searches the BM25 keyword index. |

### 5.6 `OpenAIEmbeddingProvider`

Defined in `src/margin/vector/providers/openai_embedding.py`.

HTTP adapter for OpenAI-compatible `/embeddings` APIs.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(*, api_key: str \| None = None, base_url: str \| None = None, model: str \| None = None, dimension: int \| None = None, client: Any \| None = None, timeout: float = 30.0) -> None` | Resolves config from arguments or `MARGIN_EMBEDDING_*` environment variables. Raises `RuntimeError` if `api_key` or `base_url` is missing. |
| `descriptor` | `property -> ProviderDescriptor` | Returns the provider descriptor. |
| `name` | `property -> str` | Returns the provider name (`openai_embedding`). |
| `version` | `property -> str` | Returns the configured model identifier. |
| `dim` | `property -> int` | Returns the expected embedding dimension. |
| `embed` | `(text: str) -> list[float]` | Embeds a single text string. |
| `embed_batch` | `(texts: list[str]) -> list[list[float]]` | Embeds a batch of texts via a single API call. Raises `RuntimeError` or `ValueError` on malformed responses. |
| `healthcheck` | `() -> HealthCheckResult` | Performs a lightweight health check against the embedding endpoint. |

---

## 6. Persistent Pipeline

Defined in `src/margin/vector/persistent_pipeline.py`.

### 6.1 `PersistentEmbeddingPipeline`

Exposes persistent chunks and embeddings through the same retrieval pipeline API used by the in-memory `EmbeddingPipeline`.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(*, embedding_provider: Any, repository: VectorRepository) -> None` | Initializes the pipeline with an embedding provider and a `VectorRepository`. |
| `vector_search` | `(query_text: str, top_k: int = 10, filters: dict[str, Any] \| None = None) -> list[tuple[Chunk, float]]` | Embeds the query and delegates vector search to `VectorRepository.search_vector`. |
| `keyword_search` | `(query: str, top_k: int = 10, filters: dict[str, Any] \| None = None) -> list[tuple[Chunk, float]]` | Retrieves candidate chunks from the repository and scores them by token overlap. |

### 6.2 `PersistentIndexingPipeline`

`PersistentIndexingPipeline` performs the production embedding write path.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(*, repository, embedding_provider, embedding_dimension, batch_size=64)` | Injects the repository, real embedding provider, expected dimension, and batch size. |
| `embed_and_persist` | `(chunks: list[Chunk]) -> list[str]` | Embeds chunks and validates the whole batch before writing vectors. A dimension mismatch writes no partial vectors. |

Embedding audit keys are generated with `EmbeddingKey(chunk_id, provider_name, model_name, model_version)`.

---

## 7. Retrieval

Defined in `src/margin/vector/retrieval.py` unless otherwise noted.

### 7.1 `SearchConstraints`

Constraints applied during retrieval.

| Attribute | Type | Description |
|-----------|------|-------------|
| `symbol` | `str \| None` | Legacy single-symbol filter. Required only when `security_ids` are not provided. |
| `security_ids` | `tuple[str, ...] \| None` | v0.2 preferred multi-security filter. Persistent retrieval joins `chunk_security_links`. |
| `decision_at` | `datetime \| None` | Point-in-time filter; only chunks with `available_at <= decision_at` are returned. |
| `doc_types` | `tuple[str, ...] \| None` | Optional tuple of document types to include. |
| `prefer_official` | `bool` | Whether to boost official evidence sources. Defaults to `True`. |
| `dedup` | `bool` | Whether to remove duplicate facts based on content hash. Defaults to `True`. |
| `require_locator` | `bool` | Whether to drop chunks lacking a page or text locator. Defaults to `True`. |

| Method | Signature | Description |
|--------|-----------|-------------|
| `normalize_decision_at` | `@field_validator("decision_at")` `classmethod` | Normalizes `decision_at` to UTC. |

### 7.2 `HybridWeights`

Fusion weights for hybrid retrieval.

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `vector` | `float` | `0.35` | Weight for dense vector similarity. |
| `keyword` | `float` | `0.25` | Weight for BM25 keyword score. |
| `time_decay` | `float` | `0.15` | Weight for recency-based time decay. |
| `source_quality` | `float` | `0.15` | Weight for source authority score. |
| `entity_match` | `float` | `0.10` | Weight for symbol/entity match score. |

| Method | Signature | Description |
|--------|-----------|-------------|
| `total` | `property -> float` | Returns the sum of all component weights. |

### 7.3 `HybridRetriever`

Fuses vector search with keyword search and applies retrieval constraints.

Score formula:

```text
Score = w_v * VectorScore + w_k * BM25 + w_t * TimeDecay
      + w_s * SourceQuality + w_e * EntityMatch
```

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(pipeline: EmbeddingPipeline \| VectorRepository, embedding_provider: Any \| None = None, weights: HybridWeights \| None = None, time_decay_days: float = 90.0) -> None` | Initializes the retriever. Passing a `VectorRepository` plus provider wraps it in a persistent pipeline. |
| `search` | `(query: str, top_k: int = 10, constraints: SearchConstraints \| None = None, security_ids: tuple[str, ...] \| None = None, decision_at: datetime \| None = None) -> list[RetrievalResult]` | Executes hybrid retrieval. Requires `symbol` or `security_ids`, and `decision_at`. |
| `_build_filters` | `(constraints: SearchConstraints) -> dict[str, Any]` | Builds metadata filters for the underlying search pipeline. |
| `_merge_and_score` | `(query: str, vector_results: list[tuple[Chunk, float]], keyword_results: list[tuple[Chunk, float]], constraints: SearchConstraints) -> list[RetrievalResult]` | Merges vector and keyword results, filters by `available_at` and locator requirements, and computes fused scores. |
| `_time_decay` | `(chunk: Chunk, decision_at: datetime) -> float` | Computes the exponential time decay score based on age relative to `decision_at`. |
| `_source_quality` | `(chunk: Chunk) -> float` | Computes source authority score (`L1=1.0`, `L2=0.8`, etc.). |
| `_entity_match` | `(chunk: Chunk, constraints: SearchConstraints) -> float` | Returns `1.0` if the chunk symbol matches the constraint symbol, otherwise `0.0`. |
| `_boost_official` | `(results: list[RetrievalResult]) -> list[RetrievalResult]` | Boosts official evidence sources (`L1-L3`) and re-sorts. |
| `_dedup_results` | `(results: list[RetrievalResult]) -> list[RetrievalResult]` | Removes duplicate facts based on normalized content hash. |

### 7.4 `Reranker`

Result reranker using an optional reranking provider. Includes a simple term-coverage fallback.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(rerank_func: Callable[[str, str], float] \| None = None) -> None` | Initializes the reranker with an optional scoring function. |
| `set_rerank_func` | `(func: Callable[[str, str], float]) -> None` | Injects a real reranking model function. |
| `rerank` | `(query: str, results: list[RetrievalResult], top_k: int \| None = None) -> list[RetrievalResult]` | Reranks retrieval results by combining the original score with the rerank score. |
| `_simple_rerank` | `@staticmethod (query: str, content: str) -> float` | Fallback reranker returning the fraction of query terms found in the content. |

### 7.5 `RetrievalTool`

Unified retrieval interface exposed to multi-agent research workflows.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(pipeline: EmbeddingPipeline, retriever: HybridRetriever \| None = None, reranker: Reranker \| None = None, use_rerank: bool = True) -> None` | Initializes the tool with an embedding pipeline and optional retriever/reranker. |
| `search` | `(query: str, symbol: str \| None = None, decision_at: datetime \| None = None, doc_types: list[str] \| None = None, top_k: int = 10, prefer_official: bool = True) -> list[RetrievalResult]` | Executes retrieval with constraints and optional reranking. Raises `ValueError` if `symbol` or `decision_at` is missing. |
| `search_by_symbol` | `(symbol: str, query: str = "", decision_at: datetime \| None = None, top_k: int = 10) -> list[RetrievalResult]` | Convenience wrapper that retrieves results filtered by stock symbol. |

### 7.6 `HTTPRerankProvider`

Defined in `src/margin/vector/providers/rerank.py`.

HTTP adapter for Cohere-style or OpenAI-compatible `/rerank` endpoints.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(*, api_key: str \| None = None, base_url: str \| None = None, model: str \| None = None, client: Any \| None = None, timeout: float = 30.0) -> None` | Resolves config from arguments or `MARGIN_RERANK_*` environment variables. Raises `RuntimeError` if `api_key` or `base_url` is missing. |
| `descriptor` | `property -> ProviderDescriptor` | Returns the provider descriptor. |
| `rerank` | `(query: str, documents: list[str]) -> list[float]` | Calls the `/rerank` endpoint and returns a relevance score per document. Supports `scores` and `results` response formats. |
| `healthcheck` | `() -> HealthCheckResult` | Performs a lightweight health check against the rerank endpoint. |

---

## 8. Indexing Runner

Defined in `src/margin/vector/indexing_runner.py`.

### 8.1 `DocumentIndexingRunner`

Worker that consumes document outbox events from module 03 and persists chunks/embeddings through `VectorRepository`.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(*, news_repository: NewsRepository, vector_repository: VectorRepository, embedding_provider: Any, chunker: Chunker \| None = None) -> None` | Initializes the runner with repositories, an embedding provider, and an optional chunker. |
| `run_once` | `(*, limit: int = 50) -> int` | Consumes one batch of `vector_index` outbox messages, chunks events, generates embeddings, persists data, records an audit, and marks messages delivered or failed. Returns the number of chunks indexed. |

| Helper Function | Signature | Description |
|-----------------|-----------|-------------|
| `_provider_name` | `(provider: Any) -> str` | Resolves the provider name from `provider.name` or `provider.descriptor.name`. |
| `_provider_version` | `(provider: Any) -> str` | Resolves the provider version from `provider.version` or `provider.descriptor.version`. |

### 8.2 `IndexingRunner`

v0.2 adds `IndexingRunner` for recoverable document-indexing outbox consumption.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(*, news_repository, vector_repository, embedding_provider, parser, chunker, lease_owner, lease_seconds=300)` | Injects the news repository, vector repository, parser, structured chunker, embedding provider, and lease owner. |
| `claim_next` | `(*, now=None) -> OutboxMessage \| None` | Claims a pending or expired `document_indexing` message. |
| `process_one` | `(*, event_id, now=None) -> bool` | Processes one outbox event. Parser success plus embedding failure is marked retryable instead of final. |

Outbox state is persisted through `NewsRepository.claim_outbox_with_lease`, `mark_outbox_succeeded`, `mark_outbox_retryable`, and `mark_outbox_failed_final`.

---

## 9. Repository

Defined in `src/margin/vector/repository.py`.

### 9.1 `VectorRepository`

PostgreSQL/pgvector persistence boundary for chunks, embeddings, indexing audits, and retrieval replay.

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(session_factory: Callable[[], Session], *, dimension: int) -> None` | Initializes the repository with a SQLAlchemy session factory and expected vector dimension. |
| `upsert_chunks` | `(chunks: list[Chunk], *, links: list[ChunkSecurityLink] \| None = None) -> int` | Persists chunk metadata idempotently and can write `chunk_security_links` in the same transaction. |
| `count_chunk_security_links` | `() -> int` | Returns the number of persisted chunk/security links. |
| `count_embeddings` | `() -> int` | Returns the number of persisted embedding rows. |
| `upsert_indexed_document` | `(document: IndexedDocument) -> None` | Persists document-level parser/chunker/embedding audit. |
| `get_indexed_document` | `(document_id: str) -> IndexedDocument \| None` | Reads document-level indexing audit. |
| `upsert_embeddings` | `(items: list[tuple[str, list[float]]], *, provider_name: str, model_name: str, model_version: str) -> int` | Persists model-versioned embeddings idempotently. Raises `ValueError` on dimension mismatch. |
| `search_vector` | `(query_vector: list[float], *, top_k=10, symbol=None, security_ids=None, decision_at=None, doc_types=None) -> list[tuple[Chunk, float]]` | Computes cosine similarity and filters by link-table security, PIT, and document type. |
| `get_chunk` | `(chunk_id: str) -> Chunk \| None` | Fetches a chunk by its stable identifier. |
| `list_chunks` | `(*, symbol=None, security_ids=None, decision_at=None, doc_types=None) -> list[Chunk]` | Lists active chunks ordered by `available_at`; supports `available_at <= decision_at` and link-table security filtering. |
| `record_index_audit` | `(*, operation: str, provider_name: str, model_name: str, model_version: str, chunk_count: int, vector_count: int, keyword_count: int, degraded: bool, error: str \| None = None) -> int` | Persists an indexing audit record and returns the generated `audit_id`. |
| `record_retrieval_audit` | `(*, query: str, constraints: dict, results: list[RetrievalResult]) -> int` | Persists replayable retrieval candidates and component scores, returning the generated `audit_id`. |
| `replay_retrieval` | `(audit_id: int) -> list[RetrievalResult]` | Replays a retrieval audit by looking up recorded chunk IDs. Raises `KeyError` if the audit or a referenced chunk is missing. |

| Private Helper | Signature | Description |
|----------------|-----------|-------------|
| `_chunk_to_row` | `(chunk: Chunk) -> ChunkRow` | Converts a `Chunk` domain object into a new `ChunkRow`. |
| `_update_chunk_row` | `(row: ChunkRow, chunk: Chunk) -> None` | Updates an existing `ChunkRow` in place from a `Chunk`. |
| `_chunk_from_row` | `(row: ChunkRow) -> Chunk` | Converts a `ChunkRow` into a frozen `Chunk` domain object. |
| `_cosine` | `(a: list[float], b: list[float]) -> float` | Computes cosine similarity between two equal-length vectors. |

---

## 10. Cross-Module Usage Notes

- **Module 03 (news/document ingestion)**: v0.2 uses `IndexingRunner` to consume document outbox messages, parse raw snapshots, and write `chunks`, `chunk_security_links`, `chunk_embeddings`, and `indexed_documents`.
- **Module 06 (multi-agent research)**: `RetrievalTool` / `HybridRetriever` expose PIT-safe evidence retrieval with `source_url`, `snapshot_id`, `SourceLocator`, `source_level`, and `trust_level`.
- **PIT retrieval**: callers must pass `decision_at`; repository queries enforce `ChunkRow.available_at <= decision_at`.
- **Provider registry**: `EmbeddingProvider` and `OpenAIEmbeddingProvider` implement provider descriptors compatible with `margin.core.provider`. `configure_secrets` allows credential injection from a central registry.
- **Persistence layers**: Two pipeline implementations coexist:
  - `EmbeddingPipeline` is fully in-memory and useful for tests and early development.
  - `PersistentIndexingPipeline` and `PersistentEmbeddingPipeline` delegate writes/search to `VectorRepository`, which maps to PostgreSQL tables defined in `db_models.py`.
- **Audit and replay**: Both `IndexAuditor` (in-memory) and `VectorRepository.record_index_audit` (persistent) capture indexing health. `VectorRepository.record_retrieval_audit` and `replay_retrieval` support reproducible retrieval evaluation.
- **Source locators**: Every `Chunk` can carry a unified `SourceLocator` plus legacy locator fields. `RetrievalTool` defaults to `require_locator=True`, ensuring returned evidence can be traced back to the original source.

### 10.1 Real Smoke

Run module 04 real smoke with:

```bash
python scripts/smoke_text_indexing.py
```

Required runtime configuration:

- `MARGIN_DATABASE_URL`
- `MARGIN_EMBEDDING_API_KEY`
- `MARGIN_EMBEDDING_BASE_URL`
- `MARGIN_EMBEDDING_MODEL`
- `MARGIN_EMBEDDING_DIMENSION`

Missing embedding configuration returns exit code `2` with `external_blocker=missing_embedding_config`. With complete configuration, the script writes a synthetic smoke chunk, generates a real embedding, persists `indexed_documents` and `chunk_embeddings`, and performs PIT retrieval by `security_id + decision_at`. Output includes only provider/model metadata, dimensions, counts, and chunk IDs; it does not print secrets or source text.
