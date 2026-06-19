---
task_id: 0403
parent_module: 04-text_indexing
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §7.3 混合检索; §7.4 检索约束]
status: active
estimate_days: 7
depends_on: [0402]
---

# 0403 混合检索与 Rerank — 实施计划

## 1. 任务目标

实现混合召回与重排序：Score = w_v·VectorScore + w_k·BM25 + w_t·TimeDecay + w_s·SourceQuality + w_e·EntityMatch。检索必须按股票代码过滤、满足 available_at <= decision_at、可按文档类型过滤、优先官方证据、相同事实去重、输出含页码或原文定位。

## 2. 工作项拆解

- 0403.1 Hybrid Retrieval 融合 — 向量 + 关键词 + 时间衰减 + 来源质量 + 实体匹配加权。
- 0403.2 Reranker — 可选 RerankProvider 重排候选片段。
- 0403.3 检索约束执行 — 代码过滤、时点过滤、文档类型过滤、官方优先、去重、定位输出。
- 0403.4 RetrievalTool 接口 — 供 06 多 Agent 调用。

## 3. 依赖关系

- 前置：0402（向量与关键词索引）。
- 被依赖：0501（证据等级与 Claim 基于检索片段）。
- 外部依赖：RerankProvider（可选）。

## 4. 工时估算

- 0403.1：2 天
- 0403.2：2 天
- 0403.3：2 天
- 0403.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：Hybrid Retrieval 融合评分可用（第 2 天）。
- M2：Reranker 重排（第 4 天）。
- M3：检索约束全部生效（第 6 天）。
- M4：RetrievalTool 接口交付（第 7 天）。

## 6. 验收动作

- 检索结果按股票代码与时点过滤，输出含页码/原文定位（对应 spec 04 §3）；
- 相同事实去重，官方证据优先；
- 对应产品 §12.1 RAG 命中率指标。

## 7. 审计追溯

- `source_refs`：架构 §7.3 / §7.4；
- 关联 spec：`spec/v0.1/04-text_indexing/spec.md` §3 / §4；
- 不可变产物：检索查询、候选片段、评分权重版本。
