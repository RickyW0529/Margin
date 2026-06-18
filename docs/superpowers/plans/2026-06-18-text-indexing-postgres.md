# Text Indexing PostgreSQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete plans 0401-0403 with structured locators, OpenAI-compatible embeddings, pgvector persistence, provider-backed reranking, and persistent retrieval replay.

**Architecture:** Parsers emit structured blocks with exact source locators. Chunk and vector repositories store immutable metadata and model-versioned vectors in PostgreSQL/pgvector. Hybrid retrieval filters PIT constraints in SQL, degrades to BM25, and records a replayable candidate/ranking audit.

**Tech Stack:** PyMuPDF, pypdf, BeautifulSoup, SQLAlchemy 2, PostgreSQL 16, pgvector, OpenAI-compatible HTTP APIs, pytest

---

### Task 1: Structured Parser Models

**Files:**
- Create: `src/margin/news/parsed.py`
- Modify: `src/margin/news/acquirer.py`
- Test: `tests/news/test_structured_parser.py`

- [ ] Write failing tests for HTML headings/paragraph spans, PDF page numbers, CSV table rows, JSON rows, and parse failures.
- [ ] Define immutable `ParsedBlock` and `ParsedDocument`.
- [ ] Implement BeautifulSoup HTML extraction with ordered paragraph indices and source spans.
- [ ] Implement PyMuPDF page extraction with pypdf fallback.
- [ ] Implement CSV/JSON table IDs and row IDs.
- [ ] Return `PARSE_FAILED` rather than empty ready content when no usable blocks exist.

### Task 2: Locator-Preserving Chunking

**Files:**
- Modify: `src/margin/vector/models.py`
- Modify: `src/margin/vector/chunker.py`
- Test: `tests/vector/test_structured_chunker.py`

- [ ] Write tests that every chunk inherits the originating page, section, paragraph, table row, and quote span.
- [ ] Add structured-block chunk entry points while preserving DocumentEvent compatibility.
- [ ] Split oversized blocks without losing adjusted quote spans.
- [ ] Verify reports, filings, news, IR, industry reports, and user notes.

### Task 3: Vector Schema And Repository

**Files:**
- Create: `src/margin/vector/db_models.py`
- Create: `src/margin/vector/repository.py`
- Create: `alembic/versions/20260618_0003_vector.py`
- Test: `tests/vector/test_repository_postgres.py`

- [ ] Write failing tests for chunk idempotency, model-versioned embeddings, metadata filters, and PIT SQL filtering.
- [ ] Add `chunks`, `chunk_embeddings`, `index_audit_records`, and `retrieval_audit_records`.
- [ ] Use pgvector `VECTOR(dimension)` and HNSW cosine index.
- [ ] Implement transactional upsert and search methods.
- [ ] Run migration and repository tests.

### Task 4: OpenAI-Compatible Embedding Provider

**Files:**
- Create: `src/margin/vector/providers/__init__.py`
- Create: `src/margin/vector/providers/openai_embedding.py`
- Modify: `src/margin/vector/embedding.py`
- Test: `tests/vector/test_openai_embedding.py`

- [ ] Write HTTP fixture tests for batches, dimensions, auth errors, retries, and malformed vectors.
- [ ] Implement an OpenAI-compatible adapter configured by base URL, API key, model, and dimension.
- [ ] Register the provider through `ProviderRegistry`.
- [ ] Add an optional live smoke test skipped without embedding configuration.

### Task 5: Persistent Indexing And Audit

**Files:**
- Modify: `src/margin/vector/embedding.py`
- Modify: `src/margin/vector/repository.py`
- Test: `tests/vector/test_indexing_postgres.py`

- [ ] Write tests for keyword-first indexing, vector degradation, idempotent replay, and persisted audit hashes.
- [ ] Persist chunks before embedding and BM25 metadata independently.
- [ ] Persist vectors by provider/model/version.
- [ ] Record input/output hashes, counts, errors, and degraded state.

### Task 6: Provider-Backed Reranking

**Files:**
- Create: `src/margin/vector/providers/rerank.py`
- Modify: `src/margin/vector/retrieval.py`
- Test: `tests/vector/test_rerank_provider.py`

- [ ] Write fixture tests for OpenAI-compatible and Cohere-compatible response shapes.
- [ ] Implement provider descriptor, secret injection, healthcheck, and batch reranking.
- [ ] Preserve lexical reranking as deterministic fallback.
- [ ] Add an optional live smoke test skipped without rerank configuration.

### Task 7: Persistent Hybrid Retrieval And Replay

**Files:**
- Modify: `src/margin/vector/retrieval.py`
- Modify: `src/margin/vector/repository.py`
- Test: `tests/vector/test_retrieval_postgres.py`
- Test: `tests/vector/test_replay.py`

- [ ] Write tests for SQL symbol/doc-type/PIT/locator filtering and BM25 degradation.
- [ ] Persist normalized query, constraints, weights, provider versions, candidates, component scores, ranks, and result hash.
- [ ] Implement `replay(retrieval_audit_id)` using the recorded immutable candidate set.
- [ ] Fail replay explicitly when a recorded chunk or model version is unavailable.

### Task 8: Worker Integration And Review

**Files:**
- Modify: `src/margin/worker.py`
- Modify: `docker-compose.yml`
- Test: `tests/integration/test_indexing_pipeline_postgres.py`

- [ ] Consume document outbox records and index ready events exactly once.
- [ ] Add end-to-end tests from structured snapshot through retrieval and replay.
- [ ] Verify embedding, vector-store, and reranker degradation paths.
- [ ] Run full Python/frontend verification, Compose health checks, and code review against 0401-0403 acceptance actions.

