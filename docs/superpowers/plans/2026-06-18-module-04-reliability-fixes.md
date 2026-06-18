# Module 04 Reliability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce the text-indexing PIT, locator, degradation, and audit contracts without overstating external backend support.

**Architecture:** Chunking rejects non-ready documents and creates deterministic, immutable, source-linked chunks. Indexing keeps BM25 available independently of vector failures. Retrieval requires symbol and decision time, normalizes timestamps to UTC, filters locators and document types, and degrades around vector and rerank failures.

**Tech Stack:** Python 3.11, Pydantic 2, pytest, Ruff

---

### Task 1: Regression Tests

**Files:**
- Modify: `tests/vector/test_chunker.py`
- Modify: `tests/vector/test_embedding.py`
- Modify: `tests/vector/test_retrieval.py`

- [x] Add tests for parse-failed isolation, hard chunk size, IR pairs, multi-symbol chunks, deterministic content hashes, BM25 replacement, ProviderRegistry integration, vector degradation, mandatory PIT constraints, UTC comparison, locator filtering, multi-type filtering, fact deduplication, and rerank degradation.
- [x] Run `pytest tests/vector -q` and confirm the tests fail for the reviewed defects.

### Task 2: Chunk Integrity

**Files:**
- Modify: `src/margin/vector/models.py`
- Modify: `src/margin/vector/chunker.py`

- [x] Normalize timestamps to UTC and replace mutable collections with tuples.
- [x] Make content hashes content-based and chunk IDs deterministic.
- [x] Propagate snapshot references and generate one filterable chunk per symbol.
- [x] Split oversized parts and combine IR question-answer pairs.
- [x] Reject non-ready document events.
- [x] Run `pytest tests/vector/test_chunker.py -q`.

### Task 3: Indexing And Degradation

**Files:**
- Modify: `src/margin/vector/embedding.py`
- Modify: `tests/vector/test_embedding.py`

- [x] Implement the core BaseProvider descriptor, healthcheck, and secret hook.
- [x] Make BM25 replacement idempotent.
- [x] Index BM25 before attempting embeddings and record degraded vector state.
- [x] Preserve immutable vectors and complete audit filters.
- [x] Run `pytest tests/vector/test_embedding.py -q`.

### Task 4: Retrieval Contract

**Files:**
- Modify: `src/margin/vector/retrieval.py`
- Modify: `tests/vector/test_retrieval.py`

- [x] Require symbol and decision time at public retrieval boundaries.
- [x] Compare timestamps in UTC and compute time decay from decision time.
- [x] Support all requested document types and enforce locator requirements.
- [x] Degrade vector and rerank failures to the remaining retrieval path.
- [x] Rank through model copies and deduplicate by normalized content hash.
- [x] Run `pytest tests/vector/test_retrieval.py -q`.

### Task 5: Status And Verification

**Files:**
- Modify: `AGENTS.md`

- [x] Mark 0401-0403 partial with explicit missing external capabilities.
- [x] Run `pytest`.
- [x] Run `ruff check src tests`.
- [x] Run `git diff --check`.
