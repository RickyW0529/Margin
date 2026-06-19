# Margin（安全边际）开源投资研究系统｜架构设计文档 v0.1

> 文档类型：系统架构设计文档
> 产品版本：v0.1
> 文档版本：v0.1
> 状态：active
> 架构模式：模块化单体 + 本地 Docker Compose + 持久化 Worker + Provider/Tool 插拔边界
> 当前实现：FastAPI、Next.js、PostgreSQL/pgvector、APScheduler、Prometheus、Grafana、OpenAI-compatible LLM/Embedding
> 重要边界：v0.1 不实现 MCP Server、MCP Gateway、自定义 HTTP 工具运行时或自动下单。

---

## 1. 架构目标

Margin v0.1 的架构目标是把个人投资研究链路做成可运行、可审计、可降级的本地系统，而不是只做一个前端演示。

核心目标：

- 本地一键启动：`docker compose up -d --build` 后启动数据库、迁移、seed、API、Worker、Web、Prometheus、Grafana；
- 数据安全：`.env` 本地注入密钥，Git 不提交真实 token；
- 研究可追溯：每个 run、item、snapshot、evidence、alert、audit 都能回到表记录；
- Provider 可替换：LLM、Embedding、Rerank、WebSearch、AKShare/Tushare 都通过适配器边界接入；
- 工具受控：AI 只能调用内部注册工具，工具有权限等级和审计记录；
- 降级保守：外部数据或模型异常时返回 `ABSTAINED`、`DATA_MISSING` 或 Provider degraded，不输出高置信结论；
- 代码可维护：按数据、公告、向量、证据、研究、策略、面板、监控、部署审计拆模块。

## 2. 整体架构图

```mermaid
flowchart TB
    subgraph Client[Client]
        Browser[Browser]
    end

    subgraph Web[Web Layer]
        Next[Next.js App Router<br/>portfolio/research/position pages]
    end

    subgraph API[API Layer]
        FastAPI[FastAPI app]
        Middleware[TraceId + Metrics Middleware]
        Routes[portfolio / dashboard / monitoring / strategy / research / health]
    end

    subgraph Domain[Domain Services]
        Portfolio[Portfolio Service]
        News[News + WebSearch Service]
        Vector[Vector + Retrieval Pipeline]
        Evidence[RAG Evidence Service]
        Research[Research Workflow + Agents]
        Strategy[Strategy Service]
        Dashboard[Dashboard Service]
        Monitoring[Holdings Monitoring]
        Audit[Audit Repository]
    end

    subgraph Runtime[Async Runtime]
        Worker[APScheduler Worker]
        Indexing[Indexing Runner]
        Monitor[Monitoring Sweep]
    end

    subgraph Storage[Storage]
        PG[(PostgreSQL + pgvector)]
        AuditVolume[(audit volume)]
        SnapshotVolume[(snapshot volume)]
    end

    subgraph Providers[External Providers]
        AKShare[AKShare]
        Tushare[Tushare optional]
        Tavily[Tavily WebSearch optional]
        LLM[OpenAI-compatible LLM]
        Embedding[OpenAI-compatible Embedding]
        Rerank[Rerank optional]
    end

    subgraph Observability[Observability]
        Prom[Prometheus]
        Grafana[Grafana]
    end

    Browser --> Next
    Next --> FastAPI
    FastAPI --> Middleware --> Routes
    Routes --> Portfolio
    Routes --> Dashboard
    Routes --> Monitoring
    Routes --> Strategy
    Routes --> Research
    Research --> Evidence
    Research --> Vector
    Research --> News
    Research --> Strategy
    Dashboard --> Research
    Dashboard --> Audit
    Monitoring --> Portfolio
    Worker --> Indexing
    Worker --> Monitor
    Indexing --> Vector
    Monitor --> Monitoring
    Portfolio --> PG
    News --> PG
    Vector --> PG
    Evidence --> PG
    Research --> PG
    Strategy --> PG
    Dashboard --> PG
    Monitoring --> PG
    Audit --> PG
    Audit --> AuditVolume
    News --> SnapshotVolume
    Vector --> Embedding
    Research --> LLM
    Research --> AKShare
    Research --> Tavily
    Vector --> Rerank
    Monitor --> AKShare
    Portfolio --> Tushare
    FastAPI --> Prom
    Prom --> Grafana
```

