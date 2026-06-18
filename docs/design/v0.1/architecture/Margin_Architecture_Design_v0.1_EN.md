# Margin（安全边际）Open-Source Investment Research System — Architecture Design v0.1

> Type: System Architecture Document  
> Version: v0.1  
> Architecture style: Modular monolith first, asynchronous workers, provider-based integration, plugin-based extension  
> Deployment target: Local single-user first, extensible to hosted multi-user deployments  
> Recommended stack: FastAPI + PostgreSQL + Parquet/DuckDB + pgvector/Qdrant + Provider Registry + LangGraph/custom orchestration + Next.js + Docker Compose

---

## 1. Architecture Goals

- Implement the eight product layers with explicit boundaries;
- Separate structured financial data from unstructured text;
- Enforce point-in-time correctness;
- Require evidence lineage for material AI conclusions;
- Allow users to configure strategies, prompts, models, sources, and thresholds;
- Support Provider, MCP, and tool plugins;
- Use one research signal, state, and evidence model across candidate and holdings dashboards;
- Version models, prompts, tools, strategies, providers, and data snapshots;
- Separate nightly batch research from intraday monitoring;
- Run the MVP on a 4C8G host without a GPU.

---

## 2. Eight-Layer Architecture

```mermaid
flowchart TB
    subgraph L1[1. Data Layer]
        D1[Market]
        D2[Fundamentals]
        D3[Index/Industry/Macro]
        D4[Corporate Actions]
        D5[User Trades and Positions]
    end

    subgraph L2[2. Data Storage Layer]
        S1[(PostgreSQL)]
        S2[(Parquet/DuckDB)]
        S3[(Raw Object Storage)]
        S4[Point-in-Time Dataset]
        S5[Audit and Versioning]
    end

    subgraph L3[3. News and WebSearch Acquisition Layer]
        N1[Exchange Filings]
        N2[Reports and IR]
        N3[Industry Data]
        N4[WebSearch/News/RSS]
        N5[Deduplication and Quality]
    end

    subgraph L4[4. Text Vector Database]
        V1[Parsing]
        V2[Chunking and Metadata]
        V3[Embeddings]
        V4[(Vector Store)]
        V5[Hybrid Retrieval and Rerank]
    end

    subgraph L5[5. AI Layer]
        A1[Routing]
        A2[Provider Layer]
        A3[RAG Evidence]
        A4[Tools]
        A5[Multi-Agent Orchestration]
        A6[MCP]
        A7[Model Gateway]
        A8[Structured Output and Guardrails]
    end

    subgraph L6[6. Research Signal Strategy Configuration]
        C1[Templates]
        C2[Custom Prompts]
        C3[Factors/Valuation/Risk]
        C4[Versions and Backtests]
    end

    subgraph L7[7. Research Candidate Dashboard]
        R1[Candidates]
        R2[Evidence and Valuation]
        R3[Catalysts and Risks]
        R4[Conditional Research Plans]
    end

    subgraph L8[8. Current Holdings Dashboard]
        P1[Positions and Trades]
        P2[Portfolio Risk]
        P3[Thesis State]
        P4[Intraday Alerts]
    end

    L1 --> L2
    L3 --> L2
    L3 --> L4
    L2 --> L5
    L4 --> L5
    L6 --> L5
    L5 --> L7
    L2 --> L8
    L7 --> L8
```

Cross-cutting concerns:

- Authentication and authorization;
- Scheduling;
- Audit and tracing;
- Observability;
- Secret management;
- Provider and plugin registries;
- Data quality and quarantine.

---

# Layer 1 — Data

## 3. Data Domains and Provider Protocols

| Domain | Content |
|---|---|
| Market | OHLCV, turnover, adjustments |
| Fundamental | Statements, ratios, dividends, estimates |
| Metadata | Symbols, industries, listing status, index membership |
| Corporate actions | Suspensions, distributions, splits, delisting |
| Industry and macro | Prices, inventory, rates, PMI, sales |
| User | Portfolio, trades, cash, preferences |
| Derived | Factors, model inputs, regimes |

Provider protocol:

```python
class MarketDataProvider:
    def get_securities(self, as_of): ...
    def get_bars(self, symbols, start, end, frequency="1d"): ...
    def get_adjustment_factors(self, symbols, start, end): ...
    def get_financials(self, symbols, start, end): ...
    def get_index_members(self, index_code, as_of): ...
```

