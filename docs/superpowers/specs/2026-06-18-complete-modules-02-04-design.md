# Complete Modules 02-04 Design

## Scope

This delivery completes the currently partial work in:

- 0203 portfolio dashboard;
- 0301 filing acquisition;
- 0302 WebSearch provider;
- 0303 deduplication and compliance;
- 0401 parsing and chunking;
- 0402 embedding and vector indexing;
- 0403 hybrid retrieval and reranking.

Module 01 remains unchanged except where its Provider Registry is consumed.
Modules 05-10 are not implemented as part of this scope. Infrastructure added
here is limited to what modules 02-04 require.

## Delivery Strategy

The work is delivered as three vertical packages on `main`:

1. Shared PostgreSQL/pgvector infrastructure and 0203 Dashboard.
2. Persistent acquisition, WebSearch, and deduplication for 0301-0303.
3. Structured parsing, pgvector indexing, external model providers, and replay
   for 0401-0403.

Every package has an independently runnable API or worker path and automated
tests. PostgreSQL is the only relational persistence implementation. There is
no SQLite compatibility layer.

## Runtime Topology

Docker Compose provides:

- `postgres`: PostgreSQL 16 with the pgvector extension;
- `api`: FastAPI application;
- `worker`: acquisition and indexing worker;
- `web`: Next.js portfolio dashboard.

The Python package remains usable directly for unit tests. Integration tests
use the Compose PostgreSQL service through `MARGIN_DATABASE_URL`.

## Shared Persistence

SQLAlchemy 2 provides typed synchronous repositories and transactions. Alembic
owns schema migrations. PostgreSQL stores business records, audit records,
incremental cursors, queue state, and vectors.

Core tables:

- `portfolios`, `trades`, `position_theses`;
- `source_cursors`, `raw_snapshots`, `document_events`, `document_outbox`;
- `search_queries`, `search_results`;
- `dedup_records`, `repost_edges`;
- `chunks`, `chunk_embeddings`;
- `index_audit_records`, `retrieval_audit_records`.

Immutable records use insert-only repositories. Mutable operational state is
restricted to cursor advancement, outbox delivery state, and job state.
Transactions atomically persist a document event and its outbox message.

## 0203 Portfolio Dashboard

### Backend

FastAPI exposes the v0.1 contracts:

- `GET /api/v1/portfolios/{id}`;
- `GET /api/v1/portfolios/{id}/positions`;
- `POST /api/v1/portfolios/{id}/trades`;
- `POST /api/v1/portfolios/{id}/imports`;
- `GET /api/v1/portfolios/{id}/risk`;
- `GET /api/v1/positions/{id}/thesis`;
- `PUT /api/v1/positions/{id}/thesis`.

Repositories replace the in-memory portfolio, trade, and thesis collections.
Cost and risk calculations remain domain services. API responses use explicit
Pydantic schemas and convert missing resources to HTTP 404 and invalid imports
to HTTP 422.

### Frontend

The Next.js application opens directly on the portfolio workspace. It uses a
dense, restrained operational layout:

- top summary strip for assets, cash, market value, P&L, volatility, and
  drawdown;
- position table for repeated scanning and selection;
- exposure and event panels;
- position detail route with cost/P&L, thesis, invalidation conditions, and
  trade history;
- loading, empty, degraded-data, and API-error states.

The interface is responsive, uses compact typography, Lucide icons, and stable
table/panel dimensions. It does not include a marketing landing page.

## 0301 Filing Acquisition

### Connectors And Scheduling

Connectors expose paged discovery records with a stable source item ID, source
URL, publication time, and cursor. The first production connectors target the
public SSE and SZSE announcement interfaces. Their HTTP parsing is isolated
behind connector contracts so fixture tests do not require live networks.

APScheduler runs registered source jobs. A PostgreSQL advisory lock prevents
duplicate concurrent source runs. The cursor advances only after every item up
to that cursor has been persisted or explicitly recorded as failed.

### Snapshot, Parsing, And Publication

Raw bytes remain in file storage; PostgreSQL stores immutable snapshot
metadata. The parser returns structured paragraphs, pages, tables, and source
spans rather than only flattened text.

Document events are persisted with processing status and published through a
transactional outbox. Worker consumers claim outbox rows with
`FOR UPDATE SKIP LOCKED`, making delivery restart-safe and idempotent.

## 0302 WebSearch

The first concrete search adapter is Tavily because its result contract
includes URL, title, and content snippets. Provider code is isolated behind
`WebSearchProvider`, so another search service can be selected by
configuration without changing acquisition or compliance logic.

The service persists the query and every returned result before original-page
verification. Compliance enforcement includes:

- URL scheme and domain validation;
- `robots.txt` permission check using the Margin user agent;
- no retries around 401/403, login walls, or detected paywalls;
- no use of the search snippet as evidence;
- original-page snapshot required before a document event is emitted.

Network tests are divided into deterministic adapter tests using HTTP fixtures
and optional live tests enabled only when a token is configured.

## 0303 Deduplication And Compliance

The deduplication pipeline persists all comparison decisions and canonical
links. It checks URL, exact content hash, normalized title/date, SimHash, and
embedding cosine similarity.

Canonical selection is deterministic:

1. lower source level number wins;
2. earlier publication time wins within the same level;
3. earlier availability time breaks remaining ties;
4. event ID is the final stable tie-breaker.

Repost edges preserve the complete chain rather than only storing a duplicate
count. L4/L5 restrictions remain enforced by the immutable event model.

## 0401 Structured Parsing And Chunking

Parser output uses a shared structure:

- document title and type;
- ordered blocks;
- block kind (`heading`, `paragraph`, `table`, `caption`);
- page number when available;
- section path;
- paragraph index;
- table and row identifiers;
- source character span.

PDF parsing uses PyMuPDF when available and pypdf as a text fallback. HTML uses
BeautifulSoup. CSV and JSON tables preserve row identifiers. Parsing failure
keeps the raw snapshot, persists `PARSE_FAILED`, and never creates indexable
chunks.

Chunkers consume structured blocks so locators are inherited from the parser
instead of synthesized after flattening.

## 0402 Embedding And Vector Index

### Providers

The production embedding adapter uses an OpenAI-compatible embeddings endpoint.
Configuration:

- `MARGIN_EMBEDDING_BASE_URL`;
- `MARGIN_EMBEDDING_API_KEY`;
- `MARGIN_EMBEDDING_MODEL`;
- `MARGIN_EMBEDDING_DIMENSION`.

The existing deterministic hash provider remains a test-only/offline provider.
Provider health checks verify credentials, model access, and vector dimension.

### pgvector

Chunk metadata and vector rows are persisted transactionally. The vector column
uses a fixed configured dimension and an HNSW cosine index. Indexing is
idempotent by chunk ID and embedding model version.

BM25 remains an independent sparse path. A vector failure records degradation
without deleting or blocking the keyword index.

Index audit records persist:

- chunk and snapshot references;
- embedding provider/model/version;
- vector dimension;
- keyword index version;
- success counts, degraded state, and errors;
- input and output hashes.

## 0403 Retrieval And Replay

The public retrieval boundary requires `symbol` and `decision_at`. PostgreSQL
filters symbol, document type, locator availability, and
`available_at <= decision_at` before final ranking.

The production rerank adapter uses an OpenAI-compatible or Cohere-compatible
rerank endpoint selected by configuration. The local lexical reranker remains
the deterministic fallback.

Retrieval audit records persist the normalized query, constraints, weights,
provider/model versions, candidate chunk IDs and component scores, final
ranking, and result hash. Replay loads the recorded candidate set and versions;
it fails explicitly when required immutable inputs are missing.

## External Credentials

No token is required for database, API, frontend, scheduler, parser, repository,
or fixture-based integration tests.

Optional live tests require:

- `MARGIN_WEBSEARCH_API_KEY` for Tavily search;
- `MARGIN_EMBEDDING_API_KEY` plus base URL/model for embeddings;
- `MARGIN_RERANK_API_KEY` plus base URL/model for reranking.

Tokens are read through the existing SecretManager/environment mechanism and
must not be committed or pasted into documentation.

## Error Handling And Degradation

- PostgreSQL unavailable: API returns service unavailable; workers do not
  acknowledge jobs.
- Connector unavailable: cursor does not advance beyond unprocessed items.
- Parsing failed: snapshot retained, event marked failed, no chunks emitted.
- WebSearch unavailable: existing filing and snapshot corpus remains usable.
- Embedding or pgvector unavailable: BM25 retrieval remains available and the
  audit record is degraded.
- Reranker unavailable: hybrid order is returned.
- Missing PIT or locator metadata: result is rejected rather than guessed.

## Testing And Review

Testing layers:

1. pure unit tests for domain behavior;
2. repository tests against PostgreSQL + pgvector;
3. FastAPI route tests;
4. worker/outbox restart and idempotency tests;
5. Next.js component and browser workflow tests;
6. fixture-based HTTP adapter tests;
7. optional live Provider smoke tests.

Each implementation package ends with:

- focused tests;
- full `pytest`;
- Python Ruff checks;
- frontend lint/typecheck/tests;
- Docker Compose health verification;
- code review against the v0.1 spec and plan;
- `AGENTS.md` status update only when every acceptance action is satisfied.