## 3. 分层架构

v0.1 采用“产品模块 + 横切能力”的分层方式。每层都有明确代码目录和数据边界。

```mermaid
flowchart TB
    UI[表现层<br/>web/app + web/components]
    API[API 层<br/>src/margin/api]
    APP[应用服务层<br/>portfolio/dashboard/monitoring/strategy/research service]
    DOMAIN[领域模型层<br/>models + validators + workflow]
    INFRA[基础设施层<br/>repository + providers + db_models]
    DATA[数据存储层<br/>PostgreSQL/pgvector + volumes]
    EXT[外部 Provider<br/>AKShare/Tushare/Tavily/LLM/Embedding/Rerank]
    OBS[横切能力<br/>settings/logging/metrics/audit/degradation]

    UI --> API
    API --> APP
    APP --> DOMAIN
    APP --> INFRA
    INFRA --> DATA
    INFRA --> EXT
    OBS --- API
    OBS --- APP
    OBS --- INFRA
```

| 层 | 主要职责 | 当前代码 |
| --- | --- | --- |
| 表现层 | 页面、组件、用户导航、可视化 | `web/app`, `web/components`, `web/lib/api.ts` |
| API 层 | REST 路由、依赖注入、中间件、健康检查 | `src/margin/api` |
| 应用服务层 | 组合、研究、策略、Dashboard、监控业务编排 | `service.py` in each module |
| 领域模型层 | Pydantic 模型、状态枚举、规则、workflow | `models.py`, `workflow.py`, validators |
| 基础设施层 | SQLAlchemy repository、Provider adapter、工具注册 | `repository.py`, `db_models.py`, providers |
| 数据存储层 | 业务表、向量表、审计表、Docker volumes | PostgreSQL + pgvector |
| 外部 Provider | 行情、WebSearch、LLM、Embedding、Rerank | adapter + settings |
| 横切能力 | Secret、日志、trace、metrics、degradation、audit | `src/margin/core`, `src/margin/settings.py` |

## 4. 代码模块地图

| 模块 | 目录 | 关键职责 |
| --- | --- | --- |
| core | `src/margin/core` | ProviderRegistry、Secret、Audit、Metrics、Degradation、Logging |
| settings | `src/margin/settings.py` | `MARGIN_*` 配置集中入口 |
| api | `src/margin/api` | FastAPI app、路由、中间件、依赖工厂 |
| data | `src/margin/data` | AKShare/Tushare、字段标准化、质量检查 |
| portfolio | `src/margin/portfolio` | portfolio/trade/thesis、成本与持仓、风险报告 |
| news | `src/margin/news` | source cursor、raw snapshot、document event、outbox、WebSearch、dedup |
| vector | `src/margin/vector` | chunk、embedding、pgvector repository、persistent pipeline、retrieval、indexing runner |
| evidence | `src/margin/evidence` | evidence record、claim、locator、citation validation |
| research | `src/margin/research` | ToolRegistry、LLM provider、agents、workflow、snapshot、production tools |
| strategy | `src/margin/strategy` | strategy profile、version、template、prompt、lifecycle |
| dashboard | `src/margin/dashboard` | research run/item/card、evidence/valuation/audit/report/export、feedback、provider status |
| holdings_monitoring | `src/margin/holdings_monitoring` | alert、review、operation history、behavior metrics、AKShare price polling |
| worker | `src/margin/worker.py` | APScheduler，周期执行 monitoring 和 indexing |

## 5. Docker Compose 部署拓扑