### 3.1 MVP Data Providers and Licensing Boundary

MVP includes only two structured A-share data providers:

- `AKShareProvider` for market, basic financial, index, and some filing metadata;
- `TushareProvider` for supplemental market, financial, and index membership data, with user-provided token.

Each provider records source, local Secret reference, rate limits, field authorization note, `fetched_at`, `available_at`, and raw response hash. The open-source repository provides connector code and sample mappings, not commercial datasets, paid research reports, or copyrighted sample corpora.

### 3.2 Point-in-Time Fields

```text
event_at
published_at
available_at
fetched_at
revised_at
```

```mermaid
flowchart TD
    A[Feature Request at decision_at] --> B[Read Data]
    B --> C{available_at <= decision_at?}
    C -->|Yes| D[Allow]
    C -->|No| E[Reject and Log Leakage Risk]
```

---

# Layer 2 — Data Storage

## 4. Storage Components

| Storage | Purpose |
|---|---|
| PostgreSQL | Business entities, strategies, research signals, portfolios |
| Parquet | Market, features, and backtest datasets |
| DuckDB | Local analytical queries |
| Object storage | Raw PDF, HTML, JSON, CSV snapshots |
| pgvector/Qdrant | Text vectors |
| Redis optional | Cache, locks, task state |

```mermaid
flowchart LR
    ODS[Raw ODS] --> DWD[Normalized Detail]
    DWD --> PIT[Point-in-Time]
    PIT --> DWS[Features and Subjects]
    DWS --> ADS[Research Signals and Dashboards]
```

```mermaid
erDiagram
    USER ||--o{ STRATEGY_PROFILE : owns
    USER ||--o{ PORTFOLIO : owns
    PORTFOLIO ||--o{ POSITION : contains
    PORTFOLIO ||--o{ TRADE : records
    SECURITY ||--o{ MARKET_BAR : has
    SECURITY ||--o{ FINANCIAL_FACT : has
    SECURITY ||--o{ NEWS_DOCUMENT : related
    NEWS_DOCUMENT ||--o{ DOCUMENT_CHUNK : split
    DOCUMENT_CHUNK ||--o{ EVIDENCE_CLAIM : supports
    STRATEGY_PROFILE ||--o{ STRATEGY_VERSION : versions
    STRATEGY_VERSION ||--o{ RESEARCH_RUN : drives
    RESEARCH_RUN ||--o{ RESEARCH_ITEM : outputs
    RESEARCH_ITEM }o--|| SECURITY : targets
    RESEARCH_ITEM ||--o{ RESEARCH_EVIDENCE : cites
    POSITION ||--o{ POSITION_THESIS : tracks
```

Each research run freezes universe, data snapshot, strategy, prompt, model, tool, provider, retrieval results, evidence, structured output, timestamps, and hashes.

---

# Layer 3 — News and WebSearch Acquisition

## 5. Source Hierarchy and Compliance

```mermaid
flowchart TD
    L1[Level 1: Exchange/Regulator/Statutory Filing]
    L2[Level 2: IR/Earnings Call/Formal Company News]
    L3[Level 3: Industry Data/Tenders/Prices/Inventory]
    L4[Level 4: Reputable Media/Professional Research]
    L5[Level 5: Social and Unverified Sources]
    L1 --> Q[Evidence Quality]
    L2 --> Q
    L3 --> Q
    L4 --> Q
    L5 --> Q
```

Components:

- Source Registry;
- API/RSS/Web/File Connectors;
- WebSearch Provider;
- Scheduler;
- Downloader;
- Raw Snapshot;
- Deduplicator;
- Document Classifier;
- Quality Scorer;
- Document Event Publisher.

MVP news discovery uses configurable WebSearch Providers, not unrestricted crawling:

- Users provide their own API keys;
- The system stores query, result URL, title, snippet, retrieval time, and content hash;
- A WebSearch result must resolve to an accessible original page or compliant snapshot before entering RAG;
- The system must not bypass robots, login walls, paywalls, or anti-bot controls;
- Copyrighted full text is not redistributed as open-source sample data;
- L4/L5 evidence can trigger investigation but cannot alone change research or position states.

