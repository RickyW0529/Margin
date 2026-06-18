# Portfolio Dashboard And PostgreSQL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete plan 0203 with PostgreSQL persistence, the documented FastAPI contracts, and a usable Next.js portfolio workspace.

**Architecture:** SQLAlchemy repositories persist portfolios, trades, and thesis versions in PostgreSQL. Existing cost and risk domain services remain pure. FastAPI uses the PostgreSQL repository, while unit tests may inject the in-memory repository. Next.js consumes the versioned API and opens directly on the portfolio dashboard.

**Tech Stack:** Python 3.11+, SQLAlchemy 2, Alembic, psycopg 3, PostgreSQL 16, FastAPI, Pydantic 2, Next.js, TypeScript, Vitest, Playwright

---

### Task 1: Runtime Dependencies And PostgreSQL Service

**Files:**
- Modify: `pyproject.toml`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `src/margin/storage/__init__.py`
- Create: `src/margin/storage/database.py`
- Test: `tests/storage/test_database.py`

- [ ] Add a failing test that constructs `DatabaseSettings` from `MARGIN_DATABASE_URL` and opens a SQLAlchemy session.
- [ ] Run `pytest tests/storage/test_database.py -q` and confirm import failure.
- [ ] Add SQLAlchemy, Alembic, psycopg, pgvector, FastAPI, Uvicorn, APScheduler, HTTPX, BeautifulSoup, and pypdf dependencies.
- [ ] Implement `DatabaseSettings`, `create_database_engine`, and `create_session_factory`.
- [ ] Add a Compose `postgres` service using `pgvector/pgvector:pg16`, healthcheck `pg_isready`, database `margin`, user `margin`, and a named volume.
- [ ] Add `.env.example` with `MARGIN_DATABASE_URL=postgresql+psycopg://margin:margin@localhost:5432/margin`.
- [ ] Start PostgreSQL and run the focused test.

### Task 2: Portfolio Schema And Migration

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/20260618_0001_portfolio.py`
- Create: `src/margin/storage/base.py`
- Create: `src/margin/portfolio/db_models.py`
- Test: `tests/portfolio/test_repository_postgres.py`

- [ ] Write repository integration tests that insert a portfolio, append immutable trades, append thesis versions, and survive a new session.
- [ ] Run the integration tests and confirm missing schema/repository failures.
- [ ] Define `PortfolioRow`, `TradeRow`, and `PositionThesisRow` with UTC timestamps, numeric financial columns, unique IDs, and thesis uniqueness on `(position_id, version)`.
- [ ] Configure Alembic metadata and create the initial migration.
- [ ] Run `alembic upgrade head`.
- [ ] Verify the `vector` extension is enabled and the three portfolio tables exist.

### Task 3: Repository Boundary

**Files:**
- Create: `src/margin/portfolio/repository.py`
- Modify: `src/margin/portfolio/service.py`
- Modify: `src/margin/portfolio/__init__.py`
- Test: `tests/portfolio/test_repository.py`
- Test: `tests/portfolio/test_service.py`

- [ ] Write tests for the `PortfolioRepository` contract using `MemoryPortfolioRepository`.
- [ ] Write tests that `SQLAlchemyPortfolioRepository` returns domain models and preserves thesis history order.
- [ ] Implement repository methods:

```python
class PortfolioRepository(Protocol):
    def add_portfolio(self, portfolio: Portfolio) -> None: ...
    def get_portfolio(self, portfolio_id: str) -> Portfolio | None: ...
    def update_portfolio(self, portfolio: Portfolio) -> None: ...
    def add_trades(self, trades: list[Trade]) -> None: ...
    def list_trades(self, portfolio_id: str) -> list[Trade]: ...
    def add_thesis(self, portfolio_id: str, thesis: PositionThesis) -> None: ...
    def list_theses(self, portfolio_id: str, position_id: str | None = None) -> list[PositionThesis]: ...
```

- [ ] Refactor `PortfolioService` to use an injected repository and remove direct collection ownership.
- [ ] Keep `PortfolioService()` backward compatible by defaulting to `MemoryPortfolioRepository`.
- [ ] Run all portfolio tests.

### Task 4: FastAPI Portfolio Contracts

**Files:**
- Create: `src/margin/api/__init__.py`
- Create: `src/margin/api/dependencies.py`
- Create: `src/margin/api/main.py`
- Create: `src/margin/api/schemas.py`
- Create: `src/margin/api/routes/__init__.py`
- Create: `src/margin/api/routes/portfolios.py`
- Test: `tests/api/test_portfolios.py`

- [ ] Write failing TestClient tests for all documented 0203 routes, including 404 and 422 responses.
- [ ] Implement request schemas for trade creation, CSV import, and thesis updates.
- [ ] Implement dependency injection for session factory, repository, and `PortfolioService`.
- [ ] Implement:

```text
GET  /api/v1/portfolios/{id}
GET  /api/v1/portfolios/{id}/positions
POST /api/v1/portfolios/{id}/trades
POST /api/v1/portfolios/{id}/imports
GET  /api/v1/portfolios/{id}/risk
GET  /api/v1/positions/{id}/thesis
PUT  /api/v1/positions/{id}/thesis
```

- [ ] Make `GET /portfolios/{id}` return the dashboard overview and raw portfolio identity.
- [ ] Map missing resources to 404 and import validation failures to structured 422 responses.
- [ ] Run API and portfolio tests.

### Task 5: Next.js Workspace

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/next.config.ts`
- Create: `web/eslint.config.mjs`
- Create: `web/app/globals.css`
- Create: `web/app/layout.tsx`
- Create: `web/app/page.tsx`
- Create: `web/app/portfolios/[portfolioId]/page.tsx`
- Create: `web/app/positions/[positionId]/page.tsx`
- Create: `web/components/portfolio-workspace.tsx`
- Create: `web/components/position-detail.tsx`
- Create: `web/lib/api.ts`
- Test: `web/components/portfolio-workspace.test.tsx`

- [ ] Scaffold Next.js with TypeScript, React, Lucide, Vitest, and Testing Library.
- [ ] Write component tests for populated, empty, loading, and API-error states.
- [ ] Implement API types and fetch functions.
- [ ] Implement the overview summary strip, position table, exposure panels, event list, and detail view.
- [ ] Use stable responsive tracks, compact typography, semantic status colors, and icon buttons with labels/tooltips.
- [ ] Run `npm test`, `npm run lint`, and `npm run build`.

### Task 6: Service Images And End-To-End Verification

**Files:**
- Create: `Dockerfile.api`
- Create: `Dockerfile.web`
- Modify: `docker-compose.yml`
- Create: `scripts/seed_portfolio.py`
- Test: `tests/integration/test_portfolio_api_postgres.py`

- [ ] Add `api` and `web` services to Compose.
- [ ] Add a deterministic seed command that inserts one portfolio, trades, and thesis records without overwriting existing IDs.
- [ ] Write an integration test that migrates a clean database, seeds data, and calls the live API.
- [ ] Start Compose and verify service health.
- [ ] Use Playwright to inspect desktop and mobile dashboard views, including no-overlap and text-fit checks.
- [ ] Run full Python and frontend verification.