```mermaid
flowchart TB
    Postgres[(postgres<br/>pgvector/pgvector:pg16)]
    Migrate[migrate<br/>python scripts/migrate.py]
    Seed[seed<br/>python scripts/seed_demo.py]
    API[api<br/>uvicorn margin.api.main:app]
    Worker[worker<br/>python -m margin.worker]
    Web[web<br/>next start]
    Prometheus[prometheus<br/>prom/prometheus:v3.12.0]
    Grafana[grafana<br/>grafana/grafana:13.0.2]

    Postgres -->|healthy| Migrate
    Migrate -->|completed| Seed
    Seed -->|completed| API
    Seed -->|completed| Worker
    API -->|healthy| Web
    API -->|metrics scrape| Prometheus
    Prometheus --> Grafana
```

| 服务 | 端口 | 状态要求 | 持久化 |
| --- | --- | --- | --- |
| postgres | 5432 | `pg_isready` healthy | `margin-postgres` |
| migrate | 无 | Alembic upgrade 成功后退出 0 | 无 |
| seed | 无 | demo 数据写入后退出 0 | PostgreSQL |
| api | 8000 | `/health/ready` healthy | audit/snapshot volume |
| worker | 无 | 常驻执行监控和索引任务 | audit/snapshot volume |
| web | 3000 | Next.js start | 无 |
| prometheus | 9090 | scrape API `/metrics` | 配置文件 |
| grafana | 3002 | dashboard provisioning | `margin-grafana` |

## 6. API 设计

### 6.1 路由总览

| API 域 | Prefix | 代表端点 |
| --- | --- | --- |
| 健康/指标 | `/health`, `/metrics` | `/health`, `/health/ready`, `/health/degraded`, `/metrics` |
| 组合持仓 | `/api/v1` | `/portfolios/{id}`, `/positions`, `/trades`, `/imports`, `/risk`, `/thesis` |
| Dashboard | `/api/v1` | `/research-runs`, `/research-items/{id}`, `/provider-status`, `/jobs/nightly-runs` |
| 持仓监控 | `/api/v1` | `/positions/{id}/monitoring/evaluate`, `/alerts`, `/reviews`, `/history` |
| 策略 | `/strategies` | `/templates`, `/custom`, `/{strategy_id}/versions/{version_id}/activate` |
| 研究工具 | `/research` | `/run`, `/tools` |

### 6.2 API 设计原则

- v0.1 REST API 优先，不引入 GraphQL；
- Dashboard 端点直接为前端 BFF 服务，减少前端拼装复杂度；
- 研究 run 在 v0.1 以同步 MVP 方式触发，但保留 job run 表达；
- 失败用 404/400/422/503 表达，不把内部异常暴露给前端；
- `TraceIdMiddleware` 为请求写入 trace header，`MetricsMiddleware` 记录 Prometheus 指标。

## 7. Provider 与工具系统

### 7.1 ProviderRegistry

ProviderRegistry 负责：

- 注册 Provider 描述符；
- Secret 注入；
- 健康检查；
- fallback 调用；
- 记录调用审计；
- Prometheus provider metrics。

当前 Provider 类型：

| Provider | 代码 | 配置 |
| --- | --- | --- |
| AKShare | `data/providers/akshare_provider.py` | 无 key |
| Tushare | `data/providers/tushare_provider.py` | `MARGIN_SECRET_TUSHARE_TOKEN` |
| Tavily | `news/providers/tavily.py` | `MARGIN_WEBSEARCH_API_KEY` |
| LLM | `research/llm.py` | `MARGIN_LLM_BASE_URL`, `MARGIN_LLM_API_KEY`, `MARGIN_LLM_MODEL` |
| Embedding | `vector/providers/openai_embedding.py` | `MARGIN_EMBEDDING_*` |
| Rerank | `vector/providers/rerank.py` | `MARGIN_RERANK_*` |

### 7.2 ToolRegistry

ToolRegistry 是 v0.1 的 AI 工具边界。它替代 MCP Server/Gateway，避免把单产品场景过度设计成多产品工具平台。

