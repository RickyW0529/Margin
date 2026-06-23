# 01-data_provider 模块文档

本文档覆盖 Margin 当前实现 数据层（data provider）全部公共接口与核心实现，文件位于 `src/margin/data/` 与 `src/margin/core/`。

---

## 目录

1. [模块概述与职责](#1-模块概述与职责)
2. [文件级摘要](#2-文件级摘要)
3. [Provider 协议与基类](#3-provider-协议与基类)
4. [具体 Provider 实现](#4-具体-provider-实现)
5. [Provider 注册中心](#5-provider-注册中心)
6. [数据标准化](#6-数据标准化)
7. [数据质量检查](#7-数据质量检查)
8. [v0.2 PIT 数据仓库与同步管线](#8-v02-pit-数据仓库与同步管线)
9. [跨模块使用说明](#9-跨模块使用说明)

---

## 1. 模块概述与职责

`01-data_provider` 是 Margin 系统的数据入口层，负责：

- **外部数据源适配**：封装 AKShare、Tushare 等 A 股数据接口，统一输出格式。
- **Provider 协议定义**：通过 `BaseProvider` 与 `Protocol` 约束所有数据提供方，使系统可按能力（市场数据、网页搜索等）解耦。
- **字段标准化**：将不同来源的字段、代码、单位、时间统一为内部标准事件 `StandardDataEvent`。
- **数据质量检查**：在入库前校验必要字段、时间点合规性、异常值、未来信息泄露等。
- **注册与调用治理**：`ProviderRegistry` 提供注册、发现、健康检查、限流、重试、降级、审计、成本统计等统一入口。
- **PIT 数据仓库**：v0.2 新增 Raw Snapshot、Provider Fact、Canonical Value、bitemporal 行业、公司行动和 freshness 状态等表，保留全量底层数据。
- **增量同步编排**：v0.2 新增 endpoint registry、sync run/work item、claim/retry/freshness 和 ingestion stack，支持 provider payload 到 canonical 值的端到端落库。

该模块的产品与架构边界见对应大版本的 `docs/design/`；本文描述当前已实现的数据 Provider 能力。

---

## 2. 文件级摘要

| 文件路径 | 作用 |
|---|---|
| `src/margin/data/__init__.py` | 数据层包入口，汇总导出标准化、质量检查相关公共类与函数。 |
| `src/margin/data/providers/__init__.py` | Provider 子包入口，导出 `AKShareProvider`、`TushareProvider`。 |
| `src/margin/data/providers/akshare_provider.py` | AKShare 数据提供方实现，覆盖行情、财务、指数成分等接口。 |
| `src/margin/data/providers/tushare_provider.py` | Tushare Pro 数据提供方实现，支持 Token 注入。 |
| `src/margin/data/db_models.py` | v0.2 PIT 数据仓库 ORM：endpoint、sync run、raw snapshot、schema field、facts、canonical、行业、公司行动、freshness、retention audit。 |
| `src/margin/data/endpoints.py` | Provider endpoint 描述、回填策略、限流策略和默认 AKShare/Tushare endpoint registry。 |
| `src/margin/data/sync_models.py` | `DataSyncRequest`、`DataSyncRun`、`EndpointWorkItem`、`EndpointSyncResult` 和状态枚举。 |
| `src/margin/data/sync_service.py` | DB-backed sync run/work item 创建、排他 claim、retry-safe cursor 和 endpoint 执行。 |
| `src/margin/data/ingestion.py` | Provider payload → compressed raw snapshot → schema observation → standardized facts → canonical values 的集成管线。 |
| `src/margin/data/freshness.py` | 按数据域计算 expected-as-of 与 freshness 状态。 |
| `src/margin/data/warehouse_repository.py` | 下游读取的 PIT-safe repository：canonical、industry、adjusted price、freshness、quality event。 |
| `src/margin/data/retention.py` | 引用感知的 retention 删除与不可变 audit。 |
| `src/margin/data/schema_discovery.py` | Source schema 字段生命周期与 missing/type-change 检测。 |
| `src/margin/data/facts.py`、`src/margin/data/canonical.py`、`src/margin/data/indicator_catalog.py` | 标准化指标事实、canonical resolver 和指标映射目录。 |
| `src/margin/data/security_master.py`、`src/margin/data/industry.py`、`src/margin/data/corporate_actions.py` | 证券主数据、bitemporal 行业成员和 PIT-safe 公司行动/复权计算。 |
| `src/margin/data/standardize.py` | 字段映射、代码规范化、单位换算、时间标准化、标准事件生成。 |
| `src/margin/data/quality.py` | 时间点字段校验、未来信息泄露检查、数据质量报告与事件。 |
| `src/margin/core/provider.py` | Provider 类型、状态、描述符、基类与业务协议（市场数据、网页搜索）。 |
| `src/margin/core/registry.py` | Provider 注册中心，集成健康检查、限流、重试、降级、审计、密钥注入。 |
| `scripts/smoke_data_provider.py` | 真实 AKShare/Tushare smoke 入口；输出 provider 状态、计数和 snapshot ID，不输出 token。 |

---

## 3. Provider 协议与基类

源码文件：`src/margin/core/provider.py`

### 3.1 枚举与数据模型

| 类/枚举 | 说明 |
|---|---|
| `ProviderType(StrEnum)` | Provider 能力分类：`MARKET_DATA`、`WEB_SEARCH`、`LLM`、`EMBEDDING`、`RERANK`、`VECTOR_STORE`、`NOTIFICATION`。 |
| `ProviderStatus(StrEnum)` | 健康状态：`HEALTHY`、`DEGRADED`、`UNHEALTHY`、`UNKNOWN`。 |
| `HealthCheckResult(BaseModel)` | 健康检查结果，包含 `provider_name`、`status`、`checked_at`、`latency_ms`、`message`、`details`。 |
| `CallResult(BaseModel)` | 统一调用结果，包含 `provider_name`、`provider_version`、`success`、`data`、`error`、时间戳、响应哈希、成本、延迟、尝试次数、`from_fallback`。 |
| `ProviderDescriptor(BaseModel)` | Provider 元数据描述符（不可变），包含名称、版本、类型、能力列表、`secret_refs`、配置字典。 |

### 3.2 `BaseProvider`

所有 Provider 的抽象基类。

| 方法/属性 | 签名 | 说明 |
|---|---|---|
| `descriptor` | `@property @abstractmethod def descriptor(self) -> ProviderDescriptor` | 返回 Provider 元数据描述符。子类必须实现。 |
| `healthcheck` | `@abstractmethod def healthcheck(self) -> HealthCheckResult` | 返回健康检查结果。子类必须实现。 |

### 3.3 `MarketDataProvider`（Protocol）

A 股市场数据协议，使用 `@runtime_checkable` 支持结构子类型检查。

| 方法 | 签名 | 说明 |
|---|---|---|
| `get_securities` | `def get_securities(self, as_of: datetime) -> list[dict[str, Any]]` | 返回指定日期的证券列表。 |
| `get_bars` | `def get_bars(self, symbols, start, end, frequency="1d") -> list[dict[str, Any]]` | 返回 OHLCV 行情条。 |
| `get_adjustment_factors` | `def get_adjustment_factors(self, symbols, start, end) -> list[dict[str, Any]]` | 返回复权因子。 |
| `get_financials` | `def get_financials(self, symbols, start, end) -> list[dict[str, Any]]` | 返回财务指标。 |
| `get_index_members` | `def get_index_members(self, index_code, as_of) -> list[dict[str, Any]]` | 返回指数成分股。 |

### 3.4 `WebSearchProvider`（Protocol）

网页搜索能力协议。

| 方法 | 签名 | 说明 |
|---|---|---|
| `search` | `def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]` | 执行搜索并返回结果列表。 |

---

## 4. 具体 Provider 实现

### 4.1 `AKShareProvider`

源码文件：`src/margin/data/providers/akshare_provider.py`

基于 AKShare 的 A 股数据提供方，无需 Token，但需遵守其频率限制。

**配置描述符**

| 属性 | 值 |
|---|---|
| 名称 | `akshare` |
| 版本 | `1.0.0` |
| 类型 | `ProviderType.MARKET_DATA` |
| 能力 | `get_securities`、`get_bars`、`get_adjustment_factors`、`get_financials`、`get_index_members` |
| 密钥引用 | `[]`（无需密钥） |
| 配置 | `{"license": "free", "limits": "尊重 akshare 频率限制"}` |

**公共方法**

| 方法 | 签名 | 返回值说明 |
|---|---|---|
| `__init__` | `def __init__(self) -> None` | 初始化并构建描述符。 |
| `descriptor` | `@property def descriptor(self) -> ProviderDescriptor` | 返回描述符。 |
| `healthcheck` | `def healthcheck(self) -> HealthCheckResult` | 调用 `ak.stock_zh_a_spot_em()` 测试连通性。 |
| `get_securities` | `def get_securities(self, as_of: datetime) -> list[dict[str, Any]]` | 返回 A 股实时快照，字段包括 `symbol`、`name`、`close`、`fetched_at`、`available_at`、`source`。 |
| `get_bars` | `def get_bars(self, symbols, start, end, frequency="1d") -> list[dict[str, Any]]` | 返回 OHLCV。支持 `1d`、`1w`、`1M`；使用 `ak.stock_zh_a_hist` 的 `qfq` 复权。 |
| `get_adjustment_factors` | `def get_adjustment_factors(self, symbols, start, end) -> list[dict[str, Any]]` | 使用 `hfq` 后复权序列返回 `hfq_close`。 |
| `get_financials` | `def get_financials(self, symbols, start, end) -> list[dict[str, Any]]` | 返回资产负债表数据：`report_date`、`ann_date`、`total_assets`、`total_liabilities`、`total_equity`。 |
| `get_index_members` | `def get_index_members(self, index_code, as_of) -> list[dict[str, Any]]` | 返回指数成分股，字段包括 `symbol`、`index_code`、`name`、`as_of`。 |

**内部辅助函数**

| 函数 | 签名 | 说明 |
|---|---|---|
| `_sz_sh_symbol` | `def _sz_sh_symbol(raw: str) -> str` | 将 AKShare 原始代码转为 `000001.SZ`/`600000.SH` 标准格式。 |
| `_fmt_date` | `def _fmt_date(d: datetime) -> str` | 格式化为 `%Y%m%d`。 |
| `_market_bar_available_at` | `def _market_bar_available_at(trade_date: datetime) -> datetime` | 返回交易日 15:00 作为日线可用时间。 |
| `_parse_optional_date` | `def _parse_optional_date(value: Any) -> datetime \| None` | 解析 `%Y-%m-%d` 或 `%Y%m%d` 日期。 |

### 4.2 `TushareProvider`

源码文件：`src/margin/data/providers/tushare_provider.py`

基于 Tushare Pro API 的 A 股数据提供方，需要外部注入 `tushare_token`。

**配置描述符**

| 属性 | 值 |
|---|---|
| 名称 | `tushare` |
| 版本 | `1.0.0` |
| 类型 | `ProviderType.MARKET_DATA` |
| 能力 | `get_securities`、`get_bars`、`get_adjustment_factors`、`get_financials`、`get_index_members` |
| 密钥引用 | `["tushare_token"]` |
| 配置 | `{"license": "用户自行配置 token", "limits": "遵守 tushare 频率限制"}` |

**公共方法**

| 方法 | 签名 | 说明 |
|---|---|---|
| `__init__` | `def __init__(self, token: str \| None = None) -> None` | 可选初始化 Token。 |
| `descriptor` | `@property def descriptor(self) -> ProviderDescriptor` | 返回描述符。 |
| `set_token` | `def set_token(self, token: str) -> None` | 设置或更新 Token，清空已有 API 客户端。 |
| `configure_secrets` | `def configure_secrets(self, secrets: dict[str, str]) -> None` | 从注册中心接收解析后的密钥映射，提取 `tushare_token`。 |
| `_ensure_pro` | `def _ensure_pro(self) -> Any` | 延迟初始化 Tushare Pro 客户端。 |
| `healthcheck` | `def healthcheck(self) -> HealthCheckResult` | 调用 `pro.stock_basic` 测试连通性。 |
| `get_securities` | `def get_securities(self, as_of: datetime) -> list[dict[str, Any]]` | 返回上市 A 股基础信息，含 `industry`、`market`、`list_date`。 |
| `get_bars` | `def get_bars(self, symbols, start, end, frequency="1d") -> list[dict[str, Any]]` | 返回日线 OHLCV；成交量乘以 100，成交额乘以 1000。 |
| `get_adjustment_factors` | `def get_adjustment_factors(self, symbols, start, end) -> list[dict[str, Any]]` | 返回 `adj_factor` 复权因子。 |
| `get_financials` | `def get_financials(self, symbols, start, end) -> list[dict[str, Any]]` | 返回财务指标：`report_date`、`ann_date`、`roe`、`eps`、`gross_profit_margin`。 |
| `get_index_members` | `def get_index_members(self, index_code, as_of) -> list[dict[str, Any]]` | 返回指数成分权重，字段包括 `weight`。 |

**内部辅助函数**

| 函数 | 签名 | 说明 |
|---|---|---|
| `_fmt_date` | `def _fmt_date(d: datetime) -> str` | 格式化为 `%Y%m%d`。 |
| `_tushare_symbol` | `def _tushare_symbol(symbol: str) -> str` | 内部代码转 Tushare 格式（当前为透传）。 |
| `_market_bar_available_at` | `def _market_bar_available_at(trade_date: datetime) -> datetime` | 交易日 15:00。 |
| `_next_market_open_after` | `def _next_market_open_after(value: datetime) -> datetime` | 返回下一个交易日 09:30，用于公告可用时间。 |

---

## 5. Provider 注册中心

源码文件：`src/margin/core/registry.py`

### 5.1 异常

| 异常 | 说明 |
|---|---|
| `ProviderNotFoundError(KeyError)` | 请求未注册的 Provider 时抛出。 |
| `ProviderAlreadyRegisteredError(ValueError)` | 重复注册同名 Provider 且 `allow_override=False` 时抛出。 |

### 5.2 `ProviderRegistry`

统一注册中心，集成限流、重试、降级、审计、成本统计、密钥注入。

**构造与注册**

| 方法 | 签名 | 说明 |
|---|---|---|
| `__init__` | `def __init__(self, secret_manager=None, audit_logger=None) -> None` | 初始化注册中心，可传入 `SecretManager` 与 `AuditLogger`。 |
| `register` | `def register(self, provider, *, rate_limiter=None, retry_config=None, cost_per_call=0.0, fallback_names=None, allow_override=False) -> None` | 注册 Provider 并自动注入密钥。 |
| `get` | `def get(self, name: str) -> BaseProvider` | 按名称获取 Provider 实例。 |
| `list_by_type` | `def list_by_type(self, provider_type: ProviderType) -> list[str]` | 按类型筛选已注册 Provider 名称。 |
| `list_all` | `def list_all(self) -> list[str]` | 返回所有已注册 Provider 名称。 |

**健康检查**

| 方法 | 签名 | 说明 |
|---|---|---|
| `healthcheck` | `def healthcheck(self, name: str) -> HealthCheckResult` | 对单个 Provider 执行健康检查。 |
| `healthcheck_all` | `def healthcheck_all(self) -> dict[str, HealthCheckResult]` | 对所有 Provider 执行健康检查。 |

**密钥与调用**

| 方法 | 签名 | 说明 |
|---|---|---|
| `resolve_secrets` | `def resolve_secrets(self, name: str) -> dict[str, str]` | 解析指定 Provider 的全部密钥引用。 |
| `call` | `def call(self, provider_name, method, args=(), kwargs=None, trace_id="") -> tuple[Any, CallResult]` | 统一调用入口，自动执行重试、降级、审计与成本统计。 |

**内部方法**

| 方法 | 签名 | 说明 |
|---|---|---|
| `_call_single` | `def _call_single(self, name, method, args, kwargs, trace_id, is_fallback) -> tuple[Any, CallResult]` | 单次 Provider 调用，含限流与重试。 |
| `_inject_secrets` | `def _inject_secrets(self, provider: BaseProvider) -> None` | 解析密钥并调用 Provider 的 `configure_secrets` 或 `set_token`。 |

**内部辅助函数**

| 函数 | 签名 | 说明 |
|---|---|---|
| `_positional_args` | `def _positional_args(func, args) -> dict[str, Any]` | 将位置参数映射为参数名，用于审计日志。 |
| `_raw_positional_args` | `def _raw_positional_args(args) -> dict[str, Any]` | 将位置参数映射为 `argN` 形式。 |

---

## 6. 数据标准化

源码文件：`src/margin/data/standardize.py`

### 6.1 代码映射

| 类/函数 | 签名 | 说明 |
|---|---|---|
| `Exchange(StrEnum)` | `SH = "SH"`, `SZ = "SZ"` | A 股交易所枚举。 |
| `normalize_symbol` | `def normalize_symbol(raw: str) -> str` | 将多种格式统一为 `<code>.<EXCHANGE>`。 |
| `symbol_components` | `def symbol_components(symbol: str) -> tuple[str, str]` | 拆分代码与交易所，无法拆分则抛出 `ValueError`。 |

`normalize_symbol` 支持输入格式：

| 输入示例 | 输出示例 |
|---|---|
| `000001` | `000001.SZ` |
| `600000` | `600000.SH` |
| `000001.SZ` | `000001.SZ` |
| `sz000001` | `000001.SZ` |
| `sh600000` | `600000.SH` |

### 6.2 字段映射

| 类 | 说明 |
|---|---|
| `DataDomain(StrEnum)` | 数据域：`MARKET_BAR`、`FINANCIAL`、`SECURITY_META`、`INDEX_MEMBER`、`ADJUSTMENT_FACTOR`、`CORPORATE_ACTION`。 |
| `FieldMapping(BaseModel)` | 单字段映射规则：`source_field`、`target_field`、`transform`、`unit_factor`。 |

当前内置映射 `FIELD_MAPPINGS` 仅包含 `MARKET_BAR` 域的中文行情字段到标准字段映射。

### 6.3 单位换算

| 类/方法 | 签名 | 说明 |
|---|---|---|
| `UnitConverter.CURRENCY` | 类常量 `"CNY"` | 默认货币。 |
| `UnitConverter.convert_amount` | `def convert_amount(value: float, source_unit="yuan") -> float` | 金额换算为人民币元，支持 `qian_yuan`、`wan_yuan`、`yi_yuan`。 |
| `UnitConverter.convert_volume` | `def convert_volume(value: float, source_unit="gu") -> float` | 成交量换算为股，支持 `shou`（1 手 = 100 股）。 |

### 6.4 时间标准化

| 类/函数 | 签名 | 说明 |
|---|---|---|
| `TimeStandardizer.parse_date` | `def parse_date(value: Any) -> datetime \| None` | 支持 `%Y-%m-%d`、`%Y%m%d`、`%Y/%m/%d`、`%Y-%m-%d %H:%M:%S` 等格式。 |
| `TimeStandardizer.to_pit_fields` | `def to_pit_fields(event_at=None, published_at=None, available_at=None, fetched_at=None, revised_at=None) -> dict[str, datetime]` | 生成五个时间点字段，缺失值自动回退填充。 |
| `market_bar_available_at` | `def market_bar_available_at(trade_date: datetime) -> datetime` | 日线可用时间 = 交易日 15:00。 |
| `next_market_open_after` | `def next_market_open_after(value: datetime) -> datetime` | 公告等无明确时间的数据，保守取次日 09:30。 |

### 6.5 标准数据事件

| 类/属性 | 说明 |
|---|---|
| `StandardDataEvent(BaseModel)` | 标准化后的数据事件。属性包括 `domain`、`symbol`、`data`、`event_at`、`published_at`、`available_at`、`fetched_at`、`revised_at`、`source`、`mapping_version`。 |

### 6.6 `Standardizer`

将外部原始记录转换为 `StandardDataEvent`。

| 方法 | 签名 | 说明 |
|---|---|---|
| `__init__` | `def __init__(self, mapping_version="v1") -> None` | 初始化标准器，指定映射版本。 |
| `standardize_bars` | `def standardize_bars(self, raw_records, source) -> list[StandardDataEvent]` | 标准化行情条到 `MARKET_BAR` 域。 |
| `standardize_securities` | `def standardize_securities(self, raw_records, source) -> list[StandardDataEvent]` | 标准化证券元数据到 `SECURITY_META` 域。 |
| `standardize_financials` | `def standardize_financials(self, raw_records, source) -> list[StandardDataEvent]` | 标准化财务报告到 `FINANCIAL` 域。 |
| `standardize_index_members` | `def standardize_index_members(self, raw_records, source) -> list[StandardDataEvent]` | 标准化指数成分到 `INDEX_MEMBER` 域。 |

---

## 7. 数据质量检查

源码文件：`src/margin/data/quality.py`

### 7.1 时间点字段校验

| 常量/异常 | 说明 |
|---|---|
| `PIT_FIELDS` | 元组：`("event_at", "published_at", "available_at", "fetched_at", "revised_at")`。 |
| `PITFieldError(ValueError)` | 必要时间点字段缺失或类型错误时抛出。 |

| 函数 | 签名 | 说明 |
|---|---|---|
| `validate_pit_fields` | `def validate_pit_fields(record: dict \| StandardDataEvent) -> None` | 校验 `event_at`、`published_at`、`available_at`、`fetched_at` 为 `datetime`；`revised_at` 可为 `None`。 |

### 7.2 反未来信息泄露

| 异常 | 说明 |
|---|---|
| `LookaheadError(ValueError)` | `available_at` 晚于 `decision_at` 时抛出。 |

| 函数 | 签名 | 说明 |
|---|---|---|
| `check_no_lookahead` | `def check_no_lookahead(record, decision_at) -> bool` | 校验 `available_at <= decision_at`，否则抛出 `LookaheadError`。 |
| `filter_by_decision_at` | `def filter_by_decision_at(records, decision_at) -> tuple[list, list]` | 按 `decision_at` 分割记录，返回 `(passed, rejected)`。 |

### 7.3 质量检查模型

| 类 | 说明 |
|---|---|
| `QualityIssueType(StrEnum)` | 问题类型：`MISSING_FIELD`、`MISSING_VALUE`、`OUTLIER`、`REVISION`、`STALE_DATA`、`DUPLICATE`、`LOOKAHEAD`。 |
| `QualityIssue(BaseModel)` | 单个质量问题：`issue_type`、`symbol`、`field_name`、`message`、`severity`。 |
| `QualityReport(BaseModel)` | 质量报告：`checked_at`、`total_records`、`issues`、`passed`；属性 `issue_count`、`critical_count`。 |

### 7.4 `DataQualityChecker`

| 方法 | 签名 | 说明 |
|---|---|---|
| `__init__` | `def __init__(self, required_fields=None, stale_threshold_hours=72.0) -> None` | 初始化检查器。默认必填字段映射见下表。 |
| `check` | `def check(self, records: list[StandardDataEvent]) -> QualityReport` | 批量检查，返回 `QualityReport`。 |

默认 `required_fields`：

| 域 | 必填字段 |
|---|---|
| `market_bar` | `open`、`close`、`high`、`low`、`volume` |
| `financial` | `roe` |
| `security_meta` | `name` |
| `index_member` | `index_code` |

`check` 方法执行项目：

- 必填字段非空检查（`MISSING_VALUE`）。
- `market_bar` 域价格非正、成交量为负检测（`OUTLIER`，`critical`）。
- `revised_at` 非空时标记为 `REVISION`（`info`）。
- `fetched_at - available_at` 超过阈值时标记 `STALE_DATA`（`warning`）。
- 存在 `critical` 问题时 `passed=False`。

### 7.5 质量事件

| 类 | 说明 |
|---|---|
| `QualityEventSeverity(StrEnum)` | `INFO`、`WARNING`、`CRITICAL`。 |
| `DataQualityEvent(BaseModel)` | 数据质量事件：`event_id`、`severity`、`source`、`domain`、`message`、`affected_symbols`、`issue_count`、`emitted_at`；属性 `should_suppress_research` 在 `CRITICAL` 时返回 `True`。 |
| `QualityEventEmitter` | 质量事件生成器，支持从报告生成事件或手动生成事件，并维护事件历史。 |

`QualityEventEmitter` 方法：

| 方法 | 签名 | 说明 |
|---|---|---|
| `__init__` | `def __init__(self) -> None` | 初始化空事件列表与计数器。 |
| `emit_from_report` | `def emit_from_report(self, report, source, domain) -> DataQualityEvent \| None` | 根据 `QualityReport` 生成事件；无问题时返回 `None`。 |
| `emit_custom` | `def emit_custom(self, severity, source, domain, message, affected_symbols=None) -> DataQualityEvent` | 手动生成事件。 |
| `events` | `@property def events(self) -> list[DataQualityEvent]` | 返回已生成事件副本。 |
| `has_critical` | `@property def has_critical(self) -> bool` | 是否存在会抑制研究信号的 `CRITICAL` 事件。 |

---

## 8. v0.2 PIT 数据仓库与同步管线

### 8.1 数据库与迁移

Alembic revision `20260622_0010_data_warehouse.py` 新增 v0.2 数据仓库表：

- `provider_endpoints`、`data_sync_runs`、`data_sync_work_items`：记录全量 endpoint 配置、同步 run 和 endpoint work item；
- `raw_data_snapshots`：保存 provider 原始响应的 content-addressed zstd snapshot metadata；
- `source_schema_fields`：记录源字段 first/last seen、类型变化和连续缺失；
- `standardized_indicator_facts`：保留所有 provider 标准化事实，不覆盖历史；
- `canonical_indicator_values`：保存 resolver 在某个 `decision_at` 的 canonical 选择，同时保留 candidate fact IDs；
- `securities`、`security_provider_identifiers`、`security_industry_memberships`：证券和 bitemporal 行业/代码映射；
- `corporate_actions`、`adjusted_price_series`：公司行动事实和 as-of 复权价格；
- `data_quality_events`、`data_freshness_states`、`retention_deletion_audits`：质量、freshness 和 retention 审计。

### 8.2 同步与落库流程

`DataWarehouseIngestionStack.sync_daily_bars()` 当前实现日线行情端到端路径：

```text
Provider.get_bars
  → DataSyncRun / EndpointWorkItem
  → CompressedSnapshotStore.write_json
  → raw_data_snapshots
  → source_schema_fields
  → Standardizer.standardize_bars
  → standardized_indicator_facts
  → CanonicalResolver
  → canonical_indicator_values
  → SQLAlchemyWarehouseRepository.canonical_values
```

关键行为：

- work item 在外部 provider 调用前持久化；
- claim 使用数据库锁定语义，避免多 worker 重复执行同一 endpoint；
- provider 失败时不推进 cursor，状态为 `failed_retryable`；
- canonical 查询必须显式传入 `decision_at`，否则抛出 `PITQueryError`；
- retention 删除会检查 `standardized_indicator_facts` 和 `corporate_actions` 引用，被引用 raw snapshot 只写 protected audit，不删除。

### 8.3 Freshness 与生产依赖

`FreshnessCalculator` 按数据域计算 expected-as-of：

- market / valuation：使用交易日历和 provider 可用时间；
- financial：使用披露滞后窗口；
- filing / news：使用自然日可用时间。

`MarginSettings` 当前新增：

- `MARGIN_DATA_SNAPSHOT_ROOT`：compressed raw snapshot 根目录；
- `MARGIN_DATA_SYNC_ON_STARTUP`：是否启动 data sync job；
- `MARGIN_DATA_FRESHNESS_TIMEZONE`：freshness 判断时区；
- `MARGIN_DATA_SMOKE_SYMBOLS`：真实 smoke 使用的股票代码；
- `MARGIN_TUSHARE_TOKEN`：Tushare token，`SecretStr` 掩码，不应写入源码或日志。
- `MARGIN_TUSHARE_HTTP_URL`：可选 Tushare 兼容 API 地址，例如用户自有代理或 TeaJoin 服务。

`margin.api.dependencies.build_data_warehouse_stack()` 和 `margin.worker.build_data_ingestion_stack()` 会从统一 settings 构建 DB-backed ingestion stack。

### 8.4 验证入口

- 单元/集成测试：`pytest tests/data/warehouse -v`
- 真实 provider smoke：`python scripts/smoke_data_provider.py --providers akshare,tushare`
- dry-run 配置检查：`python scripts/smoke_data_provider.py --providers tushare --dry-run`

真实 smoke 输出 JSON，只包含 provider、状态、snapshot ID、fact/canonical 计数和错误摘要；token 会被脱敏。

## 9. 跨模块使用说明

- **Provider 注册**：业务代码通常通过 `ProviderRegistry` 注册 `AKShareProvider` 或 `TushareProvider`，由注册中心自动完成密钥注入、限流与重试。`TushareProvider` 的 `tushare_token` 由 `SecretManager` 解析后通过 `configure_secrets` 注入。
- **标准化流程**：外部原始数据先经 `Standardizer` 转为 `StandardDataEvent`，再进入 ODS/DWD/PIT 存储链路。流程为：字段映射 → 代码映射 → 单位/货币统一 → 时间标准化 → 标准事件。
- **质量 gate**：在回测或研究信号生成前，使用 `DataQualityChecker.check()` 生成 `QualityReport`，并通过 `QualityEventEmitter` 发布事件。`CRITICAL` 事件可通过 `should_suppress_research` 抑制高置信度信号输出。
- **反未来信息泄露**：回测框架应在每个决策点调用 `check_no_lookahead(record, decision_at)` 或 `filter_by_decision_at(records, decision_at)`，确保只使用 `available_at` 之前的数据。
- **审计与可观测性**：`ProviderRegistry.call()` 自动记录审计日志并更新 Prometheus 指标 `PROVIDER_CALLS` 与 `PROVIDER_DEGRADED`，便于监控与故障降级。
- **扩展新 Provider**：实现 `BaseProvider` 的子类，并按需满足 `MarketDataProvider` 或 `WebSearchProvider` 协议，即可通过注册中心统一接入。
