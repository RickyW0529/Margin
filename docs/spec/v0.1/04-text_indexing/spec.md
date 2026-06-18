---
module_id: 04-text_indexing
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §4.4, §13.2-4; 架构设计 §7, §26-Phase4]
status: draft
---

# 04 文本索引模块 — 功能规格

## 1. 模块目标

对公告、财报、新闻和用户自有/授权研报进行文档解析、分块、Embedding、关键词索引、元数据过滤、向量检索、关键词检索、混合召回、重排序与引用定位，为 RAG 证据系统提供可过滤、可引用的检索基础。MVP 向量库采用 pgvector，Qdrant 可插拔。

## 2. 输入 / 输出

- **输入**：03-filing_websearch 产出的文档事件与原文快照、用户上传的自有/授权文件。
- **触发**：文档入库后进入向量化队列。
- **输出**：文档 Chunk（含元数据与定位字段）、向量索引、关键词索引；检索时输出重排后的证据片段。
- **消费方**：05-rag_evidence、06-multi_agent_research（RetrievalTool）。

## 3. 接口契约

数据流（架构 §7.1）：原始文档 → Parser → 结构识别 → Chunker → Embedding → Vector DB / 关键词索引 → Hybrid Retrieval → Reranker → 证据片段。

检索约束（架构 §7.4）：

- 必须按股票代码过滤；
- 必须满足 `available_at <= decision_at`；
- 可按文档类型过滤；
- 优先官方证据；
- 相同事实去重；
- 输出必须包含页码或原文定位。

## 4. 数据模型

Chunk 策略（架构 §7.2）：年报/季报按章节/表格/页码；公告按事项和条款；新闻按标题/导语/正文段落；IR 按问答对；行业报告按主题和图表说明；用户笔记按标题与段落。

每个 Chunk 元数据：`chunk_id`、`document_id`、`symbol`、`source_level`、`published_at`、`available_at`、`source_url`、`page`、`section`、`paragraph_index`、`table_id`、`row_id`、`quote_span`、`content_hash`。

混合检索分数（架构 §7.3）：

```
Score = w_v·VectorScore + w_k·BM25 + w_t·TimeDecay + w_s·SourceQuality + w_e·EntityMatch
```

## 5. 与其他模块依赖

- **上游**：03-filing_websearch（文档与原文快照）。
- **下游**：05-rag_evidence（证据片段与定位字段）、06-multi_agent_research（RetrievalTool）。
- **规避循环**：本模块不产生研究结论，仅提供检索能力。

## 6. 验收标准

对应产品设计 §15：

- 条目 4：研究结论包含证据引用与引用定位字段（依赖本模块输出页码/章节/字符范围等定位）；
- 系统指标（产品 §12.1）：文档解析成功率、RAG 命中率。

## 7. 风险与降级

对应架构 §25：

- 向量库失败 → 关键词检索降级（架构 §25）；
- 解析失败 → 保留原文并停止相关 AI 结论；
- Embedding Provider 失败 → 降级为关键词检索并告警。

## 8. 审计追溯

- `source_refs` 指向产品设计 §4.4、架构设计 §7 / §26 Phase4；
- 每个 Chunk 保留 `content_hash` 与原文快照引用，定位字段（page/section/quote_span 等）落库不可篡改；
- 检索结果可回放：相同查询 + 相同索引版本 → 相同候选片段。