```mermaid
flowchart LR
    Agent[Agent Node] --> Registry[ToolRegistry]
    Registry --> Permission{Tool Permission}
    Permission -->|allow| Tool[Typed Tool]
    Permission -->|deny| Reject[Reject + Audit]
    Tool --> Result[ToolResult]
    Tool --> Audit[ToolCallRecord]
```

工具类型：

- MarketDataTool；
- FactorTool；
- FinancialTool；
- PortfolioTool；
- RetrievalTool；
- WebSearchTool；
- PythonTool（受限表达式）；
- CitationValidator 相关工具。

## 8. 研究工作流架构

```mermaid
sequenceDiagram
    participant UI as Web / API
    participant Dash as DashboardResearchService
    participant Research as ResearchService
    participant WF as ResearchWorkflow
    participant Tools as ToolRegistry
    participant LLM as LLM Provider
    participant DB as PostgreSQL
    participant Audit as AuditRepository

    UI->>Dash: POST /api/v1/research-runs
    Dash->>Research: run_batch(strategy, version, symbols)
    Research->>WF: execute(decision_at, universe)
    WF->>Tools: market/portfolio/retrieval/websearch
    Tools-->>WF: ToolResult + audit records
    WF->>LLM: summary/reflection/counter arguments
    LLM-->>WF: structured output
    WF->>WF: citation validation + abstain rules
    WF-->>Research: ResearchSnapshot
    Research->>DB: persist research_snapshots
    Research->>Audit: append terminal snapshot audit
    Dash->>DB: persist dashboard_runs/items
    Dash-->>UI: ResearchRun + CandidateCard
```

### 8.1 状态设计

| 状态 | 触发条件 |
| --- | --- |
| `published` | 证据、数据、引用和策略约束通过 |
| `abstained` | 数据缺失、证据不足、引用失败、冲突或 Provider 降级 |
| `invalidated` | 后续监控或用户复盘标记研究逻辑失效 |
| `data_missing` | 行情或关键输入不可用 |

## 9. 文本索引与 RAG 数据流

```mermaid
flowchart TD
    Source[交易所公告/WebSearch/用户授权文档] --> Snapshot[raw_snapshots]
    Snapshot --> Event[document_events]
    Event --> Outbox[document_outbox]
    Outbox --> Worker[worker indexing_job]
    Worker --> Parser[Parser]
    Parser --> Chunker[Chunker]
    Chunker --> Chunks[(chunks)]
    Chunks --> Embedding[Embedding Provider]
    Embedding --> ChunkEmbeddings[(chunk_embeddings)]
    Chunks --> Keyword[Keyword index / lexical fields]
    ChunkEmbeddings --> Retrieval[Hybrid Retrieval]
    Keyword --> Retrieval
    Retrieval --> Evidence[Evidence/Claim/Citation]
    Evidence --> Research[Research Workflow]
```

v0.1 支持：

- HTML/PDF/CSV/JSON/Text parser；
- chunk metadata；
- OpenAI-compatible Embedding；
- pgvector 存储；
- 检索审计；
- 可选 Rerank；
- 引用 locator。

## 10. 持仓监控架构

```mermaid
flowchart LR
    Worker[worker monitoring_job] --> Portfolio[PortfolioService]
    Portfolio --> Positions[Current Positions]
    Positions --> Price[AKShareLatestPriceProvider]
    Price --> Rules[Monitoring Rules]
    Rules --> Snapshot[PositionMonitoringSnapshot]
    Snapshot --> Alerts[(alert_events)]
    Alerts --> UI[Position Detail Page]
    UI --> Review[(position_reviews)]
    Alerts --> History[Operation History]
    Review --> History
```

降级要求：

- AKShare 失败时不抛出未处理异常；
- 写入 `DATA_MISSING` 语义告警；
- 保留 `latest_price_provider_degraded` 日志；
- 不阻塞 indexing job；
- 不误触发高置信交易建议。

## 11. 数据设计总图

