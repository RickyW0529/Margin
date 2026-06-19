---
module_id: 06-multi_agent_research
product_version: v0.1
doc_version: v0.1
source_refs: [产品设计 §4.5, §5.2, §13.2-6; 架构设计 §8, §9, §11, §12, §14, §26-Phase4]
status: active
---

# 06 多 Agent 研究流程模块 — 功能规格

## 1. 模块目标

通过职责隔离的多 Agent 编排完成晚间研究闭环：从量化初筛到证据整合、估值、风险反方审查、组合约束、研究信号生成与引用校验。「多 Agent」指职责分工与工具调用隔离，不是通过多个 Agent 辩论制造确定性。每个 Agent 必须有明确输入、工具权限、输出 Schema 和失败降级策略。所有关键输出必须通过 JSON Schema，不接受仅自然语言结果。

## 2. 输入 / 输出

- **输入**：01-data_provider 的因子与候选、04-text_indexing 检索证据、05-rag_evidence 的 Claim、07-strategy_config 的策略/Prompt/约束、02-holdings 的组合约束。
- **触发**：晚间批处理（架构 §18 完整晚间时序）、用户手工触发研究运行。
- **输出**：结构化研究信号（RESEARCH_CANDIDATE / WATCH / ABSTAINED）、研究运行快照（不可变）、持仓研究状态更新。
- **消费方**：08-research_candidate_dashboard、09-holdings_monitoring、02-holdings（研究状态回写）。

## 3. 接口契约

AI 层总体结构（架构 §8）：用户请求/定时任务 → 路由层 → Provider 接入层 → 多 Agent/Workflow 编排层 → 内部工具系统 / RAG 证据 → 模型网关 → 结构化输出与 Guardrail → 研究信号决策引擎。v0.1 不建设 MCP Server、MCP Gateway 或自定义 HTTP 工具。

模型路由层（架构 §9）：按任务类型选择模型/工作流/工具集/检索范围/成本预算/超时重试/输出 Schema。公告抽取用低成本结构化模型，复杂财报分析用高能力长上下文模型，数值计算用 Python/估值工具，实时提醒用规则优先+轻量模型。

内置工具（架构 §11.1）：MarketDataTool、FinancialTool、FilingTool、RetrievalTool、ValuationTool、FactorTool、PortfolioTool、BacktestTool、CalendarTool、AlertTool、PythonTool。工具调用原则（§11.2）：LLM 不伪造工具结果；数值必须由工具计算；每次调用记录参数与结果；工具有权限范围；生产环境禁止任意 Shell；外部写操作必须用户确认。

模型网关与 Guardrail（架构 §14）：Provider 适配、Key 管理、能力注册、成本统计、限流、重试、Fallback、Prompt 版本、内容安全、结构化输出验证。

## 4. 数据模型

多 Agent 职能分工（架构 §12.1），12 个职能节点：

1. Universe Filter Agent — 股票池与基础规则缩小范围；
2. Quant Research Agent — 因子、估值输入、基础排名；
3. WebSearch Agent — WebSearch Provider 发现新闻/公告入口/网页来源；
4. Document Collector Agent — 下载或快照合规原文，记录来源/时间/哈希；
5. Text Summary Agent — 公告/网页/财报片段结构化摘要；
6. Evidence Research Agent — 检索与组织证据 Claim；
7. Valuation Tool Agent — 调用估值工具完成数值计算；
8. Risk and Value-Trap Review Agent — 输出风险评分而非未校准概率；
9. Reflect / Counter-Argument Agent — 审查反方证据、冲突、未知项；
10. Portfolio Constraint Agent — 检查组合暴露与持仓逻辑；
11. Research Signal Composer — 生成研究信号与面板卡片；
12. Citation Validator — 校验证据引用、来源等级、时点。

工作流状态（架构 §12.2）：Initialized → DataReady → EvidenceReady → AnalysisReady → ReviewReady → Published；DataReady → Aborted（数据错误）；EvidenceReady/ReviewReady → Abstained（证据不足/风险冲突过高）。

不可变研究信号快照（架构 §5.4）：每次研究运行冻结股票池版本、数据快照、策略版本、Prompt 版本、工具版本、模型版本、检索结果、证据 ID、结构化输出、生成时间、输入哈希、输出哈希。

## 5. 与其他模块依赖

- **上游**：01-data_provider、04-text_indexing、05-rag_evidence、07-strategy_config、02-holdings。
- **下游**：08-research_candidate_dashboard、09-holdings_monitoring、02-holdings（研究状态回写）。
- **规避循环**：研究流程单向推进，组合约束为只读输入；研究状态回写持仓后不再回流。

## 6. 验收标准

对应产品设计 §15：

- 条目 3：可运行完整晚间工作流；
- 条目 4：研究结论包含证据引用；
- 条目 2：可配置至少一个 OpenAI-compatible LLM Provider，并通过模型路由层执行研究任务；
- 条目 8：数据异常时停止高置信研究信号输出（工作流 Aborted）；
- 条目 9：所有研究信号保留不可变审计记录（研究运行快照）。

## 7. 风险与降级

对应架构 §25：

- LLM 失败 → 规则型报告（架构 §25）；
- 数据错误 → 工作流 Aborted，停止高置信研究信号；
- 证据不足/冲突过高 → Abstained；
- 单 Agent 失败 → 按该 Agent 降级策略处理，不阻塞整条链路或伪造结果。

## 8. 审计追溯

- `source_refs` 指向产品设计 §4.5 / §5.2、架构设计 §8 / §9 / §11 / §12 / §14 / §26 Phase4；
- 每次研究运行冻结完整快照（策略/Prompt/工具/模型/检索/证据/输入输出哈希），落库不可篡改；
- 每次 Agent 节点调用记录 `trace_id`、`agent_node`、`model_version`、参数与结果。