```mermaid
flowchart LR
    A[Discover URL/API/Search Result] --> B[Download or Snapshot]
    B --> C[Save Raw Snapshot]
    C --> D[Format Detection]
    D --> E[Parse Text/Tables]
    E --> F[Deduplicate]
    F --> G[Map Securities]
    G --> H[Time and Source Level]
    H --> I[Index Queue]
```

---

# Layer 4 — Text Vector Database

## 6. Vector Pipeline

```mermaid
flowchart TD
    A[Raw Document] --> B[Parser]
    B --> C[Structure Recognition]
    C --> D[Chunker]
    D --> E[Embedding]
    E --> F[(Vector Store)]
    D --> G[(Keyword Index)]
    F --> H[Hybrid Retrieval]
    G --> H
    H --> I[Reranker]
    I --> J[Evidence Chunks]
```

Chunk metadata includes:

```json
{
  "chunk_id": "chunk_xxx",
  "document_id": "doc_xxx",
  "symbol": "000001.SZ",
  "source_url": "https://...",
  "source_level": 1,
  "published_at": "2026-06-17T18:30:00+08:00",
  "available_at": "2026-06-18T09:30:00+08:00",
  "page": 86,
  "section": "Cash Flow",
  "paragraph_index": 12,
  "table_id": "cash_flow_table",
  "row_id": "net_operating_cash_flow",
  "quote_span": [120, 188],
  "content_hash": "sha256:..."
}
```

Retrieval score:

\[
Score =
w_v Vector +
w_k BM25 +
w_t TimeDecay +
w_s SourceQuality +
w_e EntityMatch
\]

Hard filters:

- Security;
- `available_at <= decision_at`;
- Document type;
- Evidence level;
- Duplicate claims;
- Original page, paragraph, table, or URL location.

---

# Layer 5 — AI

## 7. AI Architecture

```mermaid
flowchart TB
    Q[Request or Job] --> R[Routing Layer]
    R --> PR[Provider Layer]
    PR --> O[Multi-Agent/Workflow Orchestration]
    O --> T[Tool System]
    O --> G[RAG Evidence]
    O --> M[MCP Layer]
    PR --> W[WebSearch Provider]
    PR --> DP[Data Providers: AKShare/Tushare]
    PR --> EP[Embedding/Rerank Providers]
    T --> X[Internal Tools and APIs]
    M --> Y[MCP Servers]
    G --> V[Vector Store]
    O --> L[Model Gateway]
    L --> P[LLM Providers]
    O --> S[Schema and Guardrails]
    S --> D[Research Signal Decision Engine]
```

### 7.1 Provider Layer

| Provider Type | MVP Implementation | Purpose |
|---|---|---|
| MarketDataProvider | AKShare / Tushare | A-share market, fundamentals, index, actions |
| WebSearchProvider | User-configured API key | News and public web discovery |
| LLMProvider | OpenAI-compatible | Research, extraction, summary, reflection |
| EmbeddingProvider | OpenAI-compatible / local | Text embedding |
| RerankProvider | Optional | Hybrid retrieval reranking |
| VectorStoreProvider | pgvector / Qdrant | Pluggable vector storage |
| NotificationProvider | Local/email/webhook | Alert delivery |

Providers must support health checks, rate limits, retries, cost tracking, Secret references, versioning, and audit logs.

### 7.2 Routing Layer

The router selects model, workflow, tool set, retrieval scope, budget, timeout, and output schema.

```mermaid
flowchart TD
    A[Task] --> B{Type}
    B -->|Extraction| C[Low-Cost Structured Model]
    B -->|Complex Analysis| D[High-Capability Long-Context Model]
    B -->|Embedding| E[Embedding Model]
    B -->|Rerank| F[Reranker]
    B -->|Calculation| G[Python/Valuation Tool]
    B -->|Intraday| H[Rules First + Lightweight Model]
```

### 7.3 RAG Evidence System

```mermaid
sequenceDiagram
    participant A as Agent
    participant R as Retriever
    participant V as Vector Store
    participant C as Citation Validator
    participant L as LLM
    A->>R: Research query
    R->>V: Hybrid retrieval
    V-->>R: Chunks
    R-->>A: Reranked evidence
    A->>L: Evidence + structured task
    L-->>A: Claims/Risks/Unknowns
    A->>C: Validate citations and time
    C-->>A: Pass or fail
```

