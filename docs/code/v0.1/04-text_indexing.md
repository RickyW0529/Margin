# 04-text_indexing 模块文档

## 目录

- [1. 模块概述](#1-模块概述)
- [2. 文件级说明](#2-文件级说明)
- [3. 领域模型](#3-领域模型)
- [4. 分块器](#4-分块器)
- [5. 嵌入流水线](#5-嵌入流水线)
- [6. 持久化流水线](#6-持久化流水线)
- [7. 检索](#7-检索)
- [8. 索引运行器](#8-索引运行器)
- [9. 仓库](#9-仓库)
- [10. 跨模块使用说明](#10-跨模块使用说明)

---

## 1. 模块概述

`04-text_indexing` 对应代码包 `margin.vector`，负责把原始文档转换为可检索的向量与关键词索引。它是文档解析（module 03）与多智能体研究（module 06）之间的桥梁：

- 接收 `DocumentEvent`，按文档类型拆分 Chunk；
- 调用嵌入模型生成稠密向量；
- 维护向量索引与 BM25 关键词索引；
- 支持混合检索、重排、来源定位与审计回放。

数据流：

```text
DocumentEvent → Chunker → Chunk → EmbeddingProvider → VectorStore
                                          ↓
                                       BM25Index
                                          ↓
                              HybridRetriever / RetrievalTool
```

---

## 2. 文件级说明

| 文件 | 路径 | 职责 |
|------|------|------|
| `__init__.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/__init__.py` | 聚合导出模块公共 API。 |
| `models.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/models.py` | 定义 `Chunk`、`RetrievalResult`、`DocType` 等核心领域模型。 |
| `db_models.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/db_models.py` | SQLAlchemy ORM 表：`ChunkRow`、`ChunkEmbeddingRow`、`IndexAuditRecordRow`、`RetrievalAuditRecordRow`。 |
| `chunker.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/chunker.py` | 文档分块策略与分块器工厂。 |
| `embedding.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/embedding.py` | 嵌入 Provider、内存向量存储、BM25 索引、索引审计与 `EmbeddingPipeline`。 |
| `persistent_pipeline.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/persistent_pipeline.py` | 基于 PostgreSQL/pgvector 的持久化检索流水线封装。 |
| `retrieval.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/retrieval.py` | 混合检索、重排、检索约束与 `RetrievalTool`。 |
| `repository.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/repository.py` | `VectorRepository`，负责 Chunk、Embedding、审计记录的持久化与检索。 |
| `indexing_runner.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/indexing_runner.py` | 消费文档 Outbox，完成 Chunk 与 Embedding 的持久化索引。 |
| `providers/__init__.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/providers/__init__.py` | Provider 子包说明。 |
| `providers/openai_embedding.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/providers/openai_embedding.py` | OpenAI 兼容 `/embeddings` 嵌入 Provider。 |
| `providers/rerank.py` | `/Users/wangruiqi/PycharmProjects/Margin/src/margin/vector/providers/rerank.py` | HTTP 重排 Provider，兼容 Cohere/OpenAI 风格 `/rerank`。 |

---

## 3. 领域模型

### 3.1 `DocType`

| 枚举值 | 字符串值 | 说明 |
|--------|----------|------|
| `ANNUAL_REPORT` | `annual_report` | 年报 |
| `QUARTERLY_REPORT` | `quarterly_report` | 季报 |
| `FILING` | `filing` | 公告/监管文件 |
| `NEWS` | `news` | 新闻 |
| `IR` | `ir` | 投资者关系材料 |
| `INDUSTRY_REPORT` | `industry_report` | 行业研究报告 |
| `USER_NOTE` | `user_note` | 用户笔记 |
| `UNKNOWN` | `unknown` | 未知类型 |

### 3.2 `Chunk`

`Chunk` 是文本索引的最小单元，包含内容与完整来源定位信息。模型为冻结 Pydantic 模型。

| 字段 | 类型 | 说明 |
|------|------|------|
| `chunk_id` | `str` | 稳定 ID，由 `document_id`、`chunk_index`、`symbol` 哈希生成。 |
| `document_id` | `str` | 父文档 ID。 |
| `content` | `str` | 文本内容。 |
| `content_hash` | `str` | 内容 SHA-256 哈希。 |
| `symbol` | `str \| None` | 证券代码。 |
| `source_level` | `SourceLevel` | 来源可信度等级，默认 `L4`。 |
| `doc_type` | `DocType` | 文档类型，默认 `UNKNOWN`。 |
| `published_at` | `datetime` | 原始发布时间（UTC）。 |
| `available_at` | `datetime` | 可得时间（UTC）。 |
| `source_url` | `str \| None` | 原始来源 URL。 |
| `source_name` | `str \| None` | 来源名称。 |
| `snapshot_id` | `str \| None` | 网页快照 ID。 |
| `snapshot_hash` | `str \| None` | 快照哈希。 |
| `page` | `int \| None` | 页码。 |
| `section` | `str \| None` | 章节。 |
| `paragraph_index` | `int \| None` | 段落序号。 |
| `table_id` | `str \| None` | 表格 ID。 |
| `row_id` | `str \| None` | 表格行 ID。 |
| `quote_span` | `tuple[int, int] \| None` | 引用字符区间。 |
| `embedding` | `tuple[float, ...] \| None` | 稠密向量。 |
| `keywords` | `tuple[str, ...]` | 关键词/BM25 词项。 |
| `chunk_index` | `int` | 文档内分块序号。 |
| `total_chunks` | `int` | 文档分块总数。 |

方法：

| 方法 | 说明 |
|------|------|
| `has_locator`（property） | 当存在 `source_url` 且至少具备 page/section/paragraph_index/table_id/row_id/quote_span 之一时返回 `True`。 |

### 3.3 `RetrievalResult`

| 字段 | 类型 | 说明 |
|------|------|------|
| `chunk` | `Chunk` | 检索命中的 Chunk。 |
| `score` | `float` | 融合后的最终得分。 |
| `vector_score` | `float` | 稠密向量相似度得分。 |
| `keyword_score` | `float` | BM25 关键词得分。 |
| `time_decay` | `float` | 时间衰减得分。 |
| `source_quality` | `float` | 来源质量得分。 |
| `entity_match` | `float` | 实体匹配得分。 |
| `rank` | `int` | 最终排序名次。 |

### 3.4 工厂函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `compute_chunk_hash` | `(content: str) -> str` | 计算内容 SHA-256 哈希，前缀 `sha256:`。 |
| `make_chunk` | `(document_id, content, chunk_index=0, total_chunks=1, **kwargs) -> Chunk` | 自动生成 `chunk_id` 与 `content_hash`，构造 `Chunk`。 |

---

## 4. 分块器

### 4.1 异常与类型推断

| 函数/异常 | 说明 |
|-----------|------|
| `ChunkingError` | 分块失败时抛出的异常。 |
| `infer_doc_type(event: DocumentEvent) -> DocType` | 根据 `doc_type` 与 `title` 推断文档类型，支持中英文字段匹配。 |

### 4.2 `BaseChunker`

通用分块基类，提供段落/句子拆分与按大小合并能力。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(max_chunk_size: int = 1000, overlap: int = 100)` | 初始化最大分块长度与重叠长度。 |
| `chunk` | `(event: DocumentEvent) -> list[Chunk]` | 抽象方法，子类必须实现。 |
| `_split_paragraphs` | `(text: str) -> list[str]` | 按空行拆分段落。 |
| `_split_sentences` | `(text: str) -> list[str]` | 按中文/英文标点拆句。 |
| `_merge_to_size` | `(parts: list[str]) -> list[str]` | 合并片段至 `max_size`，保留重叠。 |
| `_split_oversized_part` | `(part: str) -> list[str]` | 对超长单一片段做滑动切分。 |
| `_make_chunks` | `(event, text_parts, doc_type, section_labels=None) -> list[Chunk]` | 生成 `Chunk` 列表并填充元数据；对每个 symbol 复制一份 Chunk。 |

### 4.3 `ReportChunker`

年报/季报分块器，按章节、表格、页面拆分。

| 方法 | 说明 |
|------|------|
| `chunk(event)` | 按章节切分内容，再对每章段落合并。 |
| `_split_by_sections(text)` | 识别第 X 章/节、数字序号、Section/Chapter 等标题，返回 `(section_label, section_text)` 列表。 |

### 4.4 `FilingChunker`

公告分块器，按事项与条款拆分。

| 方法 | 说明 |
|------|------|
| `chunk(event)` | 按事项切分内容。 |
| `_split_by_items(text)` | 识别中文数字序号、`第 N 条` 等标记，返回 `(item_label, item_text)` 列表。 |

### 4.5 `NewsChunker`

新闻分块器，保留标题、导语与正文段落。

| 方法 | 说明 |
|------|------|
| `chunk(event)` | 标题为 `title`，首段为 `lead`，其余为 `body`。 |

### 4.6 `IRChunker`

投资者关系记录分块器，按问答对拆分。

| 方法 | 说明 |
|------|------|
| `chunk(event)` | 提取 Q&A 对；无法识别时退化为段落。 |
| `_split_qa(text)` | 识别 `问/Q/答/A` 标记并配对。 |

### 4.7 `UserNoteChunker`

用户笔记分块器，按段落拆分。

| 方法 | 说明 |
|------|------|
| `chunk(event)` | 合并段落后按 `para_i` 打标。 |

### 4.8 `Chunker`

分块器入口工厂，根据 `DocType` 选择具体分块策略。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(max_chunk_size=1000, overlap=100, custom_chunkers=None)` | 可注入自定义分块器映射。 |
| `chunk` | `(event: DocumentEvent) -> list[Chunk]` | 若事件未 `READY` 返回空；否则选择对应分块器执行，失败抛出 `ChunkingError`。 |
| `_make_fallback_chunks` | `(event, doc_type) -> list[Chunk]` | 无正文时仅使用标题生成 Chunk。 |
| `chunk_batch` | `(events: list[DocumentEvent]) -> list[Chunk]` | 批量分块，单个失败跳过。 |
| `chunk_parsed` | `(parsed: ParsedDocument, event: DocumentEvent) -> list[Chunk]` | 对结构化 `ParsedDocument` 分块，保留 `quote_span` 等定位信息。 |
| `_split_block_text` | `(block: ParsedBlock) -> list[tuple[str, tuple[int, int] \| None]]` | 切分 `ParsedBlock` 文本并重新分配引用区间。 |

---

## 5. 嵌入流水线

### 5.1 `EmbeddingProvider`

可插拔嵌入 Provider；MVP 内置基于哈希的伪嵌入，仅用于测试。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(name="hash_embedding", version="1.0.0", dim=256, embed_func=None, secret_ref=None)` | 初始化 Provider。 |
| `descriptor` | property | 返回 `ProviderDescriptor`。 |
| `name` | property | Provider 名称。 |
| `version` | property | Provider 版本。 |
| `dim` | property | 向量维度。 |
| `embed` | `(text: str) -> list[float]` | 生成单条向量。 |
| `embed_batch` | `(texts: list[str]) -> list[list[float]]` | 批量生成向量（默认逐条调用）。 |
| `set_embed_func` | `(func: Callable[[str], list[float]]) -> None` | 注入真实嵌入函数。 |
| `configure_secrets` | `(secrets: dict[str, str]) -> None` | 接收解析后的凭证。 |
| `healthcheck` | `() -> HealthCheckResult` | 通过嵌入 `"healthcheck"` 检查可用性。 |
| `_hash_embed` | `(text: str) -> list[float]` | 基于 token 哈希的伪嵌入，单位长度。 |

### 5.2 `VectorStore`

内存向量存储，接口与 pgvector/Qdrant 兼容，便于后续替换。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(dim: int = 256)` | 初始化存储。 |
| `upsert` | `(chunk: Chunk, vector: list[float]) -> None` | 写入或更新 Chunk 与向量。 |
| `upsert_batch` | `(items: list[tuple[Chunk, list[float]]]) -> int` | 批量写入，维度不匹配则跳过。 |
| `search` | `(query_vector, top_k=10, filters=None) -> list[tuple[Chunk, float]]` | 按余弦相似度检索。 |
| `get` | `(chunk_id: str) -> Chunk \| None` | 按 ID 取 Chunk。 |
| `size` | property | 当前存储数量。 |
| `clear` | `() -> None` | 清空存储。 |
| `_match_filters` | `(chunk: Chunk, filters: dict) -> bool` | 元数据过滤匹配，支持 `symbol`、`source_level`、`doc_type`、`document_id` 及任意属性。 |

### 5.3 `BM25Index`

内存 BM25 关键词索引，支持中英文分词。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(k1: float = 1.5, b: float = 0.75)` | 初始化 BM25 参数。 |
| `upsert` | `(chunk: Chunk) -> None` | 索引单个 Chunk，自动更新倒排表。 |
| `upsert_batch` | `(chunks: list[Chunk]) -> int` | 批量索引。 |
| `search` | `(query: str, top_k=10, filters=None) -> list[tuple[Chunk, float]]` | BM25 检索。 |
| `size` | property | 当前文档数。 |
| `clear` | `() -> None` | 清空索引。 |
| `_tokenize` | `(text: str) -> list[str]` | 英文按单词、中文按单字分词。 |

### 5.4 `IndexAuditRecord` / `IndexAuditor`

| 类/方法 | 说明 |
|-----------|------|
| `IndexAuditRecord` | 索引操作审计记录 Pydantic 模型，含操作类型、Chunk 数、向量数、关键词数、降级标志、错误等。 |
| `IndexAuditor` | 内存审计记录器。 |
| `log_upsert(...)` | 记录写入/索引操作。 |
| `log_search(...)` | 记录检索操作。 |
| `records` | 返回所有审计记录副本。 |

### 5.5 `EmbeddingPipeline`

编排分块嵌入、向量存储、关键词索引与审计。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(embedding_provider=None, vector_store=None, bm25_index=None, auditor=None)` | 默认创建 hash Provider、内存向量存储、BM25 索引与审计器。 |
| `provider` / `vector_store` / `bm25_index` / `auditor` | property | 返回对应组件。 |
| `index_chunks` | `(chunks: list[Chunk]) -> int` | 先关键词索引，再生成向量并写入向量存储；记录审计。 |
| `vector_search` | `(query_text: str, top_k=10, filters=None) -> list[tuple[Chunk, float]]` | 嵌入查询后向量检索。 |
| `keyword_search` | `(query: str, top_k=10, filters=None) -> list[tuple[Chunk, float]]` | BM25 检索。 |

---

## 6. 持久化流水线

### 6.1 `PersistentEmbeddingPipeline`

将持久化的 `VectorRepository` 包装成与混合检索兼容的检索接口。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(*, embedding_provider, repository: VectorRepository)` | 依赖外部 Provider 与持久化仓库。 |
| `vector_search` | `(query_text: str, top_k=10, filters=None) -> list[tuple[Chunk, float]]` | 嵌入查询并调用 `repository.search_vector`。 |
| `keyword_search` | `(query: str, top_k=10, filters=None) -> list[tuple[Chunk, float]]` | 列出 Chunk 后按 token 重叠率打分。 |

辅助函数：

| 函数 | 说明 |
|------|------|
| `_tokenize(text)` | 中文单字/英文单词/数字分词。 |

---

## 7. 检索

### 7.1 `SearchConstraints`

检索约束模型。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `symbol` | `str \| None` | `None` | 证券代码。 |
| `decision_at` | `datetime \| None` | `None` | 决策时间点。 |
| `doc_types` | `tuple[str, ...] \| None` | `None` | 文档类型过滤。 |
| `prefer_official` | `bool` | `True` | 是否优先官方来源。 |
| `dedup` | `bool` | `True` | 是否去重。 |
| `require_locator` | `bool` | `True` | 是否要求具备定位信息。 |

### 7.2 `HybridWeights`

混合检索权重，默认总权重为 `1.0`。

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `vector` | `0.35` | 向量相似度权重。 |
| `keyword` | `0.25` | BM25 权重。 |
| `time_decay` | `0.15` | 时间衰减权重。 |
| `source_quality` | `0.15` | 来源质量权重。 |
| `entity_match` | `0.10` | 实体匹配权重。 |

### 7.3 `HybridRetriever`

混合检索器，融合向量、BM25、时间衰减、来源质量与实体匹配得分。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(pipeline: EmbeddingPipeline, weights=None, time_decay_days=90.0)` | 初始化。 |
| `search` | `(query: str, top_k=10, constraints=None) -> list[RetrievalResult]` | 执行混合检索，要求 `symbol` 与 `decision_at`。 |
| `_build_filters` | `(constraints) -> dict` | 构造底层 pipeline 过滤器。 |
| `_merge_and_score` | `(query, vector_results, keyword_results, constraints) -> list[RetrievalResult]` | 合并两种检索结果并计算融合分。 |
| `_time_decay` | `(chunk, decision_at) -> float` | 基于 `published_at` 的指数衰减。 |
| `_source_quality` | `(chunk) -> float` | 将 `SourceLevel` 映射为 0.2~1.0。 |
| `_entity_match` | `(chunk, constraints) -> float` | symbol 匹配得 1.0，否则 0.0。 |
| `_boost_official` | `(results) -> list[RetrievalResult]` | 对 L1-L3 官方来源加 0.05 分。 |
| `_dedup_results` | `(results) -> list[RetrievalResult]` | 按规范化内容哈希去重。 |

### 7.4 `Reranker`

结果重排器，MVP 提供基于词覆盖的 fallback。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(rerank_func=None)` | 初始化，可注入外部重排函数。 |
| `set_rerank_func` | `(func) -> None` | 注入真实重排模型。 |
| `rerank` | `(query: str, results: list[RetrievalResult], top_k=None) -> list[RetrievalResult]` | 重排并取 top_k，融合分权重 0.7，重排分 0.3。 |
| `_simple_rerank` | `(query: str, content: str) -> float` | 查询词在内容中的覆盖比例。 |

### 7.5 `RetrievalTool`

面向多智能体层的统一检索接口。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(pipeline, retriever=None, reranker=None, use_rerank=True)` | 组装混合检索与重排。 |
| `search` | `(query, symbol=None, decision_at=None, doc_types=None, top_k=10, prefer_official=True) -> list[RetrievalResult]` | 执行检索并可选重排，要求 `symbol` 与 `decision_at`。 |
| `search_by_symbol` | `(symbol, query="", decision_at=None, top_k=10) -> list[RetrievalResult]` | 按 symbol 检索的便捷封装。 |

---

## 8. 索引运行器

### 8.1 `DocumentIndexingRunner`

消费 `module 03` 文档 Outbox，将文档事件转为持久化 Chunk 与 Embedding。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(*, news_repository: NewsRepository, vector_repository: VectorRepository, embedding_provider, chunker=None)` | 依赖新闻仓库、向量仓库、嵌入 Provider。 |
| `run_once` | `(*, limit: int = 50) -> int` | 消费一批 `vector_index` Outbox 消息，完成分块、嵌入、持久化、审计，并标记 Outbox 状态。 |

辅助函数：

| 函数 | 说明 |
|------|------|
| `_provider_name(provider)` | 取 Provider 名称，优先 `name` 属性，否则 `descriptor.name`。 |
| `_provider_version(provider)` | 取 Provider 版本，优先 `version` 属性，否则 `descriptor.version`。 |

---

## 9. 仓库

### 9.1 `VectorRepository`

PostgreSQL/pgvector 持久化边界，负责 Chunk、Embedding、审计记录的读写与检索。

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(session_factory: Callable[[], Session], *, dimension: int)` | 初始化会话工厂与期望向量维度。 |
| `upsert_chunks` | `(chunks: list[Chunk]) -> int` | 幂等写入 Chunk 元数据。 |
| `upsert_embeddings` | `(items: list[tuple[str, list[float]]], *, provider_name, model_name, model_version) -> int` | 按 `chunk_id`+Provider+模型版本 幂等写入向量。 |
| `search_vector` | `(query_vector, *, top_k=10, symbol=None, decision_at=None, doc_types=None) -> list[tuple[Chunk, float]]` | 全量余弦相似度计算并过滤 symbol/时间点/文档类型。 |
| `get_chunk` | `(chunk_id: str) -> Chunk \| None` | 按 ID 查询 Chunk。 |
| `list_chunks` | `(*, symbol=None, doc_types=None) -> list[Chunk]` | 列出 Chunk，按 `available_at` 倒序。 |
| `record_index_audit` | `(*, operation, provider_name, model_name, model_version, chunk_count, vector_count, keyword_count, degraded, error=None) -> int` | 持久化索引审计记录，返回 `audit_id`。 |
| `record_retrieval_audit` | `(*, query, constraints, results: list[RetrievalResult]) -> int` | 持久化可回放检索结果，返回 `audit_id`。 |
| `replay_retrieval` | `(audit_id: int) -> list[RetrievalResult]` | 按审计记录重建检索结果。 |

辅助函数：

| 函数 | 说明 |
|------|------|
| `_chunk_to_row(chunk)` | `Chunk` → `ChunkRow`。 |
| `_update_chunk_row(row, chunk)` | 更新已有 `ChunkRow`（除主键外全量覆盖）。 |
| `_chunk_from_row(row)` | `ChunkRow` → `Chunk`。 |
| `_cosine(a, b)` | 计算余弦相似度。 |

---

## 10. 跨模块使用说明

- **与 module 03（news）的衔接**：`Chunker.chunk` 接收 `DocumentEvent`，`DocumentIndexingRunner` 消费 `NewsRepository` 的 Outbox，完成文档到索引的转换。
- **与 module 06（research）的衔接**：`RetrievalTool` 是研究智能体获取证据的统一入口，返回带 `source_url`/`page`/`quote_span` 的 `RetrievalResult`，支持引用溯源。
- **持久化切换**：MVP 中 `EmbeddingPipeline` 使用内存 `VectorStore` 与 `BM25Index`；生产环境可替换为 `PersistentEmbeddingPipeline` + `VectorRepository`，配合 `OpenAIEmbeddingProvider` 与 `HTTPRerankProvider`。
- **Provider 注入**：通过 `EmbeddingProvider.set_embed_func` 与 `Reranker.set_rerank_func` 可在不修改代码的情况下接入真实模型。
- **审计与回放**：`VectorRepository.record_retrieval_audit` / `replay_retrieval` 支持检索结果的事后审计与可复现分析。
