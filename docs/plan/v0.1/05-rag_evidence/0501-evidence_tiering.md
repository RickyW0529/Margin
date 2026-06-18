---
task_id: 0501
parent_module: 05-rag_evidence
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase4: RAG 证据系统; §10.3, 产品设计 §9.2]
status: draft
estimate_days: 10
depends_on: [0403]
---

# 0501 证据等级与 Claim 结构 — 实施计划

## 1. 任务目标

实现证据 L1–L5 等级划分与证据 Claim 结构：claim_id、claim_type、statement、fact_or_inference、evidence_ids、confidence、conflicts、effective_at、locator。区分事实与推断，发现冲突，支撑置信度评估。L4/L5 不能单独改变研究/持仓状态；L5 只能触发调查，L4 只能作为辅助解释或与 L1-L3 证据交叉验证后参与判断。

## 2. 工作项拆解

- 0501.1 证据等级模型 — L1–L5 来源分级与质量评分对接。
- 0501.2 Claim 结构与 fact_or_inference — 结构化 Claim 落库。
- 0501.3 conflicts 冲突识别 — 多证据冲突检测与标记。
- 0501.4 L5 使用限制 — L5 只触发调查，不改变研究/持仓状态。

## 3. 依赖关系

- 前置：0403（检索片段与来源等级，对应 Gantt d2 after d1）。
- 被依赖：0502（引用定位字段）、0503（Claim 校验）。
- 外部依赖：04 检索片段的 source_level。

## 4. 工时估算

- 0501.1：2 天
- 0501.2：3 天
- 0501.3：3 天
- 0501.4：2 天
- 合计：10 天（对齐 Gantt d2）。

## 5. 里程碑与交付物

- M1：证据等级模型与来源分级对接（第 2 天）。
- M2：Claim 结构落库（第 5 天）。
- M3：冲突识别可用（第 8 天）。
- M4：L5 使用限制生效（第 10 天）。

## 6. 验收动作

- Claim 含 fact_or_inference、confidence、conflicts、locator；
- L5 来源不直接改变研究/持仓状态（对应 spec 05 §4）；
- 对应产品 §15 条目 4。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase4 d2、§10.3、产品 §9.2；
- 关联 spec：`spec/v0.1/05-rag_evidence/spec.md` §3 / §4；
- 不可变产物：Claim 记录、evidence_ids、conflicts。
