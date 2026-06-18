# Module 03 Reliability Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make module 03 fail closed, keep WebSearch audit data consistent with acquired originals, and retain the most reliable canonical source during deduplication.

**Architecture:** Acquisition validates transport before persistence and records parsing status on immutable document events. WebSearch verification returns the parsed original plus snapshot metadata so the query record and emitted event reference the same source. Deduplication selects canonical events by authority and publication time without mutating input models.

**Tech Stack:** Python 3.11, Pydantic 2, pytest, Ruff

---

### Task 1: Add Regression Coverage

**Files:**
- Modify: `tests/news/test_acquirer.py`
- Modify: `tests/news/test_websearch.py`
- Modify: `tests/news/test_dedup.py`

- [ ] Add tests for non-2xx rejection, duplicate timeout handling, parse-failure degradation, API-key injection, original-content events, audit metadata, authority-first deduplication, timezone-aware scoring, and immutable symbol collections.
- [ ] Run `pytest tests/news -q` and confirm the new tests fail for the reviewed defects.

### Task 2: Fix Acquisition and Event Models

**Files:**
- Modify: `src/margin/news/models.py`
- Modify: `src/margin/news/acquirer.py`

- [ ] Normalize event timestamps to UTC and represent symbol collections as tuples.
- [ ] Add processing status and snapshot hash fields to document events.
- [ ] Reject non-2xx or empty downloads before snapshot persistence.
- [ ] Preserve failed-parse snapshots while marking emitted events ineligible to change research state.
- [ ] Run `pytest tests/news/test_acquirer.py -q`.

### Task 3: Fix WebSearch Verification

**Files:**
- Modify: `src/margin/news/websearch.py`
- Modify: `tests/news/test_websearch.py`

- [ ] Add ProviderRegistry-compatible secret configuration.
- [ ] Return verified original content and snapshot metadata from verification.
- [ ] Emit events from parsed original content rather than search snippets.
- [ ] Return query records updated with accessibility, snapshot ID, and snapshot hash.
- [ ] Remove rejected paywall snapshots.
- [ ] Run `pytest tests/news/test_websearch.py -q`.

### Task 4: Fix Deduplication and Scoring

**Files:**
- Modify: `src/margin/news/dedup.py`
- Modify: `tests/news/test_dedup.py`

- [ ] Select canonical documents by source authority, then publication time.
- [ ] Record canonical event IDs without mutating frozen input events.
- [ ] Score timezone-aware timestamps safely.
- [ ] Run `pytest tests/news/test_dedup.py -q`.

### Task 5: Correct Completion Status and Verify

**Files:**
- Modify: `AGENTS.md`

- [ ] Mark module 03 as partial until scheduling, real exchange connectors, vector deduplication, and event publishing are implemented.
- [ ] Run `pytest`.
- [ ] Run `ruff check src tests`.
- [ ] Run `git diff --check`.
- [ ] Review `git status --short --branch`, commit the complete user-approved worktree, and push `main`.