```mermaid
flowchart TB
    subgraph Input[输入数据]
        Trades[用户交易/CSV]
        Filings[公告/新闻/WebSearch]
        Providers[行情/财务/Embedding/LLM]
        StrategyInput[策略模板/Prompt/阈值]
    end

    subgraph Operational[业务操作层]
        PortfolioTables[portfolios/trades/position_theses]
        NewsTables[raw_snapshots/document_events/document_outbox/search_*]
        VectorTables[chunks/chunk_embeddings/index_audit/retrieval_audit]
        StrategyTables[strategy_profiles/strategy_versions]
    end

    subgraph ResearchData[研究产物层]
        ResearchSnapshots[research_snapshots]
        DashboardData[dashboard_runs/dashboard_items/dashboard_feedback]
        EvidenceData[evidence_records/evidence_claims/research_evidence]
    end

    subgraph MonitoringData[监控复盘层]
        Alerts[alert_events]
        Reviews[position_reviews]
        Audit[audit_records]
    end

    Trades --> PortfolioTables
    Filings --> NewsTables
    Providers --> VectorTables
    StrategyInput --> StrategyTables
    NewsTables --> VectorTables
    VectorTables --> EvidenceData
    PortfolioTables --> ResearchSnapshots
    StrategyTables --> ResearchSnapshots
    EvidenceData --> ResearchSnapshots
    ResearchSnapshots --> DashboardData
    DashboardData --> Alerts
    PortfolioTables --> Alerts
    Alerts --> Reviews
    ResearchSnapshots --> Audit
    DashboardData --> Audit
    Alerts --> Audit
```

## 12. PostgreSQL / pgvector ER 图

当前 v0.1 迁移生成 29 张 public tables。持仓是由 `trades` 聚合计算出的当前视图，不单独落 `positions` 表。

```mermaid
erDiagram
    portfolios {
        string portfolio_id PK
        string user_id
        string name
        numeric cash
        datetime created_at
    }

    trades {
        string trade_id PK
        string portfolio_id FK
        string symbol
        string side
        numeric quantity
        numeric price
        datetime traded_at
    }

    position_theses {
        string thesis_id PK
        string portfolio_id FK
        string symbol
        string thesis
        string status
        datetime updated_at
    }

    source_cursors {
        string source_id PK
        datetime last_seen_at
    }

    raw_snapshots {
        string snapshot_id PK
        string source_url
        string content_hash
        datetime fetched_at
    }

    document_events {
        string event_id PK
        string snapshot_id FK
        string symbol
        string title
        datetime published_at
        string status
    }

    document_outbox {
        string outbox_id PK
        string event_id FK
        string status
        int attempts
    }

    search_queries {
        string query_id PK
        string query
        datetime searched_at
    }

    search_results {
        string result_id PK
        string query_id FK
        string url
        string content_hash
    }

    dedup_records {
        string dedup_id PK
        string event_id FK
        string canonical_event_id FK
    }

    repost_edges {
        string edge_id PK
        string source_event_id FK
        string target_event_id FK
    }

    chunks {
        string chunk_id PK
        string document_id
        string source_type
        text content
    }

    chunk_embeddings {
        string embedding_id PK
        string chunk_id FK
        int dimension
        vector embedding
    }

    index_audit_records {
        string record_id PK
        string document_id
        string status
    }

    retrieval_audit_records {
        string record_id PK
        string query
        string trace_id
    }

    evidence_records {
        string evidence_id PK
        string source_level
        string source_url
        string locator_json
    }

    evidence_claims {
        string claim_id PK
        string statement
        string fact_or_inference
        float confidence
    }

    evidence_validation_audits {
        string audit_id PK
        string claim_id FK
        string status
        string reason
    }

    research_evidence {
        string link_id PK
        string claim_id FK
        string evidence_id FK
    }

    research_snapshots {
        string snapshot_id PK
        string run_id
        string symbol
        string status
        string trace_id
    }

    strategy_profiles {
        string strategy_id PK
        string owner_id
        string name
        string active_version_id
    }

    strategy_versions {
        string version_id PK
        string strategy_id FK
        string lifecycle_status
        string config_json
    }

    dashboard_runs {
        string run_id PK
        string strategy_id
        string version_id
        string portfolio_id
        string status
    }

    dashboard_items {
        string item_id PK
        string run_id FK
        string symbol
        string research_status
        float confidence
    }

    dashboard_feedback {
        string feedback_id PK
        string item_id FK
        string feedback_type
        string comment
    }

    alert_events {
        string alert_id PK
        string portfolio_id FK
        string position_id
        string priority
        string alert_type
    }

    position_reviews {
        string review_id PK
        string portfolio_id FK
        string position_id
        string alert_id FK
        string decision
    }

    audit_records {
        string record_id PK
        string record_type
        string object_id
        string trace_id
        datetime recorded_at
    }

    portfolios ||--o{ trades : records
    portfolios ||--o{ position_theses : tracks
    portfolios ||--o{ alert_events : monitors
    portfolios ||--o{ position_reviews : reviews
    raw_snapshots ||--o{ document_events : snapshots
    document_events ||--o{ document_outbox : queues
    search_queries ||--o{ search_results : returns
    document_events ||--o{ dedup_records : deduplicates
    document_events ||--o{ repost_edges : source
    chunks ||--o{ chunk_embeddings : embeds
    evidence_claims ||--o{ evidence_validation_audits : validates
    evidence_claims ||--o{ research_evidence : links
    evidence_records ||--o{ research_evidence : supports
    strategy_profiles ||--o{ strategy_versions : versions
    dashboard_runs ||--o{ dashboard_items : outputs
    dashboard_items ||--o{ dashboard_feedback : receives
    alert_events ||--o{ position_reviews : handled_by
```

