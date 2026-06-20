# 01-data_provider Module Documentation

Complete function-level documentation for the Margin v0.1 data provider module.

## Table of Contents

1. [Module Overview and Responsibilities](#1-module-overview-and-responsibilities)
2. [File-level Summaries](#2-file-level-summaries)
3. [Provider Protocols and Base Classes](#3-provider-protocols-and-base-classes)
   - 3.1 [ProviderType](#31-providertype)
   - 3.2 [ProviderStatus](#32-providerstatus)
   - 3.3 [HealthCheckResult](#33-healthcheckresult)
   - 3.4 [CallResult](#34-callresult)
   - 3.5 [ProviderDescriptor](#35-providerdescriptor)
   - 3.6 [BaseProvider](#36-baseprovider)
   - 3.7 [MarketDataProvider](#37-marketdataprovider)
   - 3.8 [WebSearchProvider](#38-websearchprovider)
4. [Concrete Providers](#4-concrete-providers)
   - 4.1 [AKShareProvider](#41-akshareprovider)
   - 4.2 [TushareProvider](#42-tushareprovider)
5. [Registry](#5-registry)
   - 5.1 [ProviderRegistry](#51-providerregistry)
   - 5.2 [Registry Exceptions](#52-registry-exceptions)
6. [Standardization](#6-standardization)
   - 6.1 [Symbol Utilities](#61-symbol-utilities)
   - 6.2 [DataDomain and FieldMapping](#62-datadomain-and-fieldmapping)
   - 6.3 [UnitConverter](#63-unitconverter)
   - 6.4 [TimeStandardizer](#64-timestandardizer)
   - 6.5 [StandardDataEvent](#65-standarddataevent)
   - 6.6 [Standardizer](#66-standardizer)
7. [Quality](#7-quality)
   - 7.1 [Point-in-Time Fields](#71-point-in-time-fields)
   - 7.2 [Anti-Lookahead Checks](#72-anti-lookahead-checks)
   - 7.3 [Data Quality Checks](#73-data-quality-checks)
   - 7.4 [Quality Events](#74-quality-events)
8. [Cross-Module Usage Notes](#8-cross-module-usage-notes)

---

## 1. Module Overview and Responsibilities

The `01-data_provider` module is the data ingestion and normalization layer of Margin v0.1. It is responsible for fetching A-share market data from external vendors, converting heterogeneous formats into a canonical internal schema, validating point-in-time correctness, and surfacing data quality issues.

Key responsibilities:

- **Provider abstraction**: Define a uniform contract (`BaseProvider`, typed protocols) for all external data sources.
- **Concrete adapters**: Implement adapters for AKShare and Tushare, the two primary A-share data sources in v0.1.
- **Registry integration**: Register provider instances, resolve secrets, apply rate limits, retries, fallbacks, audit logging, and cost tracking.
- **Symbol standardization**: Normalize raw symbols (e.g. `SZ000001`, `000001`) into the canonical `<code>.<EXCHANGE>` form.
- **Field and unit standardization**: Map vendor-specific field names, unify monetary amounts to CNY yuan, and convert trading volume to shares.
- **Time standardization**: Produce the five point-in-time (PIT) fields (`event_at`, `published_at`, `available_at`, `fetched_at`, `revised_at`) required for downstream simulation.
- **Data quality**: Validate required fields, detect outliers, stale data, revisions, duplicates, and future-data leakage.
- **Quality events**: Emit structured events that can suppress high-confidence research signals when critical issues are detected.

---

## 2. File-level Summaries

| File | Purpose |
|------|---------|
| `src/margin/data/__init__.py` | Public package exports for the data layer. Re-exports quality, standardization, and provider symbols. |
| `src/margin/data/providers/__init__.py` | Public exports for concrete provider implementations. |
| `src/margin/data/providers/akshare_provider.py` | `AKShareProvider` implementation for A-share quotes, fundamentals, indices, and announcement metadata. |
| `src/margin/data/providers/tushare_provider.py` | `TushareProvider` implementation backed by the Tushare Pro API. |
| `src/margin/data/standardize.py` | Symbol normalization, field mapping, unit/currency conversion, time standardization, and `StandardDataEvent` creation. |
| `src/margin/data/quality.py` | Point-in-time field validation, anti-lookahead checks, data quality inspection, and quality event emission. |
| `src/margin/core/provider.py` | Core provider abstractions: enums, descriptors, health results, call results, and business protocols. |
| `src/margin/core/registry.py` | `ProviderRegistry` for registration, discovery, secret injection, health checks, and resilient call dispatch. |

---

## 3. Provider Protocols and Base Classes

Defined in `src/margin/core/provider.py`.

### 3.1 ProviderType

Capability category of a provider.

| Member | Value | Description |
|--------|-------|-------------|
| `MARKET_DATA` | `"market_data"` | Market data provider (quotes, fundamentals, indices). |
| `WEB_SEARCH` | `"web_search"` | Web search provider. |
| `LLM` | `"llm"` | Large language model provider. |
| `EMBEDDING` | `"embedding"` | Text embedding provider. |
| `RERANK` | `"rerank"` | Result reranking provider. |
| `VECTOR_STORE` | `"vector_store"` | Vector store provider. |
| `NOTIFICATION` | `"notification"` | Notification provider. |

### 3.2 ProviderStatus

Health status returned by a provider health check.

| Member | Value |
|--------|-------|
| `HEALTHY` | `"healthy"` |
| `DEGRADED` | `"degraded"` |
| `UNHEALTHY` | `"unhealthy"` |
| `UNKNOWN` | `"unknown"` |

### 3.3 HealthCheckResult

Pydantic model representing the result of a provider health check.

| Field | Type | Description |
|-------|------|-------------|
| `provider_name` | `str` | Name of the provider checked. |
| `status` | `ProviderStatus` | Health status. |
| `checked_at` | `datetime` | Timestamp of the check. |
| `latency_ms` | `float \| None` | Optional latency in milliseconds. |
| `message` | `str \| None` | Optional human-readable message. |
| `details` | `dict[str, Any]` | Optional additional details. |

### 3.4 CallResult

Pydantic model representing the result of a provider method call, including audit and cost metadata.

| Field | Type | Description |
|-------|------|-------------|
| `provider_name` | `str` | Provider name. |
| `provider_version` | `str` | Provider version. |
| `success` | `bool` | Whether the call succeeded. |
| `data` | `Any` | Returned data (if any). |
| `error` | `str \| None` | Error message (if any). |
| `fetched_at` | `datetime` | Timestamp when the call was made. |
| `available_at` | `datetime \| None` | Optional availability timestamp. |
| `response_hash` | `str \| None` | Hash of the response for audit deduplication. |
| `cost` | `float` | Cost of the call. |
| `latency_ms` | `float \| None` | Latency in milliseconds. |
| `attempt_count` | `int` | Number of retry attempts. |
| `from_fallback` | `bool` | Whether the result came from a fallback provider. |

### 3.5 ProviderDescriptor

Immutable metadata descriptor for a provider.

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Unique provider name. |
| `version` | `str` | Provider version string. |
| `provider_type` | `ProviderType` | Capability category. |
| `capabilities` | `list[str]` | List of supported method names. |
| `secret_refs` | `list[str]` | Names of secrets required by the provider. Credentials are not stored here. |
| `config` | `dict[str, Any]` | Provider-specific configuration dictionary. |

### 3.6 BaseProvider

Abstract base class for all providers. Subclasses must implement `descriptor` and `healthcheck`.

| Member | Type | Description |
|--------|------|-------------|
| `descriptor` | `property` -> `ProviderDescriptor` | Return the immutable metadata descriptor. |
| `healthcheck()` | abstract method -> `HealthCheckResult` | Execute a health check and return the status. |

Example:

```python
from margin.core.provider import BaseProvider, ProviderDescriptor

class MyProvider(BaseProvider):
    @property
    def descriptor(self) -> ProviderDescriptor:
        return ProviderDescriptor(name="my_provider", version="1.0.0", ...)

    def healthcheck(self):
        ...
```

### 3.7 MarketDataProvider

`@runtime_checkable` protocol for A-share market data providers.

| Method | Signature | Description |
|--------|-----------|-------------|
| `get_securities` | `(as_of: datetime) -> list[dict[str, Any]]` | Return the universe of available securities as of a given date. |
| `get_bars` | `(symbols, start, end, frequency="1d") -> list[dict[str, Any]]` | Return OHLCV bars for the requested symbols and date range. |
| `get_adjustment_factors` | `(symbols, start, end) -> list[dict[str, Any]]` | Return adjustment factors for the requested symbols and date range. |
| `get_financials` | `(symbols, start, end) -> list[dict[str, Any]]` | Return financial statement indicators for the requested symbols. |
| `get_index_members` | `(index_code, as_of) -> list[dict[str, Any]]` | Return the constituents of an index as of a given date. |

### 3.8 WebSearchProvider

`@runtime_checkable` protocol for web search providers.

| Method | Signature | Description |
|--------|-----------|-------------|
| `search` | `(query: str, max_results: int = 10) -> list[dict[str, Any]]` | Execute a web search and return result records. |

---

## 4. Concrete Providers

### 4.1 AKShareProvider

Defined in `src/margin/data/providers/akshare_provider.py`.

A-share market data provider backed by AKShare. AKShare does not require an API token, but callers must respect its rate limits. Every public method returns a list of standard-format dictionaries that include timing fields such as `fetched_at` and `available_at`.

#### Configuration

| Attribute | Value |
|-----------|-------|
| Name | `akshare` |
| Version | `1.0.0` |
| Type | `ProviderType.MARKET_DATA` |
| Capabilities | `get_securities`, `get_bars`, `get_adjustment_factors`, `get_financials`, `get_index_members` |
| Secrets | none |
| Config | `{"license": "free", "limits": "尊重 akshare 频率限制"}` |

#### Module-level helpers

| Function | Signature | Description |
|----------|-----------|-------------|
| `_sz_sh_symbol` | `(raw: str) -> str` | Convert an AKShare raw symbol into the standard `<code>.<EXCHANGE>` format. |
| `_fmt_date` | `(d: datetime) -> str` | Format a datetime as `%Y%m%d` for AKShare. |
| `_market_bar_available_at` | `(trade_date: datetime) -> datetime` | Return availability timestamp for a daily bar (15:00 on trade date). |
| `_parse_optional_date` | `(value: Any) -> datetime \| None` | Parse an optional date value from `%Y-%m-%d` or `%Y%m%d`. |

#### Public methods

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `__init__` | `() -> None` | `AKShareProvider` | Initialize the provider and build its descriptor. |
| `descriptor` | property -> `ProviderDescriptor` | `ProviderDescriptor` | Return the cached provider descriptor. |
| `healthcheck` | `() -> HealthCheckResult` | `HealthCheckResult` | Check whether AKShare is reachable by fetching the A-share spot snapshot. |
| `get_securities` | `(as_of: datetime) -> list[dict[str, Any]]` | Security records | Fetch the current A-share security list and latest spot prices. |
| `get_bars` | `(symbols, start, end, frequency="1d") -> list[dict[str, Any]]` | OHLCV records | Fetch historical OHLCV bars. Supports `1d`, `1w`, `1M`. Uses qfq adjustment. |
| `get_adjustment_factors` | `(symbols, start, end) -> list[dict[str, Any]]` | Adjustment records | Fetch backward-adjusted (`hfq`) close prices as adjustment factors. |
| `get_financials` | `(symbols, start, end) -> list[dict[str, Any]]` | Financial records | Fetch balance-sheet fundamentals using `stock_balance_sheet_by_report_em`. |
| `get_index_members` | `(index_code, as_of) -> list[dict[str, Any]]` | Constituent records | Fetch index constituents via `index_stock_cons_csindex`. |

Return dictionaries include the following timing/source fields:

- `fetched_at`: when the data was retrieved.
- `available_at`: when the data can be used (15:00 for bars, announcement date for financials, `as_of` for index members).
- `source`: `"akshare"`.

### 4.2 TushareProvider

Defined in `src/margin/data/providers/tushare_provider.py`.

A-share market data provider backed by the Tushare Pro API. The Tushare token is resolved externally via `SecretManager` and injected through `configure_secrets` or `set_token`.

#### Configuration

| Attribute | Value |
|-----------|-------|
| Name | `tushare` |
| Version | `1.0.0` |
| Type | `ProviderType.MARKET_DATA` |
| Capabilities | `get_securities`, `get_bars`, `get_adjustment_factors`, `get_financials`, `get_index_members` |
| Secrets | `tushare_token` |
| Config | `{"license": "用户自行配置 token", "limits": "遵守 tushare 频率限制"}` |

#### Module-level helpers

| Function | Signature | Description |
|----------|-----------|-------------|
| `_fmt_date` | `(d: datetime) -> str` | Format a datetime as `YYYYMMDD`. |
| `_tushare_symbol` | `(symbol: str) -> str` | Convert an internal symbol to Tushare `ts_code` format (pass-through). |
| `_market_bar_available_at` | `(trade_date: datetime) -> datetime` | Return 15:00 availability for a daily bar. |
| `_next_market_open_after` | `(value: datetime) -> datetime` | Return the next calendar day's market open at 09:30. |

#### Public methods

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `__init__` | `(token: str \| None = None) -> None` | `TushareProvider` | Initialize provider. Token may be supplied or injected later. |
| `descriptor` | property -> `ProviderDescriptor` | `ProviderDescriptor` | Return provider metadata. |
| `_ensure_pro` | `() -> Any` | Tushare Pro client | Lazily initialize and return the Tushare Pro API client. |
| `set_token` | `(token: str) -> None` | `None` | Set or update the Tushare API token; resets the cached client. |
| `configure_secrets` | `(secrets: dict[str, str]) -> None` | `None` | Inject resolved secrets; uses `tushare_token` if present. |
| `healthcheck` | `() -> HealthCheckResult` | `HealthCheckResult` | Verify connectivity by calling `stock_basic`. |
| `get_securities` | `(as_of: datetime) -> list[dict[str, Any]]` | Security records | Fetch listed A-share securities via `stock_basic`. |
| `get_bars` | `(symbols, start, end, frequency="1d") -> list[dict[str, Any]]` | OHLCV records | Fetch daily bars via `daily`. Volume converted to shares; amount converted to yuan. |
| `get_adjustment_factors` | `(symbols, start, end) -> list[dict[str, Any]]` | Adjustment records | Fetch adjustment factors via `adj_factor`. |
| `get_financials` | `(symbols, start, end) -> list[dict[str, Any]]` | Financial records | Fetch financial indicators via `fina_indicator`. |
| `get_index_members` | `(index_code, as_of) -> list[dict[str, Any]]` | Constituent records | Fetch index constituent weights via `index_weight`. |

Volume and amount unit conversions in `get_bars`:

- `volume`: Tushare returns lots (`vol`); multiplied by `100.0` to produce shares.
- `amount`: Tushare returns thousands (`amount`); multiplied by `1000.0` to produce yuan.

---

## 5. Registry

Defined in `src/margin/core/registry.py`.

### 5.1 ProviderRegistry

Central registry for provider instances. Combines registration, health checks, rate limiting, retry, fallback, secret references, cost tracking, versioning, and audit logging.

#### Constructor

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(secret_manager=None, audit_logger=None) -> None` | Initialize the registry with optional `SecretManager` and `AuditLogger`. Defaults are created when omitted. |

#### Registration and discovery

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `register` | `(provider, *, rate_limiter=None, retry_config=None, cost_per_call=0.0, fallback_names=None, allow_override=False) -> None` | `None` | Register a provider instance. Injects secrets and configures rate limiter, retry, cost, and fallback chain. |
| `get` | `(name: str) -> BaseProvider` | `BaseProvider` | Retrieve a registered provider by name. |
| `list_by_type` | `(provider_type: ProviderType) -> list[str]` | Names | List registered provider names filtered by capability type. |
| `list_all` | `() -> list[str]` | Names | List all registered provider names. |

#### Secrets and health

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `resolve_secrets` | `(name: str) -> dict[str, str]` | Secret mapping | Resolve all secret references for a registered provider. |
| `healthcheck` | `(name: str) -> HealthCheckResult` | Health result | Run a health check for a single provider. |
| `healthcheck_all` | `() -> dict[str, HealthCheckResult]` | Name-to-result map | Run health checks for all registered providers. |

#### Call dispatch

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `call` | `(provider_name, method, args=(), kwargs=None, trace_id="") -> tuple[Any, CallResult]` | `(data, result)` | Call a provider method with retry, fallback, audit, and cost tracking. |
| `_call_single` | `(name, method, args, kwargs, trace_id, is_fallback) -> tuple[Any, CallResult]` | `(data, result)` | Internal single-provider call with rate limiting and retry. |
| `_inject_secrets` | `(provider: BaseProvider) -> None` | `None` | Resolve configured secret refs and inject them into providers that opt in. |

`call` behavior:

1. Builds a fallback chain from the primary provider plus configured fallbacks.
2. For each provider in the chain, invokes `_call_single`.
3. Returns the first successful `(data, CallResult)`.
4. If all providers fail, returns the last result.

### 5.2 Registry Exceptions

| Exception | Base | Raised when |
|-----------|------|-------------|
| `ProviderNotFoundError` | `KeyError` | A requested provider has not been registered. |
| `ProviderAlreadyRegisteredError` | `ValueError` | Registering a provider whose name is already taken and `allow_override=False`. |

---

## 6. Standardization

Defined in `src/margin/data/standardize.py`.

### 6.1 Symbol Utilities

#### `Exchange` enum

| Member | Value | Description |
|--------|-------|-------------|
| `SH` | `"SH"` | Shanghai Stock Exchange. |
| `SZ` | `"SZ"` | Shenzhen Stock Exchange. |

#### `normalize_symbol`

```python
def normalize_symbol(raw: str) -> str
```

Normalize various symbol formats to `<code>.<EXCHANGE>` form.

Supported input formats:

| Input format | Example | Output |
|--------------|---------|--------|
| Numeric only | `000001` / `600000` | `000001.SZ` / `600000.SH` |
| Standard | `000001.SZ` / `600000.SH` | unchanged |
| Exchange prefix | `SZ000001` / `SH600000` | `000001.SZ` / `600000.SH` |
| Lowercase exchange | `000001.sz` / `600000.sh` | `000001.SZ` / `600000.SH` |

Exchange inference rules for 6-digit numeric codes:

- Codes starting with `60`, `68`, `90`, `11`, `13` map to `.SH`.
- All other 6-digit codes map to `.SZ`.

Returns the upper-cased raw string if normalization fails.

#### `symbol_components`

```python
def symbol_components(symbol: str) -> tuple[str, str]
```

Split a standardized symbol into `(code, exchange)`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `symbol` | `str` | Standardized symbol, e.g. `000001.SZ`. |

Returns: `tuple[str, str]` where exchange is upper-cased.

Raises: `ValueError` if the symbol does not contain a dot separator.

### 6.2 DataDomain and FieldMapping

#### `DataDomain` enum

| Member | Value |
|--------|-------|
| `MARKET_BAR` | `"market_bar"` |
| `FINANCIAL` | `"financial"` |
| `SECURITY_META` | `"security_meta"` |
| `INDEX_MEMBER` | `"index_member"` |
| `ADJUSTMENT_FACTOR` | `"adjustment_factor"` |
| `CORPORATE_ACTION` | `"corporate_action"` |

#### `FieldMapping`

Pydantic model describing a mapping rule from a source field to the standard schema.

| Field | Type | Description |
|-------|------|-------------|
| `source_field` | `str` | Name of the field in the external source. |
| `target_field` | `str` | Name of the field in the standard schema. |
| `transform` | `str \| None` | Optional transform function name, e.g. `normalize_symbol`. |
| `unit_factor` | `float` | Multiplicative factor for unit conversion. Defaults to `1.0`. |

#### `FIELD_MAPPINGS`

Module-level constant providing a sample mapping for `MARKET_BAR` from Chinese field names to standard English names.

| Source field | Target field | Transform |
|--------------|--------------|-----------|
| `代码` | `symbol` | `normalize_symbol` |
| `开盘` | `open` | none |
| `收盘` | `close` | none |
| `最高` | `high` | none |
| `最低` | `low` | none |
| `成交量` | `volume` | none |
| `成交额` | `amount` | none |

### 6.3 UnitConverter

Unifies units and currency for A-share data. Default currency is CNY.

| Constant | Value |
|----------|-------|
| `CURRENCY` | `"CNY"` |

#### `convert_amount`

```python
@staticmethod
def convert_amount(value: float, source_unit: str = "yuan") -> float
```

Convert a monetary amount to yuan.

| Parameter | Type | Description |
|-----------|------|-------------|
| `value` | `float` | Raw monetary amount. |
| `source_unit` | `str` | `yuan`, `qian_yuan` (1,000), `wan_yuan` (10,000), or `yi_yuan` (100,000,000). |

#### `convert_volume`

```python
@staticmethod
def convert_volume(value: float, source_unit: str = "gu") -> float
```

Convert trading volume to shares.

| Parameter | Type | Description |
|-----------|------|-------------|
| `value` | `float` | Raw volume value. |
| `source_unit` | `str` | `gu` (shares) or `shou` (lots of 100). |

### 6.4 TimeStandardizer

Produces the five point-in-time fields: `event_at`, `published_at`, `available_at`, `fetched_at`, and `revised_at`.

#### `parse_date`

```python
@staticmethod
def parse_date(value: Any) -> datetime | None
```

Parse a value in multiple date formats into a `datetime`.

Supported formats: `%Y-%m-%d`, `%Y-%m-%d %H:%M:%S`, `%Y%m%d`, `%Y%m%d %H:%M:%S`, `%Y/%m/%d`.

Returns `None` if parsing fails.

#### `to_pit_fields`

```python
@staticmethod
def to_pit_fields(
    event_at: datetime | None = None,
    published_at: datetime | None = None,
    available_at: datetime | None = None,
    fetched_at: datetime | None = None,
    revised_at: datetime | None = None,
) -> dict[str, datetime]
```

Generate the full set of PIT fields. Missing timestamps are back-filled from `event_at` / `published_at` or the current local time.

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_at` | `datetime \| None` | Moment the event actually occurred. |
| `published_at` | `datetime \| None` | Moment the data was officially published. |
| `available_at` | `datetime \| None` | Moment the data becomes usable. |
| `fetched_at` | `datetime \| None` | Moment the data was fetched from the source. |
| `revised_at` | `datetime \| None` | Moment of the latest revision, if any. |

#### Module-level time helpers

| Function | Signature | Description |
|----------|-----------|-------------|
| `market_bar_available_at` | `(trade_date: datetime) -> datetime` | 15:00 on the trade date. |
| `next_market_open_after` | `(value: datetime) -> datetime` | Next calendar day's 09:30 market open. |

### 6.5 StandardDataEvent

Pydantic model for a standardized data event published after standardization.

| Field | Type | Description |
|-------|------|-------------|
| `domain` | `DataDomain` | Data domain of the event. |
| `symbol` | `str \| None` | Standardized symbol. |
| `data` | `dict[str, Any]` | Standardized payload. |
| `event_at` | `datetime` | Moment the event occurred. |
| `published_at` | `datetime` | Moment the data was published. |
| `available_at` | `datetime` | Moment the data becomes usable. |
| `fetched_at` | `datetime` | Moment the data was fetched. |
| `revised_at` | `datetime \| None` | Latest revision time, if any. |
| `source` | `str` | External source identifier. |
| `mapping_version` | `str` | Mapping version tag. Defaults to `"v1"`. |

### 6.6 Standardizer

Converts raw provider output into `StandardDataEvent` instances.

#### Constructor

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(mapping_version: str = "v1") -> None` | Initialize the standardizer with a mapping version tag. |

#### Standardization methods

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `standardize_bars` | `(raw_records, source) -> list[StandardDataEvent]` | Market-bar events | Standardize OHLCV records into `MARKET_BAR` events. |
| `standardize_securities` | `(raw_records, source) -> list[StandardDataEvent]` | Security-meta events | Standardize security metadata into `SECURITY_META` events. |
| `standardize_financials` | `(raw_records, source) -> list[StandardDataEvent]` | Financial events | Standardize financial report records into `FINANCIAL` events. |
| `standardize_index_members` | `(raw_records, source) -> list[StandardDataEvent]` | Index-member events | Standardize index constituent records into `INDEX_MEMBER` events. |

`standardize_bars` behavior:

- Normalizes `symbol`.
- Parses `date` as `event_at`; if `available_at` is missing, uses `market_bar_available_at(event_at)`.
- Converts `volume` and `amount` using `UnitConverter` based on optional `volume_unit` / `amount_unit` fields.

`standardize_financials` behavior:

- Parses `report_date` as `event_at` and `ann_date` as `published_at`.
- If `available_at` is missing, uses `next_market_open_after(published_at)`.
- Copies numeric metrics into `data` when present.

---

## 7. Quality

Defined in `src/margin/data/quality.py`.

### 7.1 Point-in-Time Fields

#### `PIT_FIELDS`

Tuple of point-in-time field names:

```python
PIT_FIELDS = ("event_at", "published_at", "available_at", "fetched_at", "revised_at")
```

#### `PITFieldError`

Exception raised when a required PIT field is missing or has an invalid type. Inherits from `ValueError`.

#### `validate_pit_fields`

```python
def validate_pit_fields(record: dict[str, Any] | StandardDataEvent) -> None
```

Validate that a record contains required PIT fields with correct types.

Required fields: `event_at`, `published_at`, `available_at`, `fetched_at` (must be `datetime`).
`revised_at` is optional and may be `None`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `record` | `dict[str, Any] \| StandardDataEvent` | Record to validate. |

Raises: `PITFieldError` on missing or incorrectly typed fields.

### 7.2 Anti-Lookahead Checks

#### `LookaheadError`

Exception raised when `available_at` is later than `decision_at`, indicating future data leakage.

#### `check_no_lookahead`

```python
def check_no_lookahead(
    record: dict[str, Any] | StandardDataEvent,
    decision_at: datetime,
) -> bool
```

Verify `available_at <= decision_at` to prevent future data leakage.

| Parameter | Type | Description |
|-----------|------|-------------|
| `record` | `dict[str, Any] \| StandardDataEvent` | Record containing `available_at`. |
| `decision_at` | `datetime` | Simulated decision time. |

Returns: `True` if the check passes.

Raises: `LookaheadError` if `available_at` is `None` or later than `decision_at`.

#### `filter_by_decision_at`

```python
def filter_by_decision_at(
    records: list[StandardDataEvent],
    decision_at: datetime,
) -> tuple[list[StandardDataEvent], list[StandardDataEvent]]
```

Split records into `(passed, rejected)` based on whether `available_at <= decision_at`.

| Parameter | Type | Description |
|-----------|------|-------------|
| `records` | `list[StandardDataEvent]` | Records to filter. |
| `decision_at` | `datetime` | Decision point. |

### 7.3 Data Quality Checks

#### `QualityIssueType` enum

| Member | Value |
|--------|-------|
| `MISSING_FIELD` | `"missing_field"` |
| `MISSING_VALUE` | `"missing_value"` |
| `OUTLIER` | `"outlier"` |
| `REVISION` | `"revision"` |
| `STALE_DATA` | `"stale_data"` |
| `DUPLICATE` | `"duplicate"` |
| `LOOKAHEAD` | `"lookahead"` |

#### `QualityIssue`

Pydantic model representing a single data quality issue.

| Field | Type | Description |
|-------|------|-------------|
| `issue_type` | `QualityIssueType` | Type of issue. |
| `symbol` | `str \| None` | Affected symbol. |
| `field_name` | `str \| None` | Affected field. |
| `message` | `str` | Human-readable description. |
| `severity` | `str` | `info`, `warning`, or `critical`. Defaults to `warning`. |

#### `QualityReport`

Pydantic model summarizing a data quality check.

| Field | Type | Description |
|-------|------|-------------|
| `checked_at` | `datetime` | When the report was generated. |
| `total_records` | `int` | Number of records inspected. |
| `issues` | `list[QualityIssue]` | Detected issues. |
| `passed` | `bool` | `False` if any critical issue exists. |

Properties:

| Property | Returns | Description |
|----------|---------|-------------|
| `issue_count` | `int` | Total number of issues. |
| `critical_count` | `int` | Number of critical issues. |

#### `DataQualityChecker`

Inspects `StandardDataEvent` records and produces a `QualityReport`.

Default required fields by domain:

| Domain | Required fields |
|--------|-----------------|
| `market_bar` | `open`, `close`, `high`, `low`, `volume` |
| `financial` | `roe` |
| `security_meta` | `name` |
| `index_member` | `index_code` |

##### Constructor

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(required_fields=None, stale_threshold_hours=72.0) -> None` | Initialize with domain-specific required fields and stale threshold. |

##### Public methods

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `check` | `(records: list[StandardDataEvent]) -> QualityReport` | `QualityReport` | Run quality checks on a batch of records. |

Checks performed by `check`:

- `MISSING_VALUE`: required field is `None`.
- `REVISION`: `revised_at` is set (severity `info`).
- `OUTLIER` (critical): non-positive prices or negative volume in `market_bar`.
- `STALE_DATA`: `fetched_at` is more than `stale_threshold_hours` after `available_at`.

### 7.4 Quality Events

#### `QualityEventSeverity` enum

| Member | Value |
|--------|-------|
| `INFO` | `"info"` |
| `WARNING` | `"warning"` |
| `CRITICAL` | `"critical"` |

#### `DataQualityEvent`

Pydantic model emitted downstream when anomalies are detected. Critical events can suppress high-confidence research signal output.

| Field | Type | Description |
|-------|------|-------------|
| `event_id` | `str` | Unique event identifier. |
| `severity` | `QualityEventSeverity` | Event severity. |
| `source` | `str` | Source component. |
| `domain` | `str` | Affected data domain. |
| `message` | `str` | Human-readable description. |
| `affected_symbols` | `list[str]` | Impacted symbols. |
| `issue_count` | `int` | Number of underlying quality issues. |
| `emitted_at` | `datetime` | Timestamp when emitted. |

Properties:

| Property | Returns | Description |
|----------|---------|-------------|
| `should_suppress_research` | `bool` | `True` if severity is `CRITICAL`. |

#### `QualityEventEmitter`

Generates and tracks `DataQualityEvent` instances.

##### Constructor

| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `() -> None` | Initialize with empty event history. |

##### Public methods

| Method | Signature | Returns | Description |
|--------|-----------|---------|-------------|
| `emit_from_report` | `(report, source, domain) -> DataQualityEvent \| None` | Event or `None` | Create a quality event from a `QualityReport`. Returns `None` if the report has no issues. |
| `emit_custom` | `(severity, source, domain, message, affected_symbols=None) -> DataQualityEvent` | Event | Emit a custom data quality event. |

##### Properties

| Property | Returns | Description |
|----------|---------|-------------|
| `events` | `list[DataQualityEvent]` | Copy of all emitted events. |
| `has_critical` | `bool` | Whether any emitted event is critical. |

`emit_from_report` severity selection:

- `CRITICAL` if any critical issue exists.
- `WARNING` if any warning issue exists (and no critical issues).
- `INFO` otherwise.

---

## 8. Cross-Module Usage Notes

### Typical data flow

1. A provider instance (`AKShareProvider` or `TushareProvider`) is created.
2. The provider is registered with `ProviderRegistry`, which injects secrets and configures resilience policies.
3. Downstream code calls `registry.call("akshare", "get_bars", args=([...], start, end))`.
4. The returned raw records are passed to `Standardizer` to produce `StandardDataEvent` objects.
5. `validate_pit_fields` and `check_no_lookahead` ensure point-in-time correctness.
6. `DataQualityChecker.check` inspects the events and produces a `QualityReport`.
7. `QualityEventEmitter.emit_from_report` converts critical reports into `DataQualityEvent` instances that can suppress research signals.

### Secret handling

- `AKShareProvider` requires no secrets.
- `TushareProvider` declares `secret_refs=["tushare_token"]`. The registry resolves this through `SecretManager` and injects it via `configure_secrets` or `set_token`.

### Unit conventions

- Currency: CNY yuan.
- Trading volume: shares.
- Amounts: yuan.

### Symbol conventions

- Internal standard: `<code>.<EXCHANGE>` (e.g. `000001.SZ`, `600000.SH`).
- Use `normalize_symbol` when ingesting external data and `symbol_components` when splitting into code and exchange.

### Anti-future-data leakage

- Always set `available_at` conservatively. For market bars, use `market_bar_available_at` (15:00). For financial announcements, use `next_market_open_after(published_at)`.
- Before using any record in a simulation, call `check_no_lookahead(record, decision_at)` or use `filter_by_decision_at`.

### Error handling

- `ProviderRegistry.call` does not raise on retryable errors; it falls back to the next provider in the chain and returns a `CallResult` with `success=False`.
- Non-retryable errors raise `ProviderError` from the registry's internal `_call_single` method.
- Data quality issues are reported via `QualityReport` and `DataQualityEvent`, not exceptions.
