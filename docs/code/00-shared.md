# Margin 当前实现 共享与核心横切组件文档

## 目录

- [1. 模块概览与职责](#1-模块概览与职责)
- [2. 文件级摘要](#2-文件级摘要)
- [3. 全局配置](#3-全局配置)
  - [3.1 `MarginSettings`](#31-marginsettings)
  - [3.2 `get_settings()`](#32-get_settings)
- [4. 持久化后台 Worker](#4-持久化后台-worker)
  - [4.1 `build_scheduler()`](#41-build_scheduler)
  - [4.2 `build_monitoring_runner()`](#42-build_monitoring_runner)
  - [4.3 `build_document_indexing_runner()`](#43-build_document_indexing_runner)
  - [4.4 `build_data_ingestion_stack()`](#44-build_data_ingestion_stack)
  - [4.5 `main()`](#45-main)
- [5. 存储基础设施](#5-存储基础设施)
  - [5.1 `Base`](#51-base)
  - [5.2 `DatabaseSettings`](#52-databasesettings)
  - [5.3 `create_database_engine()`](#53-create_database_engine)
  - [5.4 `create_session_factory()`](#54-create_session_factory)
- [6. FastAPI 应用与依赖注入](#6-fastapi-应用与依赖注入)
  - [6.1 `create_app()`](#61-create_app)
  - [6.2 `app`](#62-app)
  - [6.3 `MissingConfiguredProvider`](#63-missingconfiguredprovider)
  - [6.4 依赖工厂函数](#64-依赖工厂函数)
- [7. 共享请求/响应模型](#7-共享请求响应模型)
  - [7.1 `TradeCreate`](#71-tradecreate)
  - [7.2 `CSVImportRequest`](#72-csvimportrequest)
  - [7.3 `CSVImportResponse`](#73-csvimportresponse)
  - [7.4 `ThesisUpdate`](#74-thesisupdate)
  - [7.5 `PortfolioDashboardResponse`](#75-portfoliodashboardresponse)
- [8. Provider 核心抽象](#8-provider-核心抽象)
  - [8.1 `ProviderType`](#81-providertype)
  - [8.2 `ProviderStatus`](#82-providerstatus)
  - [8.3 `HealthCheckResult`](#83-healthcheckresult)
  - [8.4 `CallResult`](#84-callresult)
  - [8.5 `ProviderDescriptor`](#85-providerdescriptor)
  - [8.6 `BaseProvider`](#86-baseprovider)
  - [8.7 `MarketDataProvider`](#87-marketdataprovider)
  - [8.8 `WebSearchProvider`](#88-websearchprovider)
- [9. Provider 注册中心](#9-provider-注册中心)
  - [9.1 `ProviderNotFoundError`](#91-providernotfounderror)
  - [9.2 `ProviderAlreadyRegisteredError`](#92-provideralreadyregisterederror)
  - [9.3 `ProviderRegistry`](#93-providerregistry)
  - [9.4 内部辅助函数](#94-内部辅助函数)
- [10. 弹性组件](#10-弹性组件)
  - [10.1 `RateLimitError`](#101-ratelimiterror)
  - [10.2 `ProviderError`](#102-providererror)
  - [10.3 `RateLimiter`](#103-ratelimiter)
  - [10.4 `RetryConfig`](#104-retryconfig)
  - [10.5 `with_retry()`](#105-with_retry)
- [11. 密钥管理](#11-密钥管理)
  - [11.1 `SecretNotFoundError`](#111-secretnotfounderror)
  - [11.2 `SecretManager`](#112-secretmanager)
  - [11.3 `SecretRefInfo`](#113-secretrefinfo)
- [12. FastAPI 应用装配说明](#12-fastapi-应用装配说明)
  - [12.1 注册路由](#121-注册路由)
  - [12.2 注册中间件](#122-注册中间件)
  - [12.3 依赖覆盖机制](#123-依赖覆盖机制)
- [13. 跨模块使用说明](#13-跨模块使用说明)

---

## 1. 模块概览与职责

`shared/core` 层为 Margin 当前实现 提供所有业务模块共享的横切能力，包括：

- **集中式配置**：通过 `pydantic-settings` 统一读取环境变量，提供一次解析、进程内缓存的设置对象。
- **存储基础设施**：定义 SQLAlchemy 声明基类、PostgreSQL 引擎与会话工厂，以及对应的环境变量适配。
- **后台 Worker**：基于 APScheduler 的常驻进程，定时执行持仓监控与文档索引任务。
- **FastAPI 应用工厂**：装配路由、中间件、依赖注入与测试覆盖机制。
- **依赖注入**：提供数据库引擎、LLM / Embedding / WebSearch / Rerank Provider 以及各业务 ServiceBundle 的生产级工厂。
- **共享 Schema**：定义 API 请求/响应的 Pydantic 模型，使路由层与领域模型解耦。
- **Provider 抽象与注册中心**：统一 Provider 元数据、健康检查、调用结果、重试/限流/降级/审计。
- **弹性组件**：令牌桶限流器、指数退避重试、Provider 错误类型。
- **密钥管理**：基于引用名称的 Secret 解析器，支持环境变量与本地文件两种来源，避免明文落盘。
- **文档标准化流水线**：`margin.documents` 提供共享 Docling 接口，将 PDF/HTML/DOCX/XLSX/CSV/JSON/Text 统一转换为 Markdown；随后执行 Review / Repair / Verifier / Slimming，输出最终 Markdown、JSON 和 RAG chunks。RAG chunking 默认保留段落/表格行边界，并对单个超长 block 做硬切分，保证任一 chunk 不超过配置的 `max_chunk_chars`，避免 embedding provider 因输入过长拒绝请求。PDF 默认启用 RapidOCR，并固定使用 `onnxruntime` 后端；视觉校验仅在 verifier 支持多模态且存在 page images 时执行，否则自动跳过并记录状态。

---

## 2. 文件级摘要

| 文件路径 | 核心职责 |
| --- | --- |
| `src/margin/settings.py` | 定义 `MarginSettings` 与缓存工厂 `get_settings()`，集中管理环境配置。 |
| `src/margin/worker.py` | 装配 APScheduler 调度器、持仓监控 Runner 与文档索引 Runner，提供 `main()` 入口。 |
| `src/margin/storage/base.py` | 定义所有 PostgreSQL ORM 模型继承的 SQLAlchemy 声明基类 `Base`。 |
| `src/margin/storage/database.py` | 提供不可变 `DatabaseSettings`、引擎创建函数与绑定会话工厂。 |
| `src/margin/api/main.py` | FastAPI 应用工厂 `create_app()`，负责路由、中间件与依赖覆盖装配。 |
| `src/margin/api/dependencies.py` | FastAPI 依赖注入工厂，构造数据库引擎、外部 Provider 与各业务 ServiceBundle。 |
| `src/margin/api/schemas.py` | 定义路由层共享的 Pydantic 请求/响应模型。 |
| `src/margin/core/provider.py` | Provider 类型、状态、元数据、调用结果、基类与业务协议。 |
| `src/margin/core/registry.py` | Provider 注册中心，封装注册、发现、健康检查、限流、重试、降级、审计。 |
| `src/margin/core/resilience.py` | 限流器、重试配置与带重试/限流的通用调用包装函数。 |
| `src/margin/core/secret.py` | 引用式 Secret 管理器，支持环境变量与本地密钥文件。 |
| `src/margin/documents/markdown.py` | 共享 Docling Markdown 转换接口：格式路由、转换请求/结果模型、Docling 后端、PDF OCR 配置与轻量 fallback。 |
| `src/margin/documents/pipeline.py` | 共享文档标准化流水线：Review/Repair/Verifier/Slimming agent 协议与默认规则实现，输出 final Markdown/JSON/RAG chunks；chunking 对超长 block 二次切分并遵守 `max_chunk_chars`，同时支持多模态视觉校验自动降级。 |

---

## 3. 全局配置

### 3.1 `MarginSettings`

- **位置**：`src/margin/settings.py`
- **说明**：基于 `pydantic_settings.BaseSettings` 的单一配置源。所有字段默认以 `MARGIN_` 为前缀从环境变量读取，并支持 `.env` 文件。`
- **关键配置项**：

| 分组 | 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| 数据库 | `database_url` | `PostgresDsn` | `postgresql+psycopg://margin:margin@localhost:5432/margin` | PostgreSQL 连接 URL。 |
|  | `database_echo` | `bool` | `False` | 是否打印每条 SQL。 |
|  | `database_pool_pre_ping` | `bool` | `True` | 取出连接前是否探测可用性。 |
| LLM | `llm_api_key` | `SecretStr \| None` | `None` | LLM API 密钥。 |
|  | `llm_base_url` | `HttpUrl \| None` | `None` | LLM 服务基地址。 |
|  | `llm_model` | `str` | `deepseek-v4-pro` | 默认 LLM 模型。 |
| Embedding | `embedding_base_url` | `HttpUrl \| None` | `None` | Embedding 服务基地址。 |
|  | `embedding_api_key` | `SecretStr \| None` | `None` | Embedding API 密钥。 |
|  | `embedding_model` | `str` | `text-embedding-3-small` | 默认 Embedding 模型。 |
|  | `embedding_dimension` | `int` | `1536` | 向量维度。 |
| Rerank | `rerank_base_url` | `HttpUrl \| None` | `None` | Rerank 服务基地址。 |
|  | `rerank_api_key` | `SecretStr \| None` | `None` | Rerank API 密钥。 |
|  | `rerank_model` | `str` | `""` | 默认 Rerank 模型。 |
| WebSearch | `websearch_api_key` | `SecretStr \| None` | `None` | Tavily WebSearch API 密钥。 |
| Admin/Secret Store | `admin_api_token` | `SecretStr \| None` | `None` | v0.2 配置写接口 local-admin Bearer；缺失时 fail closed。 |
|  | `csrf_token` | `SecretStr \| None` | `None` | v0.2 配置写接口 CSRF token。 |
|  | `secret_master_key` | `SecretStr \| None` | `None` | AES-GCM-256 Secret Store master key，要求 32-byte 或等价 base64。 |
|  | `secret_key_version` | `str` | `local-v1` | 写入密文 associated data 的 key version。 |
|  | `allow_local_provider_urls` | `bool` | `False` | 是否允许本地开发 Provider URL。 |
|  | `resolve_provider_dns` | `bool` | `True` | SSRF guard 是否解析 DNS 并检查目标 IP。 |
| Data Provider | `tushare_token` | `SecretStr \| None` | `None` | Tushare token。会在 repr 中掩码，不应写入日志。 |
|  | `tushare_http_url` | `str \| None` | `None` | 可选 Tushare 兼容 API 地址。 |
|  | `data_snapshot_root` | `Path` | `.margin/snapshots/data` | v0.2 compressed raw snapshot 根目录。 |
|  | `data_sync_on_startup` | `bool` | `True` | Worker 是否启用 data provider sync job。 |
|  | `data_freshness_timezone` | `str` | `Asia/Shanghai` | data freshness 判断时区。 |
|  | `data_smoke_symbols` | `str` | `000001.SZ` | 真实 data provider smoke 使用的股票代码列表。 |
| 可观测性 | `log_level` | `str` | `INFO` | 日志级别。 |
|  | `log_format` | `Literal["json", "console"]` | `json` | 日志格式。 |
|  | `metrics_enabled` | `bool` | `True` | 是否启用指标。 |
|  | `trace_id_header` | `str` | `x-margin-trace-id` | Trace ID 请求/响应头。 |
|  | `monitoring_interval_seconds` | `int` | `300` | Worker 监控/索引间隔秒数。 |
| 审计 | `audit_log_path` | `Path` | `.margin/audit/provider_calls.jsonl` | Provider 调用审计日志路径。 |
| 部署 | `environment` | `Literal["development", "test", "production"]` | `development` | 运行环境。 |
|  | `service_name` | `str` | `margin-api` | 服务名。 |
|  | `service_version` | `str` | `0.1.0` | 服务版本。 |

- **校验器**：

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `empty_optional_url_is_none` | `(cls, value: object) -> object` | 将空字符串的可选 URL 字段转换为 `None`，兼容 Docker Compose 未设置变量时的空字符串注入。 |

### 3.2 `get_settings()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def get_settings() -> MarginSettings` |
| **位置** | `src/margin/settings.py` |
| **说明** | 使用 `functools.lru_cache` 缓存的配置工厂，每个进程只解析一次环境变量。 |
| **返回值** | 配置好的 `MarginSettings` 实例。 |

---

## 4. 持久化后台 Worker

### 4.1 `build_scheduler()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_scheduler(monitoring_job: Callable[[], None], *, interval_seconds: int, indexing_job: Callable[[], None] \| None = None, data_sync_job: Callable[[], None] \| None = None) -> BlockingScheduler` |
| **位置** | `src/margin/worker.py` |
| **说明** | 构造 APScheduler 调度器，配置持仓监控任务，可选地同时配置文档索引任务和 data provider sync job。 |

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `monitoring_job` | `Callable[[], None]` | 持仓监控任务函数。 |
| `interval_seconds` | `int` | 任务执行间隔秒数。 |
| `indexing_job` | `Callable[[], None] \| None` | 文档索引任务函数，可选。 |
| `data_sync_job` | `Callable[[], None] \| None` | data provider sync job，可选。 |

| 返回值 | 说明 |
| --- | --- |
| `BlockingScheduler` | 已配置任务但未启动的调度器。时区为 `Asia/Shanghai`。 |

### 4.2 `build_monitoring_runner()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_monitoring_runner() -> HoldingsMonitoringRunner` |
| **位置** | `src/margin/worker.py` |
| **说明** | 根据全局设置构建生产级持仓监控 Runner，包括数据库引擎、PortfolioService、 holdings monitoring service、AKShare 价格 Provider 与新闻事件 Provider。 |
| **返回值** | 配置好的 `HoldingsMonitoringRunner` 实例。 |

### 4.3 `build_document_indexing_runner()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_document_indexing_runner() -> DocumentIndexingRunner` |
| **位置** | `src/margin/worker.py` |
| **说明** | 根据全局设置构建文档索引 Runner。若 Embedding 配置完整则使用 `OpenAIEmbeddingProvider`，否则使用无网络能力的占位 `EmbeddingProvider`。 |
| **返回值** | 配置好的 `DocumentIndexingRunner` 实例。 |

### 4.4 `build_data_ingestion_stack()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_data_ingestion_stack(settings: MarginSettings \| None = None) -> DataWarehouseIngestionStack` |
| **位置** | `src/margin/worker.py` |
| **说明** | 根据全局设置或显式传入设置构建 v0.2 data warehouse ingestion stack，包括数据库 session factory 和 compressed raw snapshot 根目录。 |
| **返回值** | 配置好的 `DataWarehouseIngestionStack` 实例。 |

### 4.5 `main()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def main() -> None` |
| **位置** | `src/margin/worker.py` |
| **说明** | Worker 入口函数。配置日志、构造 Runner、包装异常捕获的任务函数、启动调度器。 |
| **返回值** | 无。启动后会阻塞运行。 |

---

## 5. 存储基础设施

### 5.1 `Base`

- **位置**：`src/margin/storage/base.py`
- **说明**：所有 PostgreSQL ORM 模型继承的 SQLAlchemy `DeclarativeBase` 子类。提供统一的 `metadata`，用于表注册与 Alembic 迁移管理。
- **关键属性**：

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `metadata` | `MetaData` | SQLAlchemy 表元数据实例。 |

### 5.2 `DatabaseSettings`

- **位置**：`src/margin/storage/database.py`
- **说明**：不可变的 PostgreSQL 连接配置数据类。

| 属性 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `url` | `str` | `DEFAULT_DATABASE_URL` | SQLAlchemy 数据库 URL。 |
| `echo` | `bool` | `False` | 是否打印 SQL。 |
| `pool_pre_ping` | `bool` | `True` | 连接池取出前 ping 探测。 |

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `from_env` | `@classmethod def from_env(cls) -> DatabaseSettings` | 从环境变量 `MARGIN_DATABASE_URL` 与 `MARGIN_DATABASE_ECHO` 加载配置。 |

### 5.3 `create_database_engine()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def create_database_engine(settings: DatabaseSettings \| None = None) -> Engine` |
| **位置** | `src/margin/storage/database.py` |
| **说明** | 创建共享的 SQLAlchemy 引擎。若未传入设置，则从环境变量加载。 |

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `settings` | `DatabaseSettings \| None` | 数据库连接设置，默认为 `None`。 |

| 返回值 | 说明 |
| --- | --- |
| `Engine` | 配置好的 SQLAlchemy 引擎。 |

### 5.4 `create_session_factory()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def create_session_factory(engine: Engine) -> SessionFactory` |
| **位置** | `src/margin/storage/database.py` |
| **说明** | 创建绑定到指定引擎的会话工厂。 |

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `engine` | `Engine` | SQLAlchemy 引擎。 |

| 返回值 | 说明 |
| --- | --- |
| `SessionFactory` | 配置 `expire_on_commit=False` 的 `sessionmaker` 工厂。 |

### 5.5 常量

| 常量 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DEFAULT_DATABASE_URL` | `str` | `postgresql+psycopg://margin:margin@localhost:5432/margin` | 默认数据库连接 URL。 |
| `SessionFactory` | `TypeAlias` | `sessionmaker[Session]` | 绑定到引擎的会话工厂类型别名。 |

---

## 6. FastAPI 应用与依赖注入

### 6.1 `create_app()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def create_app(portfolio_service: PortfolioService \| None = None, research_service: ResearchService \| None = None, strategy_service: StrategyService \| None = None, dashboard_services: DashboardServiceBundle \| None = None, monitoring_services: MonitoringServiceBundle \| None = None) -> FastAPI` |
| **位置** | `src/margin/api/main.py` |
| **说明** | 创建并配置 Margin API 应用。若传入业务服务实例，则通过 `dependency_overrides` 覆盖生产依赖，便于测试。 |

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `portfolio_service` | `PortfolioService \| None` | 可选的 Portfolio 服务注入。 |
| `research_service` | `ResearchService \| None` | 可选的 Research 服务注入。 |
| `strategy_service` | `StrategyService \| None` | 可选的 Strategy 服务注入。 |
| `dashboard_services` | `DashboardServiceBundle \| None` | 可选的 Dashboard 服务包注入。 |
| `monitoring_services` | `MonitoringServiceBundle \| None` | 可选的持仓监控服务包注入。 |

| 返回值 | 说明 |
| --- | --- |
| `FastAPI` | 配置好的 FastAPI 应用实例。 |

### 6.2 `app`

| 项目 | 内容 |
| --- | --- |
| **签名** | `app: FastAPI = create_app()` |
| **位置** | `src/margin/api/main.py` |
| **说明** | 使用生产配置创建的默认 API 应用实例，供 ASGI 服务器启动。 |

### 6.3 `MissingConfiguredProvider`

- **位置**：`src/margin/api/dependencies.py`
- **说明**：当外部 Provider 缺少配置时，用于仪表盘状态端点的降级占位对象。无需网络调用即可返回 `DEGRADED` 健康状态。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `descriptor` | `ProviderDescriptor` | 占位 Provider 的元数据描述符。 |
| `message` | `str` | 展示给前端的缺失配置说明。 |

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `healthcheck` | `def healthcheck(self) -> HealthCheckResult` | 返回 `DEGRADED` 状态，含缺失配置说明。 |

### 6.4 依赖工厂函数

所有工厂均位于 `src/margin/api/dependencies.py`，并使用 `@lru_cache` 进行进程级缓存。

#### 6.4.1 `build_database_engine()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_database_engine(settings: MarginSettings) -> Engine` |
| **说明** | 根据 `MarginSettings` 构建 SQLAlchemy 引擎。 |
| **返回值** | 配置好的 `Engine` 实例。 |

#### 6.4.2 `build_llm_provider()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_llm_provider(settings: MarginSettings) -> LLMProvider \| None` |
| **说明** | 若 `llm_api_key` 与 `llm_base_url` 均有效，则构建 OpenAI 兼容 LLM Provider。 |
| **返回值** | `LLMProvider` 实例，或配置缺失时返回 `None`。 |

#### 6.4.3 `build_embedding_provider()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_embedding_provider(settings: MarginSettings) -> OpenAIEmbeddingProvider \| None` |
| **说明** | 若 Embedding 配置有效，则构建 OpenAI 兼容 Embedding Provider。 |
| **返回值** | `OpenAIEmbeddingProvider` 实例，或配置缺失时返回 `None`。 |

#### 6.4.4 `build_websearch_provider()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_websearch_provider(settings: MarginSettings) -> TavilySearchAdapter \| None` |
| **说明** | 若 `websearch_api_key` 有效，则构建 Tavily WebSearch Provider。 |
| **返回值** | `TavilySearchAdapter` 实例，或配置缺失时返回 `None`。 |

#### 6.4.5 `build_rerank_provider()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_rerank_provider(settings: MarginSettings) -> HTTPRerankProvider \| None` |
| **说明** | 若 Rerank 配置有效，则构建 HTTP Rerank Provider。 |
| **返回值** | `HTTPRerankProvider` 实例，或配置缺失时返回 `None`。 |

#### 6.4.6 `build_provider_status_providers()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_provider_status_providers(settings: MarginSettings) -> list[Any]` |
| **说明** | 构建仪表盘状态端点展示的所有 Provider。缺失配置时返回对应的 `MissingConfiguredProvider` 降级占位。 |
| **返回值** | LLM、Embedding、WebSearch、Rerank Provider 或占位对象列表。 |

#### 6.4.7 `build_data_warehouse_stack()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def build_data_warehouse_stack(settings: MarginSettings) -> DataWarehouseIngestionStack` |
| **说明** | 根据集中配置构建 DB-backed data warehouse ingestion stack，供 API 或测试注入。 |
| **返回值** | `DataWarehouseIngestionStack` 实例。 |

#### 6.4.8 `get_data_warehouse_stack()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `@lru_cache def get_data_warehouse_stack() -> DataWarehouseIngestionStack` |
| **说明** | 返回生产 data warehouse ingestion stack 的进程级缓存实例。 |
| **返回值** | 缓存的 `DataWarehouseIngestionStack` 实例。 |

#### 6.4.9 `get_portfolio_service()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `@lru_cache def get_portfolio_service() -> PortfolioService` |
| **说明** | 返回基于 PostgreSQL 的 PortfolioService，供 Portfolio 路由注入。 |
| **返回值** | 缓存的 `PortfolioService` 实例。 |

#### 6.4.10 `get_research_service()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `@lru_cache def get_research_service() -> ResearchService` |
| **说明** | 返回基于 PostgreSQL 与配置化 LLM/Embedding 的 ResearchService。 |
| **返回值** | 缓存的 `ResearchService` 实例。 |

#### 6.4.11 `get_strategy_service()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `@lru_cache def get_strategy_service() -> StrategyService` |
| **说明** | 返回基于 PostgreSQL 的策略配置服务。 |
| **返回值** | 缓存的 `StrategyService` 实例。 |

#### 6.4.12 `get_dashboard_services()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `@lru_cache def get_dashboard_services() -> DashboardServiceBundle` |
| **说明** | 返回 Dashboard 模块所需的服务包，聚合 Dashboard Repository、Research Repository、ResearchService 与 Provider 状态列表。 |
| **返回值** | 缓存的 `DashboardServiceBundle` 实例。 |

#### 6.4.13 `get_monitoring_services()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `@lru_cache def get_monitoring_services() -> MonitoringServiceBundle` |
| **说明** | 返回持仓监控模块所需的服务包，包含 PortfolioService 与 MonitoringRepository。 |
| **返回值** | 缓存的 `MonitoringServiceBundle` 实例。 |

---

## 7. 共享请求/响应模型

以下模型均位于 `src/margin/api/schemas.py`，继承自 `pydantic.BaseModel`。

### 7.1 `TradeCreate`

- **说明**：手动录入单笔交易的请求体。

| 字段 | 类型 | 约束/默认值 | 说明 |
| --- | --- | --- | --- |
| `symbol` | `str` | `min_length=1` | 交易标的代码。 |
| `side` | `TradeSide` | - | 交易方向（买入/卖出）。 |
| `quantity` | `float` | `gt=0` | 成交数量。 |
| `price` | `float` | `gt=0` | 成交单价。 |
| `traded_at` | `datetime` | - | 成交时间。 |
| `fee` | `float` | `default=0, ge=0` | 手续费。 |
| `tax` | `float` | `default=0, ge=0` | 税费。 |
| `note` | `str \| None` | `None` | 备注。 |

### 7.2 `CSVImportRequest`

- **说明**：从 CSV 内容批量导入交易的请求体。

| 字段 | 类型 | 约束/默认值 | 说明 |
| --- | --- | --- | --- |
| `content` | `str` | `min_length=1` | 原始 CSV 文本。 |
| `field_mapping` | `dict[str, str] \| None` | `None` | CSV 列名到标准字段名的可选映射。 |

### 7.3 `CSVImportResponse`

- **说明**：CSV 导入完成后的响应体。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `trades` | `list[Trade]` | 从 CSV 行创建的交易列表。 |
| `record` | `ImportRecord` | 记录导入操作结果与血缘的导入记录。 |

### 7.4 `ThesisUpdate`

- **说明**：创建新投资论点版本的请求体。

| 字段 | 类型 | 约束/默认值 | 说明 |
| --- | --- | --- | --- |
| `portfolio_id` | `str` | `min_length=1` | 组合 ID。 |
| `thesis` | `str` | `min_length=1` | 投资论点正文。 |
| `entry_conditions` | `list[str]` | `[]` | 建仓条件。 |
| `hold_conditions` | `list[str]` | `[]` | 持有条件。 |
| `invalidation_conditions` | `list[str]` | `[]` | 失效条件。 |
| `target_horizon` | `list[int]` | `[60, 120]` | 目标回顾周期（天）。 |
| `next_review_at` | `datetime \| None` | `None` | 下次计划回顾时间。 |
| `status` | `ThesisStatus` | `THESIS_VALID` | 当前论点状态。 |

### 7.5 `PortfolioDashboardResponse`

- **说明**：返回组合身份与概览指标的响应体。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `portfolio` | `Portfolio` | 组合身份与元数据。 |
| `overview` | `PortfolioOverview` | 聚合后的仪表盘指标。 |

---

## 8. Provider 核心抽象

以下类型、模型与协议均位于 `src/margin/core/provider.py`。

### 8.1 `ProviderType`

- **说明**：Provider 的能力分类枚举，继承自 `StrEnum`。

| 成员 | 值 | 说明 |
| --- | --- | --- |
| `MARKET_DATA` | `market_data` | 市场数据。 |
| `WEB_SEARCH` | `web_search` | 网络搜索。 |
| `LLM` | `llm` | 大语言模型。 |
| `EMBEDDING` | `embedding` | 文本嵌入。 |
| `RERANK` | `rerank` | 重排序。 |
| `VECTOR_STORE` | `vector_store` | 向量存储。 |
| `NOTIFICATION` | `notification` | 通知。 |

### 8.2 `ProviderStatus`

- **说明**：Provider 健康状态枚举，继承自 `StrEnum`。

| 成员 | 值 | 说明 |
| --- | --- | --- |
| `HEALTHY` | `healthy` | 健康。 |
| `DEGRADED` | `degraded` | 降级可用。 |
| `UNHEALTHY` | `unhealthy` | 不健康。 |
| `UNKNOWN` | `unknown` | 未知。 |

### 8.3 `HealthCheckResult`

- **说明**：Provider 健康检查结果模型。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `provider_name` | `str` | - | Provider 名称。 |
| `status` | `ProviderStatus` | - | 健康状态。 |
| `checked_at` | `datetime` | - | 检查时间。 |
| `latency_ms` | `float \| None` | `None` | 检查耗时（毫秒）。 |
| `message` | `str \| None` | `None` | 状态说明信息。 |
| `details` | `dict[str, Any]` | `{}` | 扩展详情。 |

### 8.4 `CallResult`

- **说明**：Provider 方法调用结果模型，包含审计与成本元数据。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `provider_name` | `str` | - | Provider 名称。 |
| `provider_version` | `str` | - | Provider 版本。 |
| `success` | `bool` | - | 是否成功。 |
| `data` | `Any` | `None` | 返回数据。 |
| `error` | `str \| None` | `None` | 错误信息。 |
| `fetched_at` | `datetime` | `datetime.now()` | 获取时间。 |
| `available_at` | `datetime \| None` | `None` | 数据可用时间。 |
| `response_hash` | `str \| None` | `None` | 响应内容哈希。 |
| `cost` | `float` | `0.0` | 调用成本。 |
| `latency_ms` | `float \| None` | `None` | 调用耗时（毫秒）。 |
| `attempt_count` | `int` | `1` | 尝试次数。 |
| `from_fallback` | `bool` | `False` | 是否来自降级 Provider。 |

### 8.5 `ProviderDescriptor`

- **说明**：Provider 不可变元数据描述符，不包含真实凭证，仅保存引用名称。

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `name` | `str` | - | 唯一 Provider 名称。 |
| `version` | `str` | - | Provider 版本。 |
| `provider_type` | `ProviderType` | - | 能力分类。 |
| `capabilities` | `list[str]` | `[]` | 支持的方法名列表。 |
| `secret_refs` | `list[str]` | `[]` | 所需 Secret 引用名称。 |
| `config` | `dict[str, Any]` | `{}` | Provider 专属配置。 |

### 8.6 `BaseProvider`

- **说明**：所有 Provider 的抽象基类。

| 抽象属性/方法 | 签名 | 说明 |
| --- | --- | --- |
| `descriptor` | `@property @abstractmethod def descriptor(self) -> ProviderDescriptor` | 返回 Provider 的不可变元数据描述符。 |
| `healthcheck` | `@abstractmethod def healthcheck(self) -> HealthCheckResult` | 执行健康检查并返回结果。 |

### 8.7 `MarketDataProvider`

- **说明**：A 股市场数据 Provider 的协议（`runtime_checkable`）。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `get_securities` | `def get_securities(self, as_of: datetime) -> list[dict[str, Any]]` | 返回指定日期的证券全量列表。 |
| `get_bars` | `def get_bars(self, symbols: list[str], start: datetime, end: datetime, frequency: str = "1d") -> list[dict[str, Any]]` | 返回指定标的与区间的 OHLCV 行情。 |
| `get_adjustment_factors` | `def get_adjustment_factors(self, symbols: list[str], start: datetime, end: datetime) -> list[dict[str, Any]]` | 返回复权因子。 |
| `get_financials` | `def get_financials(self, symbols: list[str], start: datetime, end: datetime) -> list[dict[str, Any]]` | 返回财务指标。 |
| `get_index_members` | `def get_index_members(self, index_code: str, as_of: datetime) -> list[dict[str, Any]]` | 返回指数成分股。 |

### 8.8 `WebSearchProvider`

- **说明**：网络搜索 Provider 的协议（`runtime_checkable`）。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `search` | `def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]` | 执行网络搜索并返回结果列表。 |

---

## 9. Provider 注册中心

以下类与函数均位于 `src/margin/core/registry.py`。

### 9.1 `ProviderNotFoundError`

- **说明**：请求未注册的 Provider 时抛出，继承自 `KeyError`。

### 9.2 `ProviderAlreadyRegisteredError`

- **说明**：注册同名 Provider 且未设置 `allow_override=True` 时抛出，继承自 `ValueError`。

### 9.3 `ProviderRegistry`

- **说明**：Provider 注册中心，集成注册发现、健康检查、限流、重试、降级、密钥解析、审计日志与成本统计。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `_providers` | `dict[str, BaseProvider]` | Provider 名称到实例的映射。 |
| `_rate_limiters` | `dict[str, RateLimiter]` | 每个 Provider 的限流器。 |
| `_retry_configs` | `dict[str, RetryConfig]` | 每个 Provider 的重试配置。 |
| `_cost_rates` | `dict[str, float]` | 每个 Provider 的单次调用成本。 |
| `_fallbacks` | `dict[str, list[str]]` | 主 Provider 到降级链的映射。 |
| `_secret_manager` | `SecretManager` | 用于注册时解析 Secret 引用。 |
| `_audit_logger` | `AuditLogger` | 用于每次调用的审计日志。 |

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `def __init__(self, secret_manager: SecretManager \| None = None, audit_logger: AuditLogger \| None = None) -> None` | 初始化注册表，Secret 与审计日志器默认自动创建。 |
| `register` | `def register(self, provider: BaseProvider, *, rate_limiter: RateLimiter \| None = None, retry_config: RetryConfig \| None = None, cost_per_call: float = 0.0, fallback_names: list[str] \| None = None, allow_override: bool = False) -> None` | 注册 Provider，可选配置限流、重试、成本、降级链。 |
| `get` | `def get(self, name: str) -> BaseProvider` | 按名称获取已注册的 Provider。 |
| `list_by_type` | `def list_by_type(self, provider_type: ProviderType) -> list[str]` | 按能力类型过滤 Provider 名称。 |
| `list_all` | `def list_all(self) -> list[str]` | 返回所有已注册的 Provider 名称。 |
| `resolve_secrets` | `def resolve_secrets(self, name: str) -> dict[str, str]` | 解析指定 Provider 的所有 Secret 引用。 |
| `healthcheck` | `def healthcheck(self, name: str) -> HealthCheckResult` | 对单个 Provider 执行健康检查。 |
| `healthcheck_all` | `def healthcheck_all(self) -> dict[str, HealthCheckResult]` | 对所有 Provider 执行健康检查。 |
| `call` | `def call(self, provider_name: str, method: str, args: tuple = (), kwargs: dict[str, Any] \| None = None, trace_id: str = "") -> tuple[Any, CallResult]` | 调用 Provider 方法，自动处理重试、降级、审计与成本统计。 |
| `_call_single` | `def _call_single(self, name: str, method: str, args: tuple, kwargs: dict[str, Any], trace_id: str, is_fallback: bool) -> tuple[Any, CallResult]` | 内部方法：执行单次 Provider 调用，含限流与重试。 |
| `_inject_secrets` | `def _inject_secrets(self, provider: BaseProvider) -> None` | 注册时解析 Secret 并注入支持 `configure_secrets` 或 `set_token` 的 Provider。 |

### 9.4 内部辅助函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `_positional_args` | `def _positional_args(func: Callable, args: tuple) -> dict[str, Any]` | 将位置参数映射为参数名到值的字典，用于审计摘要。 |
| `_raw_positional_args` | `def _raw_positional_args(args: tuple) -> dict[str, Any]` | 将位置参数映射为 `argN` 形式字典。 |

---

## 10. 弹性组件

以下类型与函数均位于 `src/margin/core/resilience.py`。

### 10.1 `RateLimitError`

- **说明**：限流器无可用令牌时抛出。

### 10.2 `ProviderError`

- **说明**：Provider 调用失败时抛出，也作为默认可重试异常类型。

### 10.3 `RateLimiter`

- **说明**：基于令牌桶的限流器。当前实现非线程安全，适用于 MVP 单线程 Worker 场景。

| 属性 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `max_calls` | `int` | `60` | 令牌桶容量。 |
| `per_seconds` | `float` | `60.0` | 令牌补充周期（秒）。 |
| `_tokens` | `float` | 初始化时赋值为 `max_calls` | 当前可用令牌数。 |
| `_last_refill` | `float` | 初始化时赋值为当前时间 | 上次补充令牌时间戳。 |

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__post_init__` | `def __post_init__(self) -> None` | 初始化令牌桶为满容量。 |
| `_refill` | `def _refill(self) -> None` | 根据距上次补充的时长刷新令牌数。 |
| `acquire` | `def acquire(self) -> None` | 获取一个令牌，无可用时抛出 `RateLimitError`。 |
| `try_acquire` | `def try_acquire(self) -> bool` | 尝试获取一个令牌，不抛出异常，返回是否成功。 |

### 10.4 `RetryConfig`

- **说明**：重试行为配置数据类。

| 属性 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `max_retries` | `int` | `3` | 最大重试次数。 |
| `base_delay` | `float` | `1.0` | 首次重试延迟（秒）。 |
| `max_delay` | `float` | `30.0` | 最大重试延迟（秒）。 |
| `backoff_factor` | `float` | `2.0` | 指数退避乘数。 |
| `retry_on` | `tuple[type[Exception], ...]` | `(ProviderError,)` | 触发重试的异常类型。 |

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `compute_delay` | `def compute_delay(self, attempt: int) -> float` | 按指数退避计算第 `attempt` 次重试前的等待时间，上限为 `max_delay`。 |

### 10.5 `with_retry()`

| 项目 | 内容 |
| --- | --- |
| **签名** | `def with_retry(func: Callable[..., T], args: tuple = (), kwargs: dict[str, Any] \| None = None, config: RetryConfig \| None = None, rate_limiter: RateLimiter \| None = None, sleep: Callable[[float], None] = time.sleep) -> tuple[T, int]` |
| **说明** | 对函数调用添加重试、指数退避与可选限流。非可重试异常会立即抛出。 |

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `func` | `Callable[..., T]` | 待调用的函数。 |
| `args` | `tuple` | 位置参数。 |
| `kwargs` | `dict[str, Any] \| None` | 关键字参数。 |
| `config` | `RetryConfig \| None` | 重试配置，默认使用 `RetryConfig()`。 |
| `rate_limiter` | `RateLimiter \| None` | 可选的限流器。 |
| `sleep` | `Callable[[float], None]` | 等待函数，默认可注入用于测试。 |

| 返回值 | 说明 |
| --- | --- |
| `tuple[T, int]` | `(函数返回值, 实际尝试次数)`。 |

---

## 11. 密钥管理

以下类型与类均位于 `src/margin/core/secret.py`。

### 11.1 `SecretNotFoundError`

- **说明**：Secret 引用无法解析时抛出，继承自 `KeyError`。

### 11.2 `SecretManager`

- **说明**：引用式 Secret 管理器。配置文件只保存引用名，真实凭证在运行时从环境变量或本地密钥文件解析。
- **解析优先级**：
  1. 环境变量 `MARGIN_SECRET_<REF>`。
  2. 本地文件 `.margin/secrets/<ref>` 或自定义目录下的同名文件。

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `_secrets_dir` | `Path` | 本地密钥文件目录。 |
| `_env_prefix` | `str` | 环境变量前缀。 |
| `_cache` | `dict[str, str]` | 已解析 Secret 的内存缓存。 |

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `def __init__(self, secrets_dir: Path \| None = None, env_prefix: str = "MARGIN_SECRET_") -> None` | 初始化 Secret 管理器。 |
| `resolve` | `def resolve(self, ref: str) -> str` | 根据引用名解析真实 Secret 值。 |
| `has` | `def has(self, ref: str) -> bool` | 判断引用名是否可以解析。 |
| `list_refs` | `def list_refs(self) -> list[str]` | 列出所有可解析的引用名，不暴露值。 |

### 11.3 `SecretRefInfo`

- **说明**：用于展示的 Secret 引用元数据模型，不包含真实值。

### 11.4 v0.2 `SecretStore`

- **位置**：`src/margin/core/secret_store.py`
- **说明**：AES-GCM-256 版本化 Provider Secret Store。`create_or_replace` 写入随机 nonce 密文并停用旧 active secret；`metadata` 只返回 configured、last four、version/status/time；`resolve` 仅向受信 Provider adapter 返回 masked `SecretValue`。
- `get_secret_store()` 从 `MARGIN_SECRET_MASTER_KEY` 构建生产实例；缺失 master key 时拒绝启动 secret API，不生成临时 key。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `ref` | `str` | 引用名。 |
| `resolvable` | `bool` | 是否可解析。 |

---

## 12. FastAPI 应用装配说明

本章节说明 `src/margin/api/main.py` 中 `create_app()` 的装配逻辑。

### 12.1 注册路由

`create_app()` 按以下顺序注册路由模块：

| 路由文件 | Router 变量 | 功能标签 |
| --- | --- | --- |
| `src/margin/api/metrics.py` | `metrics_router` | Prometheus 指标端点 `/metrics`。 |
| `src/margin/api/routes/health.py` | `health_router` | 健康检查。 |
| `src/margin/api/routes/portfolios.py` | `portfolio_router` | 组合管理。 |
| `src/margin/api/routes/research.py` | `research_router` | 研究候选。 |
| `src/margin/api/routes/strategy.py` | `strategy_router` | 策略配置。 |
| `src/margin/api/routes/dashboard.py` | `dashboard_router` | 仪表盘。 |
| `src/margin/api/routes/monitoring.py` | `monitoring_router` | 持仓监控。 |

### 12.2 注册中间件

中间件按添加顺序由内到外生效：

| 中间件 | 类 | 位置 | 职责 |
| --- | --- | --- | --- |
| `TraceIdMiddleware` | `margin.api.middleware.TraceIdMiddleware` | `src/margin/api/middleware.py` | 优先读取请求头 `x-margin-trace-id`，不存在则生成新 trace ID，并在响应头回写。 |
| `MetricsMiddleware` | `margin.api.middleware.MetricsMiddleware` | `src/margin/api/middleware.py` | 记录 HTTP 请求数与耗时，使用路由路径模板避免高基数 URL。 |

### 12.3 依赖覆盖机制

`create_app()` 支持通过可选参数覆盖生产依赖，便于单元测试与集成测试：

| 注入参数 | 被覆盖的依赖函数 | 说明 |
| --- | --- | --- |
| `portfolio_service` | `get_portfolio_service` | 覆盖 Portfolio 服务。 |
| `research_service` | `get_research_service` | 覆盖 Research 服务。 |
| `strategy_service` | `get_strategy_service` | 覆盖 Strategy 服务。 |
| `dashboard_services` | `get_dashboard_services` | 覆盖 Dashboard 服务包。 |
| `monitoring_services` | `get_monitoring_services` | 覆盖持仓监控服务包。 |

---

## 13. 跨模块使用说明

- **配置传递**：所有生产级工厂均通过 `get_settings()` 读取环境配置，并通过 `build_database_engine()` 构造共享引擎。避免在业务代码中直接读取环境变量。
- **数据库会话生命周期**：当前版本依赖工厂返回 `SessionFactory`，由各 Repository 自行管理会话。API 路由未使用请求级会话中间件，Repository 需保证会话正确关闭。
- **Provider 注册中心使用**：业务模块若需统一调用多个 Provider，应通过 `ProviderRegistry` 注册实例，使用 `registry.call()` 获得限流、重试、降级、审计与成本统计能力。
- **Secret 安全**：所有 Provider 描述符中仅保存 `secret_refs` 引用名，真实凭证由 `SecretManager` 在运行时解析。避免将 API 密钥写入配置文件或日志。
- **缓存注意**：`@lru_cache` 装饰的依赖工厂在进程内缓存引擎与 Repository。测试时通过 `create_app(...)` 注入替代服务，或手动清除 `functools.lru_cache` 缓存。
- **Worker 与 API 共享引擎**：`worker.py` 与 `dependencies.py` 均使用 `create_database_engine()` 与 `create_session_factory()`，但分别在不同进程中创建独立引擎，不共享连接池。
- **缺失配置降级**：`build_provider_status_providers()` 对未配置的外部服务返回 `MissingConfiguredProvider`，确保仪表盘始终返回完整的 Provider 状态列表，而不是静默省略。
- **SQL 查询工厂**：所有 SQL 查询（原生 `text()` 字符串与 SQLAlchemy ORM `select()/insert()/update()/delete()` 构造器）集中在 `src/margin/sql/` 包中按业务域分模块定义，Repository 类只负责会话管理与行映射，不内联查询构造。详见 [§14 SQL 查询工厂](#14-sql-查询工厂)。

---

## 14. SQL 查询工厂

源码目录：`src/margin/sql/`

### 14.1 设计原则

- 所有 SQL 查询构造（`text()` 原生字符串、`select()/insert()/update()/delete()` ORM 构造器）集中到 `src/margin/sql/` 包。
- 按业务域分模块，每个查询一个独立函数，Repository 调用工厂函数获取 ready statement。
- Repository 只负责 session/transaction 管理 + 行到领域对象的映射，不写查询构造。
- `session.get(Model, id)` 主键查找不需要提取，保持原样。

### 14.2 模块清单

| 文件 | 查询函数数 | 覆盖的 Repository |
| --- | --- | --- |
| `raw_statements.py` | —（TextClause 常量） | health 路由、迁移验证脚本、修复脚本、回测脚本 |
| `health_queries.py` | 8 | `api/routes/health.py`、`worker_health_check.py`、`verify_migrations.py`、`smoke_full_v02.py` |
| `data_queries.py` | 36 | `warehouse_repository.py`、`sync_service.py`、`ingestion.py`、`company_pool.py`、`retention.py`、`policy.py`、`tushare_repository.py` |
| `strategy_queries.py` | 18 | `strategy/repository.py`、`scripts/bootstrap_config.py` |
| `news_queries.py` | 15 | `news/repository.py` |
| `evidence_queries.py` | 8 | `evidence/repository.py` |
| `valuation_queries.py` | 18 | `valuation_discovery/repository.py`、`valuation_discovery/adapters.py`、`valuation_discovery/analysis_mart.py` |
| `research_queries.py` | 6 | `research/repository.py`、`graph_audit_repository.py`、`delta_repository.py`、`checkpoint.py` |
| `core_queries.py` | 17 | `core/outbox.py`、`capacity.py`、`secret_store.py`、`audit_repository.py`、`orchestration_repository.py` |
| `vector_queries.py` | 5 | `vector/repository.py` |
| `dashboard_queries.py` | 5 | `dashboard/repository.py` |
| `backtest_queries.py` | 8 | `scripts/backtest_three_quant_pools_db.py` |
| **总计** | **144 函数** | — |

### 14.3 使用模式

**Repository 改造前：**
```python
class SQLAlchemyWarehouseRepository:
    def canonical_values(self, query):
        with self._session_factory() as session:
            statement = (
                select(CanonicalIndicatorValueRow)
                .where(CanonicalIndicatorValueRow.security_id.in_(query.security_ids))
                .where(CanonicalIndicatorValueRow.decision_at <= decision_at)
                .order_by(...)
            )
            rows = session.scalars(statement).all()
```

**Repository 改造后：**
```python
from margin.sql.data_queries import canonical_values_by_decision

class SQLAlchemyWarehouseRepository:
    def canonical_values(self, query):
        with self._session_factory() as session:
            statement = canonical_values_by_decision(
                security_ids=query.security_ids,
                decision_at=decision_at,
                indicator_ids=query.indicator_ids or None,
            )
            rows = session.scalars(statement).all()
```

### 14.4 原生 SQL 常量

`raw_statements.py` 存放所有 PostgreSQL 原生 SQL `TextClause` 常量，包括：

- 健康检查查询（alembic 版本、outbox 计数、worker 步骤计数）
- 迁移验证查询（pg_extension 检查、非系统表列表、数据库连接终止）
- index_weight 元数据修复 SQL（复杂 CTE + UPDATE）
- 回测脚本覆盖检查 SQL