## 13. 数据不可变与审计策略

v0.1 使用“业务可追加 + 研究快照不可变”的设计：

- `trades` 记录成交事实；
- `research_snapshots` 保存一次研究运行的终态；
- `dashboard_items` 保存面板可见候选；
- `audit_records` 保存通用审计；
- `alert_events` 保存告警；
- `position_reviews` 保存人工复盘。

不可变要求：

| 数据 | 策略 |
| --- | --- |
| 研究快照 | 创建后不覆盖，使用新 run 产生新记录 |
| 审计记录 | append-only，重复 `record_id` 拒绝 |
| Provider 调用 | 记录 trace、provider、method、status、cost/latency 可扩展字段 |
| 证据定位 | 保留 source_url、hash、locator、page/section/span |
| 告警复盘 | alert 与 review 分开，review 不修改 alert 原文 |

## 14. 配置与 Secret

`MarginSettings` 是唯一配置入口，读取 `.env` 和环境变量，前缀为 `MARGIN_`。

| 配置 | 用途 |
| --- | --- |
| `MARGIN_DATABASE_URL` | PostgreSQL 连接 |
| `MARGIN_LLM_BASE_URL` / `MARGIN_LLM_API_KEY` / `MARGIN_LLM_MODEL` | OpenAI-compatible LLM |
| `MARGIN_EMBEDDING_BASE_URL` / `MARGIN_EMBEDDING_API_KEY` / `MARGIN_EMBEDDING_MODEL` / `MARGIN_EMBEDDING_DIMENSION` | Embedding |
| `MARGIN_WEBSEARCH_API_KEY` | Tavily WebSearch |
| `MARGIN_RERANK_*` | 可选 Rerank |
| `MARGIN_SECRET_TUSHARE_TOKEN` | 可选 Tushare |
| `MARGIN_LOG_FORMAT` | `json` 或 `console` |
| `MARGIN_METRICS_ENABLED` | 是否暴露指标 |
| `MARGIN_MONITORING_INTERVAL_SECONDS` | Worker 监控周期 |

安全要求：

- `.env` 必须被 Git 忽略；
- `.env.example` 只保留空 token；
- 日志不得打印 token；
- Docker image 不 bake 真实密钥；
- Provider smoke 只输出状态和维度，不输出 key。

## 15. 可观测性

v0.1 可观测能力：

