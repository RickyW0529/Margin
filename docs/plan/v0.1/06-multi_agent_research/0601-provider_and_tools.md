---
task_id: 0601
parent_module: 06-multi_agent_research
product_version: v0.1
doc_version: v0.1
source_refs: [架构设计 §26-Phase4: 多 Agent 工具调用; §8, §9, §11, §14]
status: draft
estimate_days: 7
depends_on: [0503]
---

# 0601 Provider 接入层、路由与工具系统 — 实施计划

## 1. 任务目标

实现 AI 层基础设施：Provider 接入层（MarketData/WebSearch/LLM/Embedding/Rerank/VectorStore/Notification）、模型路由层（按任务类型选模型/工作流/工具集/检索范围/成本预算/超时重试/输出 Schema）、工具系统（11 个内置工具）、模型网关与 Guardrail（Provider 适配/Key/能力注册/成本/限流/重试/Fallback/Prompt 版本/内容安全/结构化输出验证）。所有关键输出必须通过 JSON Schema。

## 2. 工作项拆解

- 0601.1 Provider 接入层对接 — 复用 01 Provider Registry，接入各 Provider 类型。
- 0601.2 模型路由层 — 任务类型→模型/工具/检索/预算/Schema 路由。
- 0601.3 工具系统 — MarketData/Financial/Filing/Retrieval/Valuation/Factor/Portfolio/Backtest/Calendar/Alert/Python 工具，含权限范围与调用记录。
- 0601.4 模型网关与 Guardrail — 结构化输出 JSON Schema 校验、Prompt 版本、内容安全。

## 3. 依赖关系

- 前置：0503（证据校验，对应 Gantt d3 after d2）。
- 被依赖：0606（Universe/Quant Agent）、0701（策略配置 Schema）、后续 Agent 节点通过 0606 串联。
- 外部依赖：01 Provider Registry、02 PortfolioTool 数据、04 RetrievalTool。

## 4. 工时估算

- 0601.1：2 天
- 0601.2：2 天
- 0601.3：2 天
- 0601.4：1 天
- 合计：7 天。

## 5. 里程碑与交付物

- M1：Provider 接入层可用（第 2 天）。
- M2：模型路由层按任务类型分流（第 4 天）。
- M3：11 个内置工具可用（第 6 天）。
- M4：模型网关结构化输出校验（第 7 天）。

## 6. 验收动作

- 数值由工具计算，LLM 不伪造工具结果（对应 spec 06 §3）；
- 关键输出通过 JSON Schema（对应架构 §14）；
- 工具调用记录参数与结果。

## 7. 审计追溯

- `source_refs`：架构 §26-Phase4 d3、§8 / §9 / §11 / §14；
- 关联 spec：`spec/v0.1/06-multi_agent_research/spec.md` §3 / §8；
- 不可变产物：路由决策、工具调用记录、模型版本。
