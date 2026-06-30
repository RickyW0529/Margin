# 03-filing_websearch 模块文档

本模块对应 Margin 当前实现 的 filings 获取与 web search 能力，源码位于 `src/margin/news/`。文档覆盖模块职责、文件说明、领域模型、采集、搜索、去重与合规、持久化、解析、robots 检查及跨模块使用建议。

---

## 目录

1. [模块概述与职责](#1-模块概述与职责)
2. [文件级摘要](#2-文件级摘要)
3. [领域模型](#3-领域模型)
4. [采集层](#4-采集层)
5. [Web 搜索](#5-web-搜索)
6. [去重与合规评分](#6-去重与合规评分)
7. [仓库与 Outbox](#7-仓库与-outbox)
8. [结构化解析](#8-结构化解析)
9. [Robots 检查](#9-robots-检查)
10. [跨模块使用说明](#10-跨模块使用说明)

---

## 1. 模块概述与职责

`src/margin/news` 负责在向量索引与研究流水线之前，获取并暂存新闻、公告与监管文件。核心职责包括：

- **源管理**：注册数据源（交易所、IR、媒体、WebSearch 等）并维护其可信度等级。
- **发现与增量采集**：通过交易所公告连接器发现 URL，使用 `IncrementalAcquisitionRunner` 进行断点续传式采集。
- **v0.2 目标队列**：`NewsTargetQueue` 在外部调用前完整持久化每日量化研究目标；批次大小只限制吞吐，不裁剪公司覆盖范围。
- **v0.2 Refresh Run**：`news_refresh_runs` / `news_refresh_targets` 记录 target 完整性、优先级、claim、retry/backoff、partial/final 失败和对账状态。
- **v0.3 Agentic News Acquisition**：从量化 PASS 结果读取股票目标，并从公司池补齐公司名和行业上下文；使用 LLM 生成/审核搜索关键词、提炼/审核文章 finding、汇总 security brief；关键词聚焦年报、季报、业绩预告/快报、业绩说明会、公告和权威文字新闻，禁止行情、股价、走势、报价、目标价、评级、股吧和技术分析类查询；真实搜索、下载、合规、快照和 DocumentEvent 仍走受控 WebSearch 链路；支持 API 幂等键、按 target 的有界并发处理和 target 级 `NewsAgentTask` 审计。
- **下载与快照**：使用 `Downloader` + `SnapshotStore` 下载原始内容并保存不可变快照。
- **格式检测与解析**：支持 HTML、PDF、DOCX、XLSX、JSON、CSV、XML、纯文本；WebSearch 原文验证后通过共享 `margin.documents` 流水线统一转为 Markdown，再执行 Review / Repair / Verifier / Slimming，输出 final Markdown、JSON 和 RAG chunks；RAG chunking 会对单个超长段落/表格 block 做二次切分，保证不超过 `max_chunk_chars` 后再进入 embedding；PDF 默认启用 RapidOCR，OCR 后端固定为 `onnxruntime`；非多模态 verifier 自动跳过截图校验。
- **证券映射**：从标题与正文中提取标准化证券代码。
- **Web 搜索**：通过可插拔 `WebSearchProvider` 调用第三方搜索 API，对结果进行合规边界检查与原内容验证。
- **Materiality 与 Context Bundle**：`DocumentMaterialityService` 输出确定性相关度/重要度/新颖度评分；`NewsContextBundleBuilder` 把已完成文档和未完成 target 语义一起交给下游 RAG/AI。
- **去重与质量评分**：URL、内容哈希、标题-日期、SimHash、向量相似度、转载链检测，并计算 L1-L5 来源等级与质量分。
- **持久化与 Outbox**：使用 `NewsRepository` 将快照、事件、查询记录、重复决策、转载边写入 PostgreSQL，并通过事务性 Outbox 投递给下游索引队列。
- **合规边界**：robots.txt 检查、禁止绕过登录墙/付费墙、401/403 拒绝、原内容可访问性验证。

---

## 2. 文件级摘要

| 文件路径 | 说明 |
| --- | --- |
| `src/margin/news/__init__.py` | 包入口，导出公共 API（采集、搜索、去重、模型等）。 |
| `src/margin/news/models.py` | 领域模型：`SourceLevel`、`DocumentStatus`、`RawSnapshot`、`DocumentEvent`、`SourceDescriptor`、v0.2 refresh target/context DTO 及工厂函数。 |
| `src/margin/news/target_queue.py` | v0.2 目标队列：完整 enqueue、幂等 target、批次 claim、retry/backoff、终态对账。 |
| `src/margin/news/query_templates.py` | v0.2/v0.3 WebSearch 查询模板：版本化 query 生成、template hash、目标 dedupe key 关联；fallback query 优先官方年报/季报/业绩公告。 |
| `src/margin/news/agentic_models.py` | v0.3 agentic acquisition 领域模型：run、task、search plan、article finding、security brief。 |
| `src/margin/news/quant_targets.py` | v0.3 量化结果到 news target 的 scoped 读取器；默认只返回 PASS，显式开关包含 NEAR_THRESHOLD；当量化 `factor_details` 缺 name/industry 时回查最新 included company-pool member。 |
| `src/margin/news/agentic_prompts.py` | v0.3 关键词、文章提炼、写作 review 和 brief 的结构化 prompt 与 JSON schema；关键词 prompt 明确禁止股价走势、目标价、评级、研报等交易/行情查询。 |
| `src/margin/news/keyword_workflow.py` | v0.3 关键词 writer/review 两轮循环；LLM review 后还有本地 guardrail，拦截错公司、缺 ticker、缺事件词和交易/行情词；失败后回退 `QueryTemplateFactory`。 |
| `src/margin/news/article_workflow.py` | v0.3 文章 finding 提炼/review 和 derived security brief 生成；LLM review 通过后仍执行本地 `cited_spans` 区间校验。 |
| `src/margin/news/agentic_acquisition.py` | v0.3 agentic 编排：target 读取、query plan、受控 WebSearch、finding/brief 持久化、幂等 run、按 target 有界并发和失败审计。 |
| `src/margin/news/refresh_service.py` | v0.2 target-driven WebSearch 编排：先持久化全部 target，再调用 provider，限流时 run 进入 waiting。 |
| `src/margin/news/official_sync.py` | v0.2 官方公告同步：全局 cursor 增量，只有 DocumentEvent 落库后才推进 cursor。 |
| `src/margin/news/materiality.py` | v0.2 确定性文档重要度评分：监管处罚、停复牌、重大合同、诉讼、控制权变化等规则。 |
| `src/margin/news/context_bundle.py` | v0.2 新闻上下文包：按 source/materiality/novelty/time 排序，并暴露 target 是否完整。 |
| `src/margin/news/service.py` | v0.2 API 应用服务：启动 refresh、查询 run reconciliation。 |
| `src/margin/news/discovery.py` | 增量发现模型：`DiscoveredDocument`、`DiscoveryConnector` 协议。 |
| `src/margin/news/connectors.py` | 交易所公告适配器：`SSEAnnouncementConnector`、`SZSEAnnouncementConnector`。 |
| `src/margin/news/acquirer.py` | 采集核心：`SourceRegistry`、`SnapshotStore`、`Downloader`、`DocumentParser`、`SecurityMapper`、`FilingAcquirer` 及异常。 |
| `src/margin/news/websearch.py` | WebSearch：`WebSearchProvider`、`WebSearchService`、`ComplianceChecker`、`OriginalContentVerifier`、搜索结果模型。 |
| `src/margin/documents/markdown.py` | 共享 Docling Markdown 转换接口：`DocumentFormatRouter`、`DoclingMarkdownConverter`、`MarkdownConversionResult`；PDF 默认启用 RapidOCR/`onnxruntime`；供 news 获取和后续研报导入复用。 |
| `src/margin/documents/pipeline.py` | 共享文档标准化流水线：Docling 输出后执行 Review/Repair/Verifier/Slimming，最终返回 Markdown、JSON、RAG chunks；超长 block 会按行/字符二次切分并遵守 `max_chunk_chars`；多模态可用时执行 page image 校验，否则记录跳过。 |
| `src/margin/news/providers/__init__.py` | 第三方 provider 包入口（当前为空）。 |
| `src/margin/news/providers/tavily.py` | Tavily 搜索适配器：`TavilySearchAdapter`、token-safe `TavilyProviderError` 与稳定错误码。 |
| `src/margin/news/dedup.py` | 去重与评分：`Deduplicator`、`NewsProcessor`、`PersistentNewsProcessor`、`QualityScorer`、SimHash 工具。 |
| `src/margin/news/repository.py` | PostgreSQL 仓库：`NewsRepository`、`OutboxMessage`、`DedupRecord`、`RepostEdge`、v0.3 agentic run/task/plan/finding/brief 及行映射函数。 |
| `src/margin/news/db_models.py` | SQLAlchemy 行模型：快照、事件、Outbox、搜索记录、去重记录、转载边、游标、v0.2 refresh run/target、文档证券关系、materiality、context bundle。 |
| `src/margin/news/outbox.py` | Outbox 发布者/消费者：`DocumentEventPublisher`、`OutboxConsumer`。 |
| `src/margin/news/parsed.py` | 结构化解析：`ParsedBlock`、`ParsedDocument`、`StructuredDocumentParser`。 |
| `src/margin/news/robots.py` | robots.txt 合规：`RobotsRules`、`RobotsChecker`、`RobotsFetcher` 协议。 |
| `src/margin/news/scheduler.py` | 增量调度：`AcquisitionRunResult`、`IncrementalAcquisitionRunner`。 |
| `src/margin/api/routes/news.py` | News API：`POST /api/v1/news/refresh`、`GET /api/v1/news/runs/{run_id}`、`POST /api/v1/news/agentic-refresh`。 |
| `scripts/smoke_news_websearch.py` | Tavily 实网 smoke：只输出状态、结果数、query_id、snapshot 数，不输出 token/raw text。 |
| `scripts/smoke_agentic_news.py` | v0.3 agentic news smoke：只输出 run/count/outbox 计数，不输出 token、prompt 或原文。 |

---

## 3. 领域模型

### 3.1 来源等级与文档状态

`SourceLevel`（`src/margin/news/models.py`）为 IntEnum，值越小可信度越高：

| 枚举值 | 等级 | 含义 |
| --- | --- | --- |
| `L1 = 1` | 最高 | 交易所公告、监管文件、定期报告。 |
| `L2 = 2` | 高 | 官方 IR、业绩会、管理层正式指引。 |
| `L3 = 3` | 中 | 硬行业数据（价格、销量、库存、招标）。 |
| `L4 = 4` | 低 | 权威媒体、专业研究，仅可触发调研或辅助解释。 |
| `L5 = 5` | 最低 | 社交媒体、未验证来源，仅可触发调研。 |

`DocumentStatus`（`src/margin/news/models.py`）为 StrEnum：

| 枚举值 | 说明 |
| --- | --- |
| `READY` | 解析完成，可用作证据。 |
| `PARSE_FAILED` | 解析失败，但原始快照仍保留。 |

### 3.2 RawSnapshot

位置：`src/margin/news/models.py`

不可变原始下载快照元数据。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `snapshot_id` | `str` | 唯一标识。 |
| `source_url` | `str` | 来源 URL。 |
| `content_hash` | `str` | 原始内容哈希。 |
| `content_type` | `str` | 格式：`pdf`/`html`/`json`/`csv`/`text` 等。 |
| `raw_size` | `int` | 字节大小。 |
| `storage_path` | `str \| None` | 本地或远程存储路径。 |
| `downloaded_at` | `datetime` | 下载时间（UTC）。 |
| `http_status` | `int \| None` | HTTP 状态码。 |

### 3.3 DocumentEvent

位置：`src/margin/news/models.py`

归一化后的文档事件，下游向量索引队列消费该对象。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | `str` | 事件唯一 ID。 |
| `document_id` | `str` | 逻辑文档 ID。 |
| `source_url` | `str` | 原始 URL。 |
| `source_name` | `str` | 来源名称。 |
| `source_level` | `SourceLevel` | 来源可信度等级。 |
| `title` | `str` | 标题。 |
| `content` | `str \| None` | 正文。 |
| `content_hash` | `str` | 归一化内容哈希。 |
| `snapshot_id` | `str \| None` | 关联原始快照 ID。 |
| `snapshot_hash` | `str \| None` | 原始快照哈希。 |
| `symbols` | `tuple[str, ...]` | 提及的证券代码。 |
| `doc_type` | `str` | 文档类型：`filing`/`news`/`report`/`ir`/`industry`/`user_file`。 |
| `published_at` | `datetime` | 官方发布时间（UTC）。 |
| `available_at` | `datetime` | 系统可获取时间（UTC）。 |
| `retrieved_at` | `datetime` | 系统抓取时间（UTC）。 |
| `processing_status` | `DocumentStatus` | 处理状态。 |
| `processing_error` | `str \| None` | 处理错误信息。 |
| `is_original` | `bool` | 是否为原创（非重复）事件。 |
| `duplicate_of` | `str \| None` | 指向标准事件 ID。 |

**属性**

| 属性 | 返回类型 | 说明 |
| --- | --- | --- |
| `can_change_research_state` | `bool` | 当状态为 `READY` 且 `source_level <= L3` 时返回 `True`。 |

### 3.4 SourceDescriptor

位置：`src/margin/news/models.py`

注册来源时使用的描述符。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | `str` | 唯一名称。 |
| `source_type` | `str` | 类型：`exchange`/`ir`/`media`/`rss`/`websearch`/`user`。 |
| `default_level` | `SourceLevel` | 默认可信度。 |
| `url_pattern` | `str \| None` | URL 模式或基地址。 |
| `requires_auth` | `bool` | 是否需要认证。 |
| `rate_limit_per_min` | `int` | 每分钟请求上限，默认 60。 |
| `config` | `dict[str, Any]` | 来源专属配置。 |

### 3.5 发现与解析模型

**DiscoveredDocument**（`src/margin/news/discovery.py`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `external_id` | `str` | 外部 ID。 |
| `title` | `str` | 标题。 |
| `source_url` | `str` | 下载 URL。 |
| `published_at` | `datetime` | 发布时间（自动转 UTC）。 |
| `cursor` | `str \| None` | 下一页游标。 |
| `metadata` | `dict[str, str]` | 附加元数据。 |

**ParsedBlock**（`src/margin/news/parsed.py`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `block_id` | `str` | 块 ID。 |
| `block_type` | `Literal[...]` | `heading`/`paragraph`/`table_row`/`page`/`json_row`/`text`。 |
| `text` | `str` | 文本内容。 |
| `page` | `int \| None` | 页码。 |
| `section` | `str \| None` | 所属章节。 |
| `paragraph_index` | `int \| None` | 段落索引。 |
| `table_id` / `row_id` | `str \| None` | 表/行标识。 |
| `quote_span` | `tuple[int, int] \| None` | 原文字符区间。 |

**ParsedDocument**（`src/margin/news/parsed.py`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `document_id` | `str` | 文档 ID。 |
| `source_url` | `str \| None` | 来源 URL。 |
| `title` | `str \| None` | 标题。 |
| `blocks` | `tuple[ParsedBlock, ...]` | 有序块列表。 |
| `parse_status` | `str` | `ready` 或 `failed`。 |
| `parse_error` | `str \| None` | 错误信息。 |

### 3.6 Web 搜索模型

**SearchResult**（`src/margin/news/websearch.py`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `url` | `str` | 结果 URL。 |
| `title` | `str` | 结果标题。 |
| `snippet` | `str` | 摘要。 |
| `source_level` | `SourceLevel` | 默认 `L4`；WebSearch 质量策略会把交易所、巨潮、监管等官方域名提升为 `L1`。 |
| `has_accessible_original` | `bool` | 是否有可访问原内容。 |
| `content_hash` | `str \| None` | 原内容快照哈希。 |
| `snapshot_id` | `str \| None` | 快照 ID。 |

**SearchQueryRecord**（`src/margin/news/websearch.py`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `query_id` | `str` | 查询唯一 ID。 |
| `query` | `str` | 查询字符串。 |
| `results` | `tuple[SearchResult, ...]` | 结果列表。 |
| `searched_at` | `datetime` | 查询时间（UTC）。 |
| `api_provider` | `str` | API 提供者名称。 |
| `result_count` | `int` | 结果数量。 |

**VerifiedContent**（`src/margin/news/websearch.py`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `result` | `SearchResult` | 验证后的结果（含快照信息）。 |
| `snapshot` | `RawSnapshot` | 原始快照。 |
| `title` | `str` | 解析出的标题。 |
| `content` | `str` | 解析出的正文。 |

### 3.7 去重与仓库领域对象

**DedupResult**（`src/margin/news/dedup.py`）

| 字段/属性 | 类型 | 说明 |
| --- | --- | --- |
| `unique_events` | `list[DocumentEvent]` | 通过去重的事件。 |
| `duplicate_count` | `int` | 重复数量。 |
| `duplicates` | `list[dict[str, Any]]` | 重复元数据（含 `reason`、`duplicate_of`）。 |
| `total_count` | `int`（属性） | `len(unique_events) + duplicate_count`。 |

**QualityScore**（`src/margin/news/dedup.py`）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `event_id` | `str` | 事件 ID。 |
| `source_level` | `SourceLevel` | 来源等级。 |
| `completeness` | `float` | 内容完整度 [0,1]。 |
| `timeliness` | `float` | 时效性 [0,1]。 |
| `uniqueness` | `float` | 唯一性 [0,1]。 |
| `authority` | `float` | 权威性 [0,1]。 |
| `total_score` | `float` | 加权总分。 |

**OutboxMessage / DedupRecord / RepostEdge**（`src/margin/news/repository.py`）

| 模型 | 关键字段 | 说明 |
| --- | --- | --- |
| `OutboxMessage` | `outbox_id`, `event_id`, `topic`, `attempts` | 被 worker 认领的消息。 |
| `DedupRecord` | `duplicate_event_id`, `canonical_event_id`, `reason`, `similarity_score`, `created_at` | 重复决策记录。 |
| `RepostEdge` | `parent_event_id`, `child_event_id`, `reason`, `created_at` | 转载链边。 |

### 3.8 工厂函数与工具函数

| 函数 | 位置 | 签名 | 说明 |
| --- | --- | --- | --- |
| `utc_now` | `models.py` | `() -> datetime` | 返回 UTC 当前时间。 |
| `ensure_utc` | `models.py` | `(datetime) -> datetime` | 将 naive 时间视为 UTC 并统一为 UTC。 |
| `compute_content_hash` | `models.py` | `(str \| bytes) -> str` | 计算 `sha256:` 前缀的内容哈希。 |
| `make_document_event` | `models.py` | 见源码 | 自动生成 `event_id`、`document_id` 与 `content_hash`，构造 `DocumentEvent`。 |

### 3.9 v0.3 Agentic acquisition 模型

位置：`src/margin/news/agentic_models.py`

| 模型 | 说明 |
| --- | --- |
| `NewsAgentRun` | 一次 agentic news acquisition run，记录 scope、quant run、decision_at、状态、target 数和配置 hash；API 幂等键会生成稳定 run_id 并复用已存在 run。 |
| `NewsAgentTask` | 单个 LLM/deterministic/target pipeline 节点任务审计，保存 prompt/schema/request/response hash、target payload 和错误信息。 |
| `NewsSearchPlan` | 每只股票审核后的搜索计划；`fallback_used=True` 表示 LLM review 未通过后使用 deterministic 模板。 |
| `NewsArticleFinding` | 从已落库 DocumentEvent 提炼出的事件级 finding，必须反链 `event_id` 和 `source_url`。 |
| `NewsSecurityBrief` | 每只股票的 derived news brief，反链 finding 与 source event；默认 `trust_level=derived_low_trust`。 |

`SQLAlchemyQuantNewsTargetRepository` 默认只读取 `screening_status=pass` 的量化结果；`include_near_threshold=True` 时才包含 `near_threshold`。量化结果的 `factor_details.name` / `industry_terms` 缺失时，会按 `security_id` 回查最新 included `company_pool_members`，避免关键词 agent 收到只有股票代码的目标。

---

## 4. 采集层

源码主要位于 `src/margin/news/acquirer.py`、`src/margin/news/connectors.py`、`src/margin/news/scheduler.py`。

### 4.1 异常

| 异常 | 说明 |
| --- | --- |
| `DownloadError` | 下载失败时抛出。 |
| `ParseError` | 解析失败时抛出。 |
| `SourceNotFoundError` | 未注册来源时抛出。 |
| `ComplianceError` | 触碰合规边界（robots/付费墙/版权）时抛出。 |

### 4.2 BaseConnector

位置：`src/margin/news/acquirer.py`

抽象基类，定义来源连接器协议。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `source_name`（属性） | `abstract -> str` | 返回来源名称。 |
| `fetch` | `abstract (url: str, **kwargs) -> tuple[bytes, str, int]` | 抓取 URL，返回 `(原始字节, content_type, http_status)`。 |

### 4.3 HTTPConnector

位置：`src/margin/news/acquirer.py`

通用 HTTP 连接器，优先使用 `requests`，缺失时回退 `urllib`。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(name: str = "http")` | 设置连接器名称。 |
| `source_name` | `-> str` | 返回 `_name`。 |
| `fetch` | `(url: str, **kwargs) -> tuple[bytes, str, int]` | 使用 `requests.get` 获取，超时默认 30 秒。 |
| `_fetch_urllib` | `(url: str) -> tuple[bytes, str, int]` | `requests` 不可用时使用 `urllib`。 |

### 4.4 SourceRegistry

位置：`src/margin/news/acquirer.py`

管理来源描述符与连接器映射。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `()` | 初始化内部字典。 |
| `register` | `(descriptor: SourceDescriptor, connector: BaseConnector \| None = None)` | 注册来源及可选连接器。 |
| `get` | `(name: str) -> SourceDescriptor` | 按名称返回描述符；不存在抛 `SourceNotFoundError`。 |
| `get_connector` | `(name: str) -> BaseConnector \| None` | 返回已注册连接器。 |
| `list_sources` | `() -> list[str]` | 返回所有来源名称。 |
| `list_by_type` | `(source_type: str) -> list[str]` | 按类型过滤来源名称。 |

### 4.5 SnapshotStore

位置：`src/margin/news/acquirer.py`

本地文件系统不可变快照存储。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(base_dir: Path \| None = None)` | 默认目录为 `.margin/snapshots`，不存在则创建。 |
| `save` | `(source_url: str, content: bytes, content_type: str, http_status: int \| None = None) -> RawSnapshot` | 保存内容并返回快照元数据。 |
| `read` | `(snapshot_id: str, content_type: str) -> bytes \| None` | 按 ID 与扩展名读取原始字节。 |
| `read_snapshot` | `(snapshot: RawSnapshot) -> bytes \| None` | 通过快照对象读取。 |
| `delete` | `(snapshot: RawSnapshot) -> None` | 删除快照文件。 |
| `_detect_extension` | `(content_type: str) -> str` | 将 Content-Type 映射为 `pdf`/`html`/`json`/`csv`/`xml`/`txt`。 |

### 4.6 Downloader

位置：`src/margin/news/acquirer.py`

通过连接器抓取内容并写入快照存储。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(registry: SourceRegistry, snapshot_store: SnapshotStore)` | 注入注册表与快照存储。 |
| `download` | `(source_name: str, url: str, **kwargs) -> RawSnapshot` | 获取连接器、执行 `fetch`、检查 HTTP 状态、保存快照。401/403 抛 `ComplianceError`；非 2xx/空内容抛 `DownloadError`。 |

### 4.7 DocumentParser

位置：`src/margin/news/acquirer.py`

根据 `content_type` 分发解析逻辑。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `parse` | `(snapshot: RawSnapshot, content: bytes \| None = None) -> dict[str, Any]` | 按 `content_type` 分发到 `_parse_html`/`_parse_pdf`/`_parse_structured`/`_parse_text`。 |
| `_parse_html` | 静态方法，见源码 | 提取 `<title>` 与 `<body>` 可见文本，内容上限 50,000 字符。 |
| `_parse_pdf` | 静态方法，见源码 | 使用 `pymupdf` 提取文本；库缺失时返回 `parse_note`。 |
| `_parse_structured` | 静态方法，见源码 | 解析 JSON，失败时回退为纯文本。 |
| `_parse_text` | 静态方法，见源码 | 纯文本解析，取首行作为标题。 |
| `_extract_html_title` | 静态方法，`(html: str) -> str` | 提取 `<title>` 标签内容。 |

### 4.8 SecurityMapper

位置：`src/margin/news/acquirer.py`

从标题与正文中识别并标准化证券代码。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `map_symbols` | `(title: str, content: str \| None = None) -> list[str]` | 按 `CODE_PATTERNS` 匹配并调用 `margin.data.standardize.normalize_symbol`，返回排序后的标准化代码。 |

匹配模式示例：`\b(\d{6})\.SZ\b`、`\bSZ(\d{6})\b`、`\b(\d{6})\b` 等。

### 4.9 FilingAcquirer

位置：`src/margin/news/acquirer.py`

集成注册表、下载器、解析器、证券映射器，输出 `DocumentEvent`。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(registry, snapshot_store, parser=None, security_mapper=None)` | 组装 downloader、parser、mapper。 |
| `acquire` | `(source_name: str, url: str, title_override=None, published_at=None, **kwargs) -> DocumentEvent` | 下载 -> 快照 -> 解析 -> 证券映射 -> 构造 `DocumentEvent`；解析失败保留快照并标记 `PARSE_FAILED`。 |
| `acquire_batch` | `(source_name: str, urls: list[str], **kwargs) -> list[DocumentEvent]` | 批量采集，跳过下载失败的 URL。 |

### 4.10 SSEAnnouncementConnector

位置：`src/margin/news/connectors.py`

上交所公告发现适配器。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(*, endpoint: str, client: Any \| None = None)` | 支持注入 `httpx.Client` 以便测试。 |
| `discover` | `(cursor: str \| None, limit: int) -> list[DiscoveredDocument]` | GET 分页接口，将 `result`/`data` 映射为 `DiscoveredDocument`，metadata 含 `exchange: sse`。 |

内部函数 `_parse_datetime` 支持 `%Y-%m-%d %H:%M:%S`、`%Y-%m-%d`、`%Y/%m/%d %H:%M:%S` 及 ISO 格式，并统一为 UTC。

### 4.11 SZSEAnnouncementConnector

位置：`src/margin/news/connectors.py`

深交所公告发现适配器。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(*, endpoint: str, base_url: str = "https://disc.szse.cn", client: Any \| None = None)` | 默认基地址为深交所公告域名。 |
| `discover` | `(cursor: str \| None, limit: int) -> list[DiscoveredDocument]` | 与上交所类似，metadata 含 `exchange: szse`；相对路径会拼接 `base_url`。 |

### 4.12 IncrementalAcquisitionRunner

位置：`src/margin/news/scheduler.py`

驱动增量发现、采集、发布与游标推进。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(*, repository: NewsRepository, acquirer: Any, publisher: DocumentEventPublisher, cursor_key: str = "announcements")` | 注入仓库、采集器、发布者。 |
| `run_once` | `(source_name: str, connector: DiscoveryConnector, *, limit: int = 100) -> AcquisitionRunResult` | 读取游标 -> 发现 -> 逐个采集并持久化 -> 更新游标；返回发现/发布/失败计数。 |

---

## 5. Web 搜索

源码位于 `src/margin/news/websearch.py`，适配器位于 `src/margin/news/providers/tavily.py`。

### 5.1 WebSearchProvider

位置：`src/margin/news/websearch.py`

可插拔 WebSearch Provider，API key 由用户通过 SecretManager 提供。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(name: str = "websearch", secret_ref: str = "websearch_api_key", search_func: Any = None)` | 初始化描述符与 `search_func` 钩子。 |
| `descriptor` | `-> ProviderDescriptor` | 返回提供者元数据。 |
| `set_api_key` | `(api_key: str)` | 设置 API key。 |
| `configure_secrets` | `(secrets: dict[str, str])` | 通过 `ProviderRegistry` 标准钩子配置密钥。 |
| `api_key_configured` | `-> bool` | 是否已配置 API key。 |
| `set_search_func` | `(search_func: Any)` | 设置实际搜索函数，便于切换不同 API。 |
| `healthcheck` | `-> HealthCheckResult` | 未配置搜索函数返回 `DEGRADED`，否则 `HEALTHY`。 |
| `search` | `(query: str, max_results: int = 10, source_level: SourceLevel = SourceLevel.L4) -> SearchQueryRecord` | 调用 `search_func`，将原始结果转换为 `SearchResult` 列表并生成 `SearchQueryRecord`。 |

### 5.2 ComplianceChecker

位置：`src/margin/news/websearch.py`

WebSearch 合规边界检查。

| 属性/方法 | 签名 | 说明 |
| --- | --- | --- |
| `BLOCKED_DOMAINS` | `set[str]` | 被屏蔽域名集合，当前为空，可扩展。 |
| `PAYWALL_INDICATORS` | `list[str]` | 付费墙关键词，如 `subscribe to read`、`登录后查看`、`付费阅读`。 |
| `check_url` | `(url: str) -> None` | 解析域名并与 `BLOCKED_DOMAINS` 匹配，命中则抛 `ComplianceError`。 |
| `check_content_for_paywall` | `(content: str) -> bool` | 检测内容是否包含付费墙提示。 |
| `check_http_status` | `(status: int) -> None` | 401/403 抛 `ComplianceError`。 |

### 5.3 OriginalContentVerifier

位置：`src/margin/news/websearch.py`

验证搜索结果是否可访问、可下载、非付费墙，并保存快照；通过 `DocumentNormalizationPipeline` 将 PDF/HTML/DOCX/XLSX/CSV/JSON/Text 统一转换为 final Markdown。流水线内部先走 `DoclingMarkdownConverter`，再执行 Review/Repair/Verifier/Slimming；PDF 默认走 RapidOCR/`onnxruntime`，有多模态 verifier 时校验 page images，否则自动跳过视觉校验并继续文本验证。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(registry: SourceRegistry, snapshot_store: SnapshotStore, markdown_converter: Any \| None = None, normalization_pipeline: Any \| None = None)` | 内部构造 `Downloader`，默认使用共享 `DocumentNormalizationPipeline`；保留 `markdown_converter` 注入用于兼容和测试。 |
| `verify_and_snapshot` | `(result: SearchResult) -> VerifiedContent \| None` | 检查 URL -> 下载快照 -> 检测付费墙 -> 文档标准化流水线 -> 非空 final Markdown 则返回 `VerifiedContent`；否则返回 `None`。 |
| `verify_batch` | `(results: list[SearchResult]) -> list[VerifiedContent \| None]` | 批量验证，顺序一一对应。 |

### 5.4 WebSearchService

位置：`src/margin/news/websearch.py`

整合 Provider、合规检查、原内容验证与事件生成。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(provider: WebSearchProvider, registry: SourceRegistry, snapshot_store: SnapshotStore, repository: NewsRepository \| None = None, quality_policy: SearchResultQualityPolicy \| None = None, markdown_converter: Any \| None = None, normalization_pipeline: Any \| None = None)` | 注入各组件，可覆盖搜索结果质量策略、Markdown 转换器或完整文档标准化流水线。 |
| `search` | `(query: str, max_results: int = 10) -> SearchQueryRecord` | 直接调用 provider 搜索。 |
| `search_and_acquire` | `(query: str, max_results: int = 10, source_level: SourceLevel = SourceLevel.L4, searched_at: datetime \| None = None) -> tuple[SearchQueryRecord, list[DocumentEvent]]` | 搜索 -> 权威/官方/报告类结果过滤与重排 -> 官方域名来源等级提升为 `L1` -> 持久化查询记录 -> 原内容验证与 Markdown 转换 -> 为可访问结果生成 `DocumentEvent` -> 用验证后结果更新查询记录再持久化。 |

### 5.5 TavilySearchAdapter

位置：`src/margin/news/providers/tavily.py`

Tavily HTTP 搜索适配器。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(api_key: str \| None = None, *, client: Any \| None = None, base_url: str = "https://api.tavily.com/search", timeout: float = 30.0)` | 从参数或环境变量 `MARGIN_WEBSEARCH_API_KEY` 读取 key；构造 `ProviderDescriptor`。 |
| `descriptor` | `-> ProviderDescriptor` | 返回提供者描述符。 |
| `search` | `(query: str, max_results: int = 10) -> list[dict[str, str]]` | POST Tavily 接口，返回 `[{"url": ..., "title": ..., "snippet": ...}, ...]`；429 视为限流。 |
| `healthcheck` | `-> HealthCheckResult` | 执行一次轻量搜索，失败返回 `UNHEALTHY`。 |

---

## 6. 去重与合规评分

源码位于 `src/margin/news/dedup.py`。

### 6.1 SimHash 工具函数

| 函数 | 签名 | 说明 |
| --- | --- | --- |
| `_tokenize` | `(text: str) -> list[str]` | 英文按字母拆分、中文按单字拆分，统一小写。 |
| `_hash64` | `(token: str) -> int` | MD5 前 16 字符转 64 位整数。 |
| `compute_simhash` | `(text: str) -> int` | 计算 64 位 SimHash；无 token 返回 0。 |
| `hamming_distance` | `(a: int, b: int) -> int` | 两指纹异或后 1 的位数。 |
| `simhash_similarity` | `(a: int, b: int) -> float` | `1.0 - distance / 64.0`。 |

### 6.2 Deduplicator

位置：`src/margin/news/dedup.py`

多层去重器，检查顺序如下：

1. URL 唯一性
2. 内容哈希
3. 标题 + 发布日期
4. SimHash（Hamming 距离阈值内）
5. 向量相似度（如提供）
6. 转载链检测，保留更早/更权威来源

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(simhash_threshold: int = 3, title_similarity_threshold: float = 0.85, vector_similarity_func: Callable \| None = None, vector_similarity_threshold: float = 0.92)` | 配置阈值。 |
| `seed` | `(events: list[DocumentEvent]) -> None` | 用已有标准事件初始化内存状态。 |
| `find_duplicate` | `(event: DocumentEvent) -> tuple[str, DocumentEvent] \| None` | 公开探测，返回重复原因与标准事件。 |
| `record_event` | `(event: DocumentEvent) -> None` | 将事件记录为已见标准事件。 |
| `deduplicate` | `(events: list[DocumentEvent]) -> DedupResult` | 按 `(source_level, published_at)` 排序后逐条去重，输出 `DedupResult`。 |
| `_check_duplicate` | `(event: DocumentEvent) -> tuple[str, DocumentEvent] \| None` | 内部实现，依次检查 URL、哈希、标题日期、SimHash、向量相似度。 |
| `_record_seen` | `(event: DocumentEvent) -> None` | 把唯一事件加入各索引。 |

### 6.3 QualityScorer

位置：`src/margin/news/dedup.py`

按来源等级、内容完整度、时效性、唯一性计算质量分。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(timeliness_decay_days: float = 30.0)` | 设置时效性衰减天数。 |
| `score` | `(event: DocumentEvent) -> QualityScore` | 计算单事件质量分。权威性：L1=1.0、L2=0.8、L3=0.6、L4=0.4、L5=0.2；完整度：正文>100 字符 1.0；时效性：按发布时间线性衰减；唯一性：原创 1.0 / 重复 0.3。总分权重：authority 0.40、completeness 0.25、timeliness 0.20、uniqueness 0.15。 |
| `score_batch` | `(events: list[DocumentEvent]) -> list[QualityScore]` | 批量评分，保持顺序。 |

### 6.4 NewsProcessor

位置：`src/margin/news/dedup.py`

内存中的去重与评分组合器。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(deduplicator: Deduplicator \| None = None, quality_scorer: QualityScorer \| None = None)` | 默认构造新实例。 |
| `process` | `(events: list[DocumentEvent]) -> DedupResult` | 去重。 |
| `score` | `(event: DocumentEvent) -> QualityScore` | 单事件评分。 |
| `score_batch` | `(events: list[DocumentEvent]) -> list[QualityScore]` | 批量评分。 |
| `process_and_score` | `(events: list[DocumentEvent]) -> tuple[DedupResult, list[QualityScore]]` | 去重后对唯一事件评分。 |
| `filter_by_level` | `(events: list[DocumentEvent], min_level=L1, max_level=L3) -> list[DocumentEvent]` | 按来源等级过滤，默认保留 L1-L3。 |

### 6.5 PersistentNewsProcessor

位置：`src/margin/news/dedup.py`

与持久化仓库结合的去重处理器。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(repository: NewsRepository, *, simhash_threshold=3, vector_similarity_func=None, vector_similarity_threshold=0.92, quality_scorer=None)` | 注入仓库与阈值。 |
| `process` | `(events: list[DocumentEvent]) -> DedupResult` | 从仓库加载已有标准事件作为种子，逐条判断；唯一事件以 `publishable=True` 持久化，重复事件写入 `DedupRecord` 与 `RepostEdge`。 |
| `score` | `(event: DocumentEvent) -> QualityScore` | 调用内部 `QualityScorer` 评分。 |

---

## 7. 仓库与 Outbox

源码位于 `src/margin/news/repository.py`、`src/margin/news/outbox.py`。

### 7.1 NewsRepository

位置：`src/margin/news/repository.py`

SQLAlchemy 持久化边界，所有公共方法自行管理会话生命周期。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(session_factory: Callable[[], Session])` | 注入返回 SQLAlchemy `Session` 的工厂。 |
| `upsert_cursor` | `(source_name: str, cursor_key: str, cursor_value: str) -> None` | 插入或更新增量游标。 |
| `get_cursor` | `(source_name: str, cursor_key: str) -> str \| None` | 读取游标。 |
| `add_snapshot` | `(snapshot: RawSnapshot) -> None` | 幂等地写入快照元数据。 |
| `get_snapshot` | `(snapshot_id: str) -> RawSnapshot \| None` | 读取快照元数据。 |
| `add_document_event` | `(event: DocumentEvent, *, publishable: bool = True, topic: str = "vector_index") -> None` | 写入事件；若 `publishable=True` 且状态 `READY`，则写入 Outbox。 |
| `get_document_event` | `(event_id: str) -> DocumentEvent \| None` | 按 ID 读取事件。 |
| `list_unique_events` | `() -> list[DocumentEvent]` | 返回未被标记为重复的事件，按来源等级与发布时间排序。 |
| `claim_outbox` | `(topic: str, limit: int = 50) -> list[OutboxMessage]` | 使用 `SELECT ... FOR UPDATE SKIP LOCKED` 认领待处理消息。 |
| `mark_outbox_delivered` | `(outbox_id: int) -> None` | 标记消息已投递。 |
| `mark_outbox_failed` | `(outbox_id: int, error: str) -> None` | 标记消息失败并记录错误。 |
| `add_search_record` | `(record: SearchQueryRecord) -> None` | 幂等地写入搜索查询与结果行。 |
| `get_search_record` | `(query_id: str) -> SearchQueryRecord \| None` | 读取查询记录及排序后的结果。 |
| `add_dedup_record` | `(*, duplicate_event_id: str, canonical_event_id: str, reason: str, similarity_score: float \| None = None) -> None` | 写入重复决策。 |
| `get_dedup_record` | `(duplicate_event_id: str) -> DedupRecord \| None` | 读取重复决策。 |
| `add_repost_edge` | `(*, parent_event_id: str, child_event_id: str, reason: str) -> None` | 写入转载边。 |
| `list_repost_chain` | `(parent_event_id: str) -> list[RepostEdge]` | 列出某父事件下的直接转载边。 |
| `add_news_agent_run` / `get_news_agent_run` | `(NewsAgentRun)` / `(run_id)` | 持久化和读取 v0.3 agentic run。 |
| `add_news_agent_task` / `list_news_agent_tasks` | `(NewsAgentTask)` / `(run_id)` | 持久化和读取 v0.3 agentic 任务审计，包括 target pipeline 的 running/approved/failed_final 状态。 |
| `add_news_search_plan` / `list_news_search_plans` | `(NewsSearchPlan)` / `(run_id)` | 持久化和读取 reviewed/fallback query plan。 |
| `add_news_article_finding` / `list_news_article_findings` | `(NewsArticleFinding)` / `(run_id, security_id=None)` | 持久化和读取文章 finding。 |
| `add_news_security_brief` / `list_news_security_briefs` | `(NewsSecurityBrief)` / `(run_id)` | 持久化和读取 derived security brief。 |
| `list_document_events_by_ids` | `(event_ids: list[str]) -> list[DocumentEvent]` | 按 event ID 批量读取已落库文档事件。 |

v0.3 新增持久化表：

- `news_agent_runs`
- `news_agent_tasks`
- `news_search_plans`
- `news_article_findings`
- `news_security_briefs`

### 7.2 DocumentEventPublisher

位置：`src/margin/news/outbox.py`

事务性事件发布门面。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(repository: NewsRepository)` | 注入仓库。 |
| `persist_pending` | `(event: DocumentEvent) -> None` | 调用 `add_document_event(event, publishable=True)`。 |

### 7.3 OutboxConsumer

位置：`src/margin/news/outbox.py`

Outbox 消费门面。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__init__` | `(repository: NewsRepository)` | 注入仓库。 |
| `claim_batch` | `(topic: str, limit: int = 50) -> list[OutboxMessage]` | 认领一批消息。 |
| `mark_delivered` | `(outbox_id: int) -> None` | 标记已投递。 |
| `mark_failed` | `(outbox_id: int, error: str) -> None` | 标记失败。 |

---

## 8. 结构化解析

源码位于 `src/margin/news/parsed.py`。

### 8.1 StructuredDocumentParser

按格式输出带定位信息的 `ParsedBlock`。

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `parse_html` | `(html: str \| bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | 使用 BeautifulSoup 提取标题、`h1/h2/h3/p/li`，生成 `heading`/`paragraph` 块。 |
| `parse_csv` | `(content: str \| bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | 每行生成一个 `table_row` 块。 |
| `parse_json` | `(content: str \| bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | 对象或数组每项生成 `json_row` 块。 |
| `parse_pdf` | `(content: bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | 使用 `pypdf.PdfReader` 每页生成 `page` 块。 |
| `parse_text` | `(content: str \| bytes, *, document_id: str, source_url: str \| None = None) -> ParsedDocument` | 按空行分paragraph生成 `paragraph` 块。 |

---

## 9. Robots 检查

源码位于 `src/margin/news/robots.py`。

### 9.1 RobotsFetcher 协议与默认实现

| 名称 | 签名 | 说明 |
| --- | --- | --- |
| `RobotsFetcher` | `__call__(url: str) -> tuple[int, bytes]` | 获取 robots.txt 的可调用协议。 |
| `_default_fetcher` | `(url: str) -> tuple[int, bytes]` | 使用 `httpx.get`（follow redirects，10 秒超时）。 |

### 9.2 RobotsRules

位置：`src/margin/news/robots.py`

解析后的 Allow/Disallow 规则。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `allows` | `list[str]` | Allow 路径前缀。 |
| `disallows` | `list[str]` | Disallow 路径前缀。 |

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `can_fetch` | `(path: str) -> bool` | 应用最长前缀优先的 Allow/Disallow 语义。 |

### 9.3 RobotsChecker

位置：`src/margin/news/robots.py`

带缓存的 robots.txt 检查器。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `fetcher` | `RobotsFetcher` | robots.txt 获取器，默认 `_default_fetcher`。 |
| `user_agent` | `str` | 当前仅匹配通配符 `*`，默认 `"MarginBot/0.1"`。 |
| `_cache` | `dict[str, RobotsRules]` | 按 origin 缓存的规则。 |

| 方法 | 签名 | 说明 |
| --- | --- | --- |
| `__post_init__` | `() -> None` | 初始化缓存。 |
| `allowed` | `(url: str) -> bool` | 返回 URL 是否可抓取；非 http/https 返回 `False`；robots.txt 不可达时按 allow-all 处理。 |
| `assert_allowed` | `(url: str) -> None` | 不允许时抛 `ComplianceError`。 |
| `_parser_for` | `(scheme: str, netloc: str) -> RobotsRules` | 获取、解析并缓存某 origin 的 robots.txt。 |
| `_parse_rules` | `(content: str) -> RobotsRules` | 解析 `User-agent: *` 下的 Allow/Disallow 规则，忽略注释。 |

---

## 10. 跨模块使用说明

### 10.1 标准采集流水线

```text
DiscoveryConnector.discover()
        |
        v
IncrementalAcquisitionRunner.run_once()
        |
        v
FilingAcquirer.acquire()
        |
        +-- Downloader.download()  -> SnapshotStore.save()
        +-- DocumentParser.parse()
        +-- SecurityMapper.map_symbols()
        |
        v
DocumentEventPublisher.persist_pending()
        |
        v
NewsRepository.add_document_event()  -> DocumentOutboxRow
```

该流水线保证：每次增量运行从上次游标继续；失败单条跳过；解析失败仍保留原始快照；ready 事件进入 Outbox 等待向量索引 worker 消费。

### 10.2 WebSearch 流水线

```text
WebSearchProvider.search()
        |
        v
WebSearchService.search_and_acquire()
        |
        +-- NewsRepository.add_search_record()
        +-- OriginalContentVerifier.verify_batch()
                +-- ComplianceChecker.check_url()
                +-- Downloader.download()
                +-- ComplianceChecker.check_content_for_paywall()
                +-- DoclingMarkdownConverter.convert()
        |
        v
make_document_event() -> DocumentEvent
        |
        v
NewsRepository.add_search_record(audited)
```

只有转换出非空 Markdown 且未触碰付费墙的结果才会生成 `DocumentEvent`，摘要本身不可作为证据。

### 10.3 去重流水线

```text
批量 DocumentEvent
        |
        v
PersistentNewsProcessor.process()
        |
        +-- 从 NewsRepository.list_unique_events() 加载种子
        +-- Deduplicator.find_duplicate()
        |
        v
唯一事件 -> NewsRepository.add_document_event(publishable=True)
重复事件 -> NewsRepository.add_document_event(publishable=False)
              -> NewsRepository.add_dedup_record()
              -> NewsRepository.add_repost_edge()
```

### 10.4 Agentic news acquisition 流水线

```text
SQLAlchemyQuantNewsTargetRepository.list_targets(PASS only by default)
        |
        +-- company_pool_members backfill for name / industry
        |
        v
AgenticNewsAcquisitionService.run_for_quant_run()
        |
        +-- idempotency key -> stable run_id / existing run reuse
        +-- bounded target parallelism controlled by max_workers
        +-- KeywordWorkflow: writer -> review -> local guardrail -> fallback if needed
        +-- WebSearchService.search_and_acquire()
        |       +-- query/result audit
        |       +-- robots/paywall/original-content checks
        |       +-- snapshot/Docling Markdown/DocumentEvent
        |       +-- document_outbox(topic=vector_index)
        +-- ArticleWorkflow: article writer -> writing review -> local cited_span validation
        +-- ArticleWorkflow.build_brief()
        |
        v
news_agent_tasks / news_search_plans / news_article_findings / news_security_briefs
```

Agentic 层不直接写 `chunks`、`chunk_embeddings` 或任何向量表；原文索引仍由 `04-text_indexing` 的 `IndexingRunner` 消费 `document_outbox(topic=vector_index)` 完成。LLM 不能执行自由 SQL，量化目标读取由服务端 repository 完成。

Agentic news 的 provider 构造优先使用 strategy active provider；本地 smoke 环境如果没有 `MARGIN_SECRET_MASTER_KEY`，但 `.env` 已配置 LLM/WebSearch key，则回退到直接环境变量 provider。该流程不是 LangGraph run，因此 LLMService 不使用带 `ai_graph_runs` 外键的 SQL audit repository；prompt/response hash 落在 news 自身 run/plan/finding 表中。WebSearch provider 出现预算、paygo 或认证类稳定错误码时，run 状态进入 `waiting_provider` 并记录 token-safe `error_summary`，不再归为普通 `partial`。

### 10.5 来源等级语义

- L1-L3：可作为改变研究状态或持仓状态的直接证据。
- L4-L5：仅触发调研或提供辅助解释，不能单独改变研究/持仓状态。
- 该语义体现在 `DocumentEvent.can_change_research_state` 与 `NewsProcessor.filter_by_level` 中。

### 10.6 常见使用模式

#### 注册交易所来源并单条采集

```python
from margin.news.acquirer import SourceRegistry, SnapshotStore, FilingAcquirer
from margin.news.models import SourceDescriptor, SourceLevel

registry = SourceRegistry()
registry.register(
    SourceDescriptor(name="sse", source_type="exchange", default_level=SourceLevel.L1)
)
store = SnapshotStore()
acquirer = FilingAcquirer(registry, store)
event = acquirer.acquire("sse", "https://www.sse.com.cn/.../announcement.pdf")
```

#### 增量运行交易所公告

```python
from margin.news.connectors import SSEAnnouncementConnector
from margin.news.scheduler import IncrementalAcquisitionRunner
from margin.news.outbox import DocumentEventPublisher
from margin.news.repository import NewsRepository

connector = SSEAnnouncementConnector(endpoint="https://api.example.com/sse")
runner = IncrementalAcquisitionRunner(
    repository=NewsRepository(session_factory),
    acquirer=acquirer,
    publisher=DocumentEventPublisher(repository),
)
result = runner.run_once("sse", connector, limit=100)
```

#### 使用 Tavily 进行 WebSearch

```python
from margin.news.providers.tavily import TavilySearchAdapter
from margin.news.websearch import WebSearchProvider, WebSearchService
from margin.news.acquirer import SourceRegistry, SnapshotStore

tavily = TavilySearchAdapter()
provider = WebSearchProvider(search_func=tavily.search)
service = WebSearchService(provider, SourceRegistry(), SnapshotStore())
record, events = service.search_and_acquire("平安银行 公告", max_results=5)
```

#### 从量化 run 启动 agentic news acquisition

```http
POST /api/v1/news/agentic-refresh
Authorization: Bearer <admin-token>
X-CSRF-Token: <csrf-token>
Idempotency-Key: <key>

{
  "scope_version_id": "scope_v1",
  "quant_run_id": "qr_...",
  "decision_at": "2026-06-29T00:00:00Z",
  "include_near_threshold": false,
  "max_workers": 4
}
```

响应只返回 run 摘要：

```json
{
  "run_id": "nar_...",
  "status": "completed",
  "target_count": 3,
  "include_near_threshold": false
}
```

token-safe smoke：

```bash
python scripts/smoke_agentic_news.py \
  --scope-version-id scope_v1 \
  --quant-run-id qr_... \
  --decision-at 2026-06-29T00:00:00Z
```

最新本地 50 样例评测（过程文件位于被 Git 忽略的 `docs/superpowers/evals/v0.3/`）：target context `OK=50/50`，keyword `OK=50/50`；当前 Tavily 返回 HTTP 432，对应 `provider_budget_exceeded`，所以搜索结果、文章 finding、brief 和 outbox 端到端实网质量仍等待 provider 额度恢复后复测。

### 10.7 注意事项

- `SnapshotStore` 默认写入项目相对目录 `.margin/snapshots`，生产环境应替换为对象存储实现。
- `DocumentParser` 对 PDF 的解析依赖 `pymupdf`；缺失时仅保留快照，状态为 `PARSE_FAILED`。
- `ComplianceChecker` 与 `RobotsChecker` 共同防止绕过 robots.txt、登录墙、付费墙；遇到 401/403 直接拒绝。
- `NewsRepository` 每个方法内部独立开启事务，批量写入时应在外层控制会话以避免多次提交（当前实现每次方法调用提交）。
- WebSearch 结果默认等级为 L4，进入证据库前必须通过 `OriginalContentVerifier` 验证原内容可访问性。
- `NewsSecurityBrief` 是 derived summary，不是一手证据；研究结论仍必须引用原始 DocumentEvent / Evidence。