- `/health`：进程存活；
- `/health/ready`：数据库可用；
- `/health/degraded`：Provider/数据库降级状态；
- `/metrics`：Prometheus 格式；
- TraceIdMiddleware：请求 trace header；
- MetricsMiddleware：HTTP request counter / duration；
- Provider metrics：provider call success/degraded；
- Grafana dashboard provisioning；
- Worker 日志记录 monitoring/indexing job。

## 16. 降级策略

| 场景 | 行为 |
| --- | --- |
| 数据库不可达 | `/health/ready` 返回 503 |
| LLM 缺失 | 研究服务使用保守 fallback 或拒绝高置信输出 |
| Embedding 缺失 | 索引 worker 使用默认本地 embedding fallback 或跳过真实索引 |
| WebSearch key 缺失 | WebSearch 工具不注册或返回降级 |
| AKShare 不可达 | 持仓监控记录 `DATA_MISSING`，worker 不崩溃 |
| 引用校验失败 | research item `abstained` |
| Evidence 冲突 | 降低置信度或拒绝发布 |
| Rerank 缺失 | 使用基础混合召回排序 |

## 17. 测试与验证

当前验证层级：

| 层级 | 命令/证据 |
| --- | --- |
| Python lint | `ruff check src tests` |
| 后端测试 | `pytest -q` |
| 前端 lint | `npm run lint` in `web/` |
| 前端测试 | `npm test` in `web/` |
| 前端 build | `npm run build` in `web/` |
| Compose 配置 | `docker compose config --quiet` |
| 运行态 | `/health`, `/health/ready`, `/metrics`, browser E2E |
| 数据库 | Alembic `20260619_0009_audit`，29 张 public tables |
| Provider | DeepSeek chat HTTP 200；智谱 embedding 2048 dims |

测试数据库隔离要求：

- pytest 强制使用 `margin_test`；
- 不允许误删开发库；
- 测试会创建/升级测试库并清理隔离数据；
- Provider key 在测试中默认清空，避免真实调用混入单元测试。

## 18. 前端架构

```mermaid
flowchart TB
    App[Next.js App Router]
    Home[/ /]
    Portfolio[/portfolios/:portfolioId]
    Position[/positions/:positionId]
    Research[/research]
    Item[/research/items/:itemId]
    Run[/research/runs/:runId]
    ApiClient[web/lib/api.ts]
    Components[portfolio/candidate/evidence/report components]

    App --> Home
    App --> Portfolio
    App --> Position
    App --> Research
    App --> Item
    App --> Run
    Portfolio --> Components
    Position --> Components
    Research --> Components
    Item --> Components
    Components --> ApiClient
    ApiClient --> FastAPI[FastAPI API]
```

前端当前重点是可用性和可追溯：

- 组合持仓表中的 symbol 可点击进入持仓详情；
- 候选卡 symbol 可点击进入研究项详情；
- 研究项详情展示证据、估值、审计、报告；
- CSS 采用全局样式，后续可逐步提取设计 token 和组件库。

## 19. v0.1 与后续版本边界

v0.1 是单用户本地研究产品。v0.2 可扩展：

- 多 AI Provider UI；
- 模型路由和自动模型选择；
- 策略配置前端；
- 更完整的文档导入；
- 更强的 WebSearch/source 管理；
- 成本与质量观测；
- 更细粒度的 Provider 权限。

任何新增范围应进入 `docs/design/v0.2`、`docs/spec/v0.2`、`docs/plan/v0.2`，不修改 v0.1 的审计边界。

## 20. 总结

Margin v0.1 的架构不是“AI 调几个工具生成股票观点”，而是一套本地优先的研究操作系统：

- 数据进入系统后有快照和时点；
- 文档进入系统后有 outbox、chunk、embedding 和检索审计；
- AI 输出必须经过工具审计和证据校验；
- 候选面板与持仓监控共享同一审计链；
- 外部 Provider 失败时系统保守降级；
- 所有核心能力都能通过 Docker Compose、测试和浏览器 E2E 验证。
