---
task_id: 0401
parent_module: 04-text_indexing
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase4: 文本索引与引用定位; §7.1, §7.2]
status: active
estimate_days: 10
depends_on: [0303]
---

# 0401 文档解析与分块 — 实施计划

## 1. 任务目标

实现文档解析、结构识别与分块：年报/季报按章节/表格/页码，公告按事项和条款，新闻按标题/导语/正文段落，IR 按问答对，行业报告按主题和图表说明，用户笔记按标题与段落。每个 Chunk 携带完整元数据与定位字段。

## 2. 工作项拆解

- 0401.1 Parser 与结构识别 — PDF/HTML/表格解析。
- 0401.2 Chunker 分块策略 — 按文档类型差异化切分。
- 0401.3 Chunk 元数据 — chunk_id/document_id/symbol/source_level/published_at/available_at/source_url/page/section/paragraph_index/table_id/row_id/quote_span/content_hash。
- 0401.4 解析失败处理 — 保留原文并停止相关 AI 结论。

## 3. 依赖关系

- 前置：0303（去重后文档，对应 Gantt d1 after c2）。
- 被依赖：0402（Embedding 流水线）。
- 外部依赖：无。

## 4. 工时估算

- 0401.1：3 天
- 0401.2：3 天
- 0401.3：2 天
- 0401.4：2 天
- 合计：10 天。

## 5. 里程碑与交付物

- M1：Parser 支持 PDF/HTML/表格（第 3 天）。
- M2：差异化分块策略齐全（第 6 天）。
- M3：Chunk 元数据完整（第 8 天）。
- M4：解析失败处理与降级（第 10 天）。

## 6. 验收动作

- 各文档类型按策略切分，Chunk 元数据含定位字段；
- 解析失败时保留原文并停止相关 AI 结论（对应 spec 04 §7）；
- 对应产品 §12.1 文档解析成功率指标。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase4 d1、§7.1 / §7.2；
- 关联 spec：`spec/v0.1/04-text_indexing/spec.md` §4 / §7；
- 不可变产物：Chunk 元数据、content_hash、定位字段。
