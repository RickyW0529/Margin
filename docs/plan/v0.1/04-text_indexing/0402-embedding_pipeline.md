---
task_id: 0402
parent_module: 04-text_indexing
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §7.1 数据流; §8.1 EmbeddingProvider]
status: draft
estimate_days: 7
depends_on: [0401]
---

# 0402 Embedding 与向量索引 — 实施计划

## 1. 任务目标

实现 Embedding 流水线与向量/关键词双索引：Chunk → Embedding → pgvector 向量库 + 关键词索引。MVP 向量库采用 pgvector，Qdrant 可插拔（VectorStoreProvider）。EmbeddingProvider 支持 OpenAI-compatible / 本地模型。

## 2. 工作项拆解

- 0402.1 EmbeddingProvider 接入 — OpenAI-compatible / 本地模型，经 Provider Registry。
- 0402.2 pgvector 向量存储 — 建索引、写入、可插拔 Qdrant 接口。
- 0402.3 关键词索引 — BM25 / 全文索引并行建设。
- 0402.4 索引审计与回放 — 索引版本记录，支持相同查询回放。

## 3. 依赖关系

- 前置：0401（Chunk 与元数据）。
- 被依赖：0403（混合检索）。
- 外部依赖：01 Provider Registry（EmbeddingProvider）、10 pgvector 部署。

## 4. 工时估算

- 0402.1：2 天
- 0402.2：2 天
- 0402.3：2 天
- 0402.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：EmbeddingProvider 可用（第 2 天）。
- M2：pgvector 写入与查询（第 4 天）。
- M3：关键词索引并行可用（第 6 天）。
- M4：索引版本与回放（第 7 天）。

## 6. 验收动作

- Chunk 入向量库与关键词索引；
- Embedding Provider 失败时降级为关键词检索并告警（对应 spec 04 §7）；
- 向量库失败时关键词检索降级（对应架构 §25）。

## 7. 审计追溯

- `source_refs`：架构 §7.1、§8.1；
- 关联 spec：`spec/v0.1/04-text_indexing/spec.md` §3 / §7；
- 不可变产物：向量索引版本、Embedding 模型版本。
