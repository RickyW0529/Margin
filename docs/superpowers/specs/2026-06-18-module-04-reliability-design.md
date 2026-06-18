# Module 04 Reliability Design

## Scope

This repair makes the in-memory text indexing implementation enforce the v0.1
retrieval contract. It does not claim to implement pgvector, Qdrant, external
Embedding/Rerank providers, persistent audit storage, or replay across process
restarts.

## Data Integrity

- Documents with a non-ready processing status do not produce chunks.
- Chunk content hashes identify exact content independently of document ID.
- Retrieval deduplication separately normalizes whitespace and case for
  cross-document fact matching.
- Chunk IDs are deterministic for a document, position, and symbol.
- Snapshot references and source locators propagate from document events.
- Frozen models use immutable collections.

## Chunking

- Oversized text parts are split to the configured maximum size.
- Overlap is character-based and validated to be smaller than the maximum size.
- IR questions and answers are emitted as pairs.
- Multi-symbol documents produce independently filterable chunks for each symbol.

## Indexing And Degradation

- Keyword indexing happens even when embedding generation or vector storage fails.
- Vector search failures degrade to keyword retrieval.
- BM25 upserts replace prior document-frequency contributions instead of
  accumulating corrupt statistics.
- EmbeddingProvider follows the core ProviderRegistry contract.
- In-memory audit records include degradation state and complete search filters.

## Retrieval Contract

- Symbol and decision time are mandatory.
- All comparisons normalize timestamps to UTC.
- Time decay is computed relative to decision time for deterministic replay.
- Multiple document types are supported.
- Locator-required searches reject chunks without a usable original locator.
- Ranking creates new immutable result objects rather than mutating frozen models.
- Rerank failures return the hybrid order.

## Verification

Regression tests cover each reviewed failure, followed by vector-only and full
repository pytest and Ruff runs.
