# News Acquisition And Compliance Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete plans 0301-0303 with restart-safe acquisition, concrete WebSearch integration, robots-aware original verification, and persistent dedup/repost audit.

**Architecture:** PostgreSQL stores cursors, snapshot metadata, document events, outbox messages, search records, and dedup decisions. Public source connectors and Tavily are adapters behind existing contracts. Workers use advisory locks and transactional outbox claims for idempotent processing.

**Tech Stack:** SQLAlchemy 2, Alembic, PostgreSQL 16, APScheduler, HTTPX, BeautifulSoup, Tavily HTTP API, pytest

---

### Task 1: News Persistence Schema

**Files:**
- Create: `src/margin/news/db_models.py`
- Create: `src/margin/news/repository.py`
- Create: `alembic/versions/20260618_0002_news.py`
- Test: `tests/news/test_repository_postgres.py`

- [ ] Write failing tests for immutable snapshots/events, cursor upsert, query/result persistence, and duplicate/repost records.
- [ ] Add rows for `source_cursors`, `raw_snapshots`, `document_events`, `document_outbox`, `search_queries`, `search_results`, `dedup_records`, and `repost_edges`.
- [ ] Implement repository transactions, uniqueness constraints, and domain-model conversion.
- [ ] Run migration and focused tests.

### Task 2: Discovery Connectors And Incremental Runner

**Files:**
- Create: `src/margin/news/discovery.py`
- Create: `src/margin/news/connectors.py`
- Create: `src/margin/news/scheduler.py`
- Modify: `src/margin/news/acquirer.py`
- Test: `tests/news/test_discovery.py`
- Test: `tests/news/test_scheduler.py`

- [ ] Write fixture-driven tests for paged SSE/SZSE announcement discovery and stable cursors.
- [ ] Define `DiscoveredDocument` and `DiscoveryConnector`.
- [ ] Implement SSE and SZSE response adapters without embedding endpoint-specific logic in the runner.
- [ ] Implement `IncrementalAcquisitionRunner` with PostgreSQL advisory lock, per-item persistence, and cursor advancement only after handled items.
- [ ] Configure APScheduler jobs from registered sources.
- [ ] Verify retries do not duplicate events or outbox rows.

### Task 3: Transactional Event Publisher

**Files:**
- Create: `src/margin/news/outbox.py`
- Modify: `src/margin/news/acquirer.py`
- Test: `tests/news/test_outbox.py`

- [ ] Write tests for atomic event/outbox insertion, `SKIP LOCKED` claiming, acknowledgement, failure recording, and restart recovery.
- [ ] Implement `DocumentEventPublisher.persist_pending`.
- [ ] Implement `OutboxConsumer.claim_batch`, `mark_delivered`, and `mark_failed`.
- [ ] Ensure parse-failed events are persisted but never published as indexable events.

### Task 4: Tavily Provider And Search Audit

**Files:**
- Create: `src/margin/news/providers/__init__.py`
- Create: `src/margin/news/providers/tavily.py`
- Modify: `src/margin/news/websearch.py`
- Test: `tests/news/test_tavily.py`
- Test: `tests/news/test_websearch_repository.py`

- [ ] Write HTTP fixture tests for authentication, result mapping, rate-limit errors, and malformed responses.
- [ ] Implement `TavilySearchAdapter` using injected HTTPX client and `MARGIN_WEBSEARCH_API_KEY`.
- [ ] Persist query and every raw result before original-content verification.
- [ ] Add an optional live smoke test marked `live` and skipped without the token.

### Task 5: Robots And Original-Page Compliance

**Files:**
- Create: `src/margin/news/robots.py`
- Modify: `src/margin/news/acquirer.py`
- Modify: `src/margin/news/websearch.py`
- Test: `tests/news/test_robots.py`
- Test: `tests/news/test_websearch.py`

- [ ] Write tests for allowed/disallowed robots rules, cached robots files, invalid schemes, redirects, 401/403, paywalls, and inaccessible originals.
- [ ] Implement a robots checker using `urllib.robotparser` and Margin user agent.
- [ ] Reject disallowed URLs before downloading content.
- [ ] Persist compliance rejection reason without creating a document event.

### Task 6: Persistent Vector Dedup And Repost Chains

**Files:**
- Modify: `src/margin/news/dedup.py`
- Modify: `src/margin/news/repository.py`
- Test: `tests/news/test_dedup_postgres.py`

- [ ] Write tests that dedup decisions survive process restart and preserve the full repost chain.
- [ ] Add an injected vector similarity function with deterministic threshold behavior.
- [ ] Implement deterministic canonical selection by source level, publication time, availability time, and event ID.
- [ ] Persist every comparison reason and canonical edge.
- [ ] Verify L4/L5 state-change restrictions remain intact.

### Task 7: Worker Integration And Review

**Files:**
- Create: `src/margin/worker.py`
- Modify: `docker-compose.yml`
- Test: `tests/integration/test_news_pipeline_postgres.py`

- [ ] Wire scheduler, connectors, acquisition runner, outbox consumer, and dedup processor.
- [ ] Add fixture-based end-to-end tests from discovery through persisted unique events.
- [ ] Verify worker restart and duplicate delivery behavior.
- [ ] Run full tests, Ruff, Compose health checks, and code review against 0301-0303 acceptance actions.