Evidence claim shape:

```json
{
  "claim_id": "claim_001",
  "claim_type": "cash_flow_improvement",
  "statement": "Operating cash flow quality improved",
  "fact_or_inference": "FACT",
  "evidence_ids": ["ev_101", "ev_102"],
  "confidence": 0.87,
  "conflicts": [],
  "effective_at": "2026-06-18",
  "locator": {
    "source_url": "https://...",
    "page": 86,
    "section": "Cash Flow",
    "paragraph_index": 12,
    "table_id": "cash_flow_table",
    "row_id": "net_operating_cash_flow",
    "content_hash": "sha256:..."
  }
}
```

### 7.4 Tool System

- MarketDataTool;
- FinancialTool;
- FilingTool;
- WebSearchTool;
- RetrievalTool;
- ValuationTool;
- FactorTool;
- PortfolioTool;
- BacktestTool;
- CalendarTool;
- AlertTool;
- Controlled PythonTool.

LLMs may not fabricate tool output. Numerical results must come from deterministic tools. External writes require user confirmation.

### 7.5 Multi-Agent Orchestration

“Multi-agent” means role-based tool orchestration, not debate that creates false certainty. Each agent has explicit input, permissions, output schema, and failure policy.

```mermaid
flowchart LR
    A[Universe Filter] --> B[Quant Research]
    B --> C[WebSearch Agent]
    C --> D[Document Collector]
    D --> E[Text Summary]
    E --> F[Evidence Research]
    F --> G[Valuation Tool]
    G --> H[Risk/Value-Trap Review]
    H --> I[Reflect/Counterargument]
    I --> J[Portfolio Constraint]
    J --> K[Research Signal Composer]
    K --> L[Citation Validator]
```

### 7.6 MCP

Suggested servers:

```text
margin-market-mcp
margin-filings-mcp
margin-portfolio-mcp
margin-backtest-mcp
margin-evidence-mcp
margin-macro-mcp
```

```mermaid
flowchart TD
    A[Agent] --> B[MCP Gateway]
    B --> C{Permission}
    C -->|Read Only| D[Data and Evidence]
    C -->|Confirmation| E[Modify Strategy/Create Alert]
    C -->|Forbidden| F[Automatic Trading/Arbitrary Execution]
```

---

# Layer 6 — Research Signal Strategy Configuration

## 8. Strategy Lifecycle

```mermaid
flowchart TD
    A[Strategy Editor] --> B[Schema Validation]
    B --> C[Merge Guardrails]
    C --> D[Create Version]
    D --> E[Backtest]
    E --> F[Paper Run]
    F --> G{Enable?}
    G -->|Yes| H[Active]
    G -->|No| I[Draft/Archived]
```

Strategy fields:

- Universe;
- Factors;
- Valuation;
- Quality;
- Catalysts;
- News and WebSearch sources;
- AI prompts;
- Evidence requirements;
- Horizon;
- Risk limits;
- Portfolio constraints;
- Decision thresholds;
- Output templates.

Prompt stack:

```text
System Guardrails
+ Platform Research Prompt
+ Strategy Template Prompt
+ User Custom Prompt
+ Task Context
+ Retrieved Evidence
```

---

# Layer 7 — Research Candidate Dashboard

## 9. Dashboard Services and API

Services:

- Research Run Query Service;
- Dashboard BFF;
- Evidence View Service;
- Valuation View Service;
- Strategy Status Service;
- Report Renderer;
- Export Service.

```mermaid
flowchart TD
    A[Research Candidate Dashboard] --> B[Candidates]
    A --> C[Position Reviews]
    A --> D[Critical Risks]
    A --> E[Abstentions]
    A --> F[Job Status]
    B --> G[Research Detail]
    G --> H[Evidence]
    G --> I[Valuation]
    G --> J[Catalysts]
    G --> K[Counterarguments]
```

API:

```text
GET  /api/v1/research-runs?date=&strategy_id=&portfolio_id=&universe_id=&status=
POST /api/v1/research-runs
GET  /api/v1/research-runs/{run_id}
GET  /api/v1/research-runs/{run_id}/items
GET  /api/v1/research-items/{item_id}
GET  /api/v1/research-items/{item_id}/evidence
GET  /api/v1/research-items/{item_id}/valuation
GET  /api/v1/research-items/{item_id}/audit
POST /api/v1/research-items/{item_id}/feedback
GET  /api/v1/provider-status
POST /api/v1/jobs/nightly-runs
GET  /api/v1/jobs/{job_run_id}
```

