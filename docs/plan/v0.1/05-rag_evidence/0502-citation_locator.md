---
task_id: 0502
parent_module: 05-rag_evidence
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §9.3 引用定位字段; 架构设计 §10.3 locator]
status: active
estimate_days: 7
depends_on: [0501]
---

# 0502 引用定位字段 — 实施计划

## 1. 任务目标

实现多来源引用定位字段：evidence_id、document_id、source_type（filing_pdf/web_page/table/api_record/user_file）、source_url、source_level、content_hash、published_at、available_at、retrieved_at、page、section、paragraph_index、table_id、row_id、quote_span。PDF 优先页码/章节/字符范围，HTML 优先 URL/标题/段落序号/正文哈希，表格优先表格 ID/行列定位，WebSearch 结果必须落到可访问原文或快照。

## 2. 工作项拆解

- 0502.1 locator 字段模型 — 统一定位字段结构。
- 0502.2 PDF/HTML/表格差异化定位 — 按来源类型填充对应字段。
- 0502.3 WebSearch 原文落校验 — 不能只引用搜索摘要。
- 0502.4 时点校验 — 所有引用满足 available_at <= decision_at。

## 3. 依赖关系

- 前置：0501（Claim 结构）。
- 被依赖：0503（Claim 校验使用 locator）。
- 外部依赖：04 Chunk 定位字段。

## 4. 工时估算

- 0502.1：2 天
- 0502.2：2 天
- 0502.3：2 天
- 0502.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：locator 字段模型可用（第 2 天）。
- M2：PDF/HTML/表格定位填充（第 4 天）。
- M3：WebSearch 原文落校验（第 6 天）。
- M4：时点校验集成（第 7 天）。

## 6. 验收动作

- 引用可从结论回溯到原文页码/章节/字符范围（对应 spec 05 §4）；
- WebSearch 摘要无原文时被拒绝；
- 对应产品 §15 条目 4。

## 7. 审计追溯

- `source_refs`：产品 §9.3、架构 §10.3；
- 关联 spec：`spec/v0.1/05-rag_evidence/spec.md` §4 / §8；
- 不可变产物：locator 字段、content_hash。
