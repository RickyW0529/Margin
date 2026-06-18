---
module_id: 05-rag_evidence
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §9, §13.2-5; 架构设计 §10, §26-Phase4]
status: draft
---

# 05 RAG 证据模块 — 功能规格

## 1. 模块目标

让每个关键研究结论满足：有来源、有时间、有原文定位、能区分事实与推断、能发现冲突、能拒绝回答。对证据进行 L1–L5 等级划分，提供 Claim 结构与引用定位字段，并在证据不足、来源冲突或数据异常时输出 `ABSTAINED`。

## 2. 输入 / 输出

- **输入**：04-text_indexing 检索出的证据片段、Agent 生成的 Claims、`decision_at` 决策时点。
- **触发**：研究流程中 Agent 提交 Claims 后触发校验。
- **输出**：结构化证据 Claim（含 fact_or_inference、confidence、conflicts、locator）、引用定位字段、校验通过/失败结果。
- **消费方**：06-multi_agent_research（Citation Validator、Evidence Research Agent）、08-research_candidate_dashboard（证据展开）。

## 3. 接口契约

RAG 工作流（架构 §10.2）：Agent → Retriever（混合检索）→ Vector DB → 候选片段 → 重排证据 → Agent + LLM 生成 Claims/Unknowns/Risks → Citation Validator 校验引用和时间 → 通过/失败。

证据 Claim 结构（架构 §10.3）：

```json
{
  "claim_id": "claim_001",
  "claim_type": "cash_flow_improvement",
  "statement": "经营现金流质量改善",
  "fact_or_inference": "FACT",
  "evidence_ids": ["ev_101", "ev_102"],
  "confidence": 0.87,
  "conflicts": [],
  "effective_at": "2026-06-18",
  "locator": {
    "source_url": "https://...",
    "page": 86,
    "section": "经营现金流",
    "paragraph_index": 12,
    "table_id": "cash_flow_table",
    "row_id": "net_operating_cash_flow",
    "content_hash": "sha256:..."
  }
}
```

## 4. 数据模型

证据等级（产品 §9.2 / 架构 §6.1）：

| 等级 | 来源 |
|---|---|
| L1 | 交易所公告、监管文件、定期报告 |
| L2 | 公司 IR、业绩说明会、管理层正式指引 |
| L3 | 行业价格、销量、库存、招投标等硬数据 |
| L4 | 权威媒体、专业研究 |
| L5 | 社交媒体和未经验证信息 |

L4/L5 不能单独改变研究/持仓状态；L5 只能触发调查，L4 只能作为辅助解释或与 L1-L3 证据交叉验证后参与判断。

引用定位字段（产品 §9.3）：`evidence_id`、`document_id`、`source_type`（filing_pdf/web_page/table/api_record/user_file）、`source_url`、`source_level`、`content_hash`、`published_at`、`available_at`、`retrieved_at`、`page`、`section`、`paragraph_index`、`table_id`、`row_id`、`quote_span`。要求：PDF 优先记录页码/章节/字符范围；HTML 优先记录 URL/标题/段落序号/正文哈希；表格优先记录表格 ID/行列定位/原始文件哈希；WebSearch 结果必须落到可访问原文或快照，不能只引用搜索摘要；所有引用必须满足 `available_at <= decision_at`。

核心实体（架构 §5.3）：`NEWS_DOCUMENT` 1→N `DOCUMENT_CHUNK` 1→N `EVIDENCE_CLAIM`、`RESEARCH_ITEM` 1→N `RESEARCH_EVIDENCE`。

## 5. 与其他模块依赖

- **上游**：04-text_indexing（证据片段与定位）。
- **下游**：06-multi_agent_research（Citation Validator 校验、Evidence Research Agent 组织 Claim）、08-research_candidate_dashboard（证据展开）。
- **规避循环**：本模块只校验与结构化证据，不生成研究信号决策。

## 6. 验收标准

对应产品设计 §15：

- 条目 4：研究结论包含证据引用与引用定位字段；
- 条目 8：数据异常时停止高置信研究信号输出（证据不足/冲突 → ABSTAINED）。

## 7. 风险与降级

对应架构 §25：

- 引用校验失败 → 标记该 Claim 失败，不进入研究信号；
- 证据冲突 → 提升到反方审查，置信度上限封顶；
- 证据不足 → 输出 `ABSTAINED`，宁可拒绝也不输出虚假高置信结论（架构 §25 原则）。

## 8. 审计追溯

- `source_refs` 指向产品设计 §9、架构设计 §10 / §26 Phase4；
- 每个 Claim 保留 `evidence_ids`、`locator`、`content_hash`、`effective_at`，落库不可篡改；
- 引用定位字段支持从结论回溯到原文页码/章节/字符范围。