Key query dimensions: `date`, `strategy_id`, `strategy_version_id`, `portfolio_id`, `universe_id`, `run_id`, and `decision_at`.

---

# Layer 8 — Holdings Dashboard

## 10. Portfolio Architecture

```mermaid
flowchart TB
    T[Manual/CSV Trades] --> P[Portfolio Service]
    P --> C[Cost and Quantity]
    P --> R[Portfolio Risk]
    P --> H[Thesis Tracking]
    M[Market Data] --> C
    N[Filings and News] --> H
    C --> UI[Holdings Dashboard]
    R --> UI
    H --> UI
    R --> A[Alert Engine]
    H --> A
```

Portfolio risk:

- Single-name concentration;
- Industry and factor exposure;
- Correlation;
- Liquidity;
- Volatility;
- Drawdown;
- Event concentration.

Position APIs:

```text
GET  /api/v1/portfolios/{id}
GET  /api/v1/portfolios/{id}/positions
POST /api/v1/portfolios/{id}/trades
POST /api/v1/portfolios/{id}/imports
GET  /api/v1/portfolios/{id}/risk
GET  /api/v1/positions/{id}/thesis
PUT  /api/v1/positions/{id}/thesis
GET  /api/v1/positions/{id}/alerts
```

---

## 11. End-to-End Nightly Sequence

```mermaid
sequenceDiagram
    participant S as Scheduler
    participant D as Data Provider
    participant N as News/WebSearch
    participant V as Vector DB
    participant C as Strategy
    participant A as AI Orchestrator
    participant R as Research Signal Service
    participant P as Portfolio

    S->>D: Update structured data
    S->>N: Fetch filings and WebSearch results
    N->>V: Parse, embed, index
    S->>C: Load active strategy
    C-->>A: Prompts and constraints
    D-->>A: Factors and candidates
    A->>V: Retrieve evidence
    V-->>A: Evidence chunks
    A->>A: Tools, valuation, reflection
    A->>P: Read positions and limits
    P-->>A: Portfolio risk
    A->>R: Structured research signals
    R->>P: Update thesis state
```

---

## 12. Intraday Monitoring

```mermaid
flowchart TD
    A[Price Poller] --> B[Rule Engine]
    C[News Poller] --> B
    B --> D{Trigger?}
    D -->|No| E[Wait]
    D -->|Yes| F[Evidence Retrieval]
    F --> G[Lightweight AI Explanation]
    G --> H{Thesis Changed?}
    H -->|No| I[P2/P3 Alert]
    H -->|Yes| J[P0/P1 Alert]
```

Intraday does not run retraining, full-universe research, unrestricted agent chains, automatic execution, or unconstrained advice.

---

## 13. Plugin Architecture

Plugin types:

- DataProvider;
- NewsProvider;
- WebSearchProvider;
- VectorStore;
- EmbeddingProvider;
- LLMProvider;
- MCPServer;
- ToolPlugin;
- StrategyPlugin;
- ValuationPlugin;
- NotificationPlugin;
- BrokerImportPlugin.

Repository:

```text
margin/
├── apps/api
├── apps/web
├── packages/core
├── packages/data
├── packages/storage
├── packages/news
├── packages/vector
├── packages/ai
├── packages/strategy
├── packages/research
├── packages/portfolio
├── connectors
├── mcp_servers
├── plugins
├── workflows
├── configs
├── examples
├── docs
└── tests
```

---

## 14. Deployment

```mermaid
flowchart TB
    subgraph Host[Local or Cloud Host]
        WEB[Next.js]
        API[FastAPI]
        WORKER[Worker/Scheduler]
        PG[(PostgreSQL + pgvector)]
        FILES[(Raw/Parquet)]
        REDIS[(Optional Redis)]
    end
    API --> PG
    WORKER --> PG
    WORKER --> FILES
    WORKER --> LLM[Cloud or Local Model]
    WORKER --> DATA[AKShare/Tushare]
    WORKER --> SEARCH[WebSearch API]
    WEB --> API
```

Docker Compose:

```text
web
api
worker
postgres
optional-redis
optional-qdrant
prometheus
grafana
```

---

## 15. Security and Observability

Security:

- Secret management;
- Least privilege;
- Provider and MCP permission policies;
- Prompt-injection defenses;
- User prompts cannot override guardrails;
- File validation;
- No arbitrary code execution by default;
- Sandboxed research agents;
- Local portfolio storage;
- Immutable audit logs;
- Data-source licensing, WebSearch API key, news copyright, and user-upload responsibility boundaries shown in settings.

Metrics:

- Provider availability;
- Missing-data rate;
- News delay;
- Parse success;
- Vector-index delay;
- Citation-validation failure;
- Agent-node latency;
- Model cost;
- Research signal abstention rate;
- Alert latency;
- Strategy success rate.

Trace fields:

```text
trace_id
job_run_id
strategy_version_id
research_run_id
symbol
agent_node
model_version
provider_version
```

---

## 16. Testing and Failure Modes

Tests:

- Connector and schema;
- Provider limits and licensing metadata;
- Point-in-time;
- Valuation formulas;
- Retrieval filters;
- Prompt merge;
- Decision rules;
- Portfolio cost and risk;
- End-to-end data-to-dashboard;
- Look-ahead and survivorship bias;
- Adjustment factors and trading costs;
- Risk score and event-window calibration;
- Model drift.

```mermaid
flowchart TD
    A[Failure] --> B{Type}
    B -->|Data Source| C[Fallback or Stale-Data Degradation]
    B -->|Parser| D[Keep Raw and Suppress AI Claim]
    B -->|Vector Store| E[Keyword Retrieval]
    B -->|LLM| F[Rule-Only Report]
    B -->|Strategy| G[Rollback]
    B -->|Critical Conflict| H[Suppress High-Confidence Research Signal]
```

Principle: prefer `ABSTAINED` to a false high-confidence conclusion.

---

## 17. Implementation Order

```mermaid
gantt
    title Margin v0.1 Technical Implementation Path
    dateFormat YYYY-MM-DD
    section Phase 1 Providers and Storage
    Provider Registry              :a1, 2026-07-01, 10d
    AKShare/Tushare Access         :a2, after a1, 14d
    PostgreSQL/Parquet and Snapshots :a3, after a1, 14d
    section Phase 2 Holdings and Data Quality
    Holdings Core Service          :b1, after a2, 14d
    Point-in-Time and Quality Checks :b2, after a3, 14d
    section Phase 3 Filings and WebSearch
    Filing Acquisition and Raw Snapshots :c1, after b2, 14d
    WebSearch Provider and Compliance Dedup :c2, after c1, 14d
    section Phase 4 RAG and Multi-Agent
    Text Indexing and Citation Locator :d1, after c2, 21d
    RAG Evidence System            :d2, after d1, 21d
    Multi-Agent Tool Calls         :d3, after d2, 21d
    section Phase 5 Dashboards and Strategy
    Strategy Configuration         :e1, after d3, 21d
    Research Candidate Dashboard   :e2, after e1, 21d
    Holdings Dashboard Enhancements :e3, after e1, 21d
    section Phase 6 Validation and Ecosystem
    Backtest and Model Governance  :f1, after e2, 30d
    MCP and Plugin Ecosystem       :f2, after f1, 30d
```

---

## 18. Recommended MVP Stack

```text
Backend: FastAPI
Frontend: Next.js
Primary DB: PostgreSQL
Vector: pgvector first, Qdrant optional
Analytics: Parquet + DuckDB
Provider Registry: lightweight custom registry
Market Data Providers: AKShare + Tushare
WebSearch Provider: user-configured API key
Scheduler: APScheduler
Queue: local worker first; Celery/RQ later
Quant: rule/factor engine first; Qlib + LightGBM as later pluggable modules
Agent: LangGraph or explicit state machine
MCP: Python MCP SDK in later MVP phases
Deployment: Docker Compose
```

---

## 19. Summary

Margin v0.1 prioritizes:

> Point-in-time correctness > evidence lineage > strategy configurability > agent complexity.

The minimum complete loop is:

> Data Providers → News/WebSearch → Vector retrieval → Controlled multi-agent research → User strategy constraints → Research Candidate Dashboard → Holdings Dashboard → Review and attribution.
