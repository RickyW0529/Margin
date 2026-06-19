---
task_id: 0603
parent_module: 06-multi_agent_research
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §12.1 Agent #5,#6,#7]
status: active
estimate_days: 5
depends_on: [0602]
---

# 0603 摘要、证据研究与估值 Agent — 实施计划

## 1. 任务目标

实现 Text Summary Agent（对公告/网页/财报片段做结构化摘要）、Evidence Research Agent（检索与组织证据 Claim）、Valuation Tool Agent（调用估值工具完成 DCF/相对估值/敏感性分析等数值计算）。数值必须由工具计算，LLM 不伪造工具结果。

## 2. 工作项拆解

- 0603.1 Text Summary Agent — 结构化摘要，输出 Schema 约束。
- 0603.2 Evidence Research Agent — 检索证据、组织 Claim，对接 05 模块。
- 0603.3 Valuation Tool Agent — 调用 ValuationTool 完成 DCF/相对估值/敏感性分析。
- 0603.4 工具调用记录 — 每次调用记录参数与结果。

## 3. 依赖关系

- 前置：0602（WebSearch Agent 与 Document Collector 产出候选文档与合规快照）。
- 被依赖：0604（Risk/Reflect Agent 消费摘要与证据）。
- 外部依赖：04 RetrievalTool、05 证据 Claim、ValuationTool。

## 4. 工时估算

- 0603.1：1 天
- 0603.2：2 天
- 0603.3：1 天
- 0603.4：1 天
- 合计：5 天。

## 5. 里程碑与交付物

- M1：Text Summary Agent 可用（第 1 天）。
- M2：Evidence Research Agent 对接证据模块（第 3 天）。
- M3：Valuation Tool Agent 数值计算（第 4 天）。
- M4：工具调用记录完整（第 5 天）。

## 6. 验收动作

- 摘要与证据 Claim 结构化输出（对应 spec 06 §3）；
- 估值数值由 ValuationTool 计算，LLM 不伪造（对应架构 §11.2）；
- 对应产品 §15 条目 4。

## 7. 审计追溯

- `source_refs`：架构 §12.1 #5/#6/#7；
- 关联 spec：`spec/v0.1/06-multi_agent_research/spec.md` §4 / §8；
- 不可变产物：摘要、Claim、估值工具调用记录。
