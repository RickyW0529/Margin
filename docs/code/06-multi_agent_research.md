# 06-multi_agent_research 模块文档

本文件描述当前仓库中的多 Agent 研究流程实现。v0.2 已删除 v0.1 的同步 `ResearchWorkflow`、12 个顺序 Agent、全局工具注册表兼容入口以及 `/api/v1/research/run`、`/api/v1/research/tools` API；当前模块只承担“冻结上下文进入 LangGraph delta review，输出可审计研究复核结果”的职责。

## 1. 模块职责

`src/margin/research/` 负责消费上游冻结的 `ResearchContextSnapshot`，在确定性路由与受限工具权限下执行 AI delta review，并把本轮结论、引用校验、LLM 调用、工具调用和 outbox 事件持久化。

当前边界：

- 输入：已冻结的研究上下文快照 ID，不直接抓行情、搜索新闻或读取用户前端临时状态。
- 编排：LangGraph 图，含路由、证据计划、检索、基本面分析、估值分析、风险复核、反方论证、决策、引用校验、修复与 finalize。
- 工具：通过 `ScopedToolFactory`、`ToolPolicyEngine`、`ToolExecutor` 按节点生成最小权限工具清单；包含 Analysis Mart 五个只读工具和可选 RAG evidence 检索工具；默认拒绝越权、跨 scope、跨 security、PIT 违规、预算超限和 deadline 过期。
- Prompt：通过 `PromptFactory` 生成固定 section 顺序的提示词，所有外部文本都进入 untrusted data block。
- 反思：`NodeExecutionRunner` 对 LLM 节点执行 draft → deterministic validation → critic → 最多一次 revision；critic/revision 不能新增 evidence ID。
- 输出：`ResearchDeltaReview`，表示本轮 current review outcome 与有效结论指针，不输出 BUY/SELL。

## 2. 当前文件结构

| 路径 | 当前职责 |
| --- | --- |
| `src/margin/research/models.py` | v0.1 snapshot 兼容模型与研究信号模型，供历史快照和 dashboard 内部聚合读取。 |
| `src/margin/research/llm.py` | OpenAI-compatible LLM provider、确定性测试 provider、模型路由和结构化输出护栏。 |
| `src/margin/research/service.py` | 高层入口；生产路径为 `ResearchService.run_delta_review(context_snapshot_id)`。 |
| `src/margin/research/graph/state.py` | LangGraph 状态、review mode、review outcome、节点状态与图事件模型。 |
| `src/margin/research/graph/builder.py` | 构建 AI delta review LangGraph 拓扑，并承载确定性条件路由。 |
| `src/margin/research/graph/nodes/` | context、evidence、analysis、decision 等节点实现。 |
| `src/margin/research/execution/llm_service.py` | LLM 调用服务，记录 hash-only prompt/output 审计。 |
| `src/margin/research/execution/node_runner.py` | 带反思机制的节点执行器。 |
| `src/margin/research/execution/reflection.py` | 节点 draft/critic/revision 结果结构。 |
| `src/margin/research/prompts/` | Prompt 模型、仓库与工厂。 |
| `src/margin/research/tools/definitions.py` | 工具定义、权限级别、工具参数与执行上下文。 |
| `src/margin/research/tools/factory.py` | 按节点和上下文生成 scoped tool manifest。 |
| `src/margin/research/tools/policy.py` | 默认拒绝的工具权限策略。 |
| `src/margin/research/tools/executor.py` | 统一工具执行器，执行前校验策略并写审计。 |
| `src/margin/research/tools/manifests.py` | 面向 LLM 的工具 manifest 结构。 |
| `src/margin/research/analysis_tools.py` | 注册 `analysis_snapshot_get`、`analysis_metrics_list`、`analysis_findings_list`、`quant_feature_snapshot_get`、`quant_feature_rows_list` 五个第四层 Mart 只读工具。 |
| `src/margin/research/evidence_tools.py` | 注册 `rag_evidence_retrieve`；把向量检索结果转换为 Agent-ready `evidence_blocks`，并可写入 `05-rag_evidence` EvidencePackage。 |
| `src/margin/research/checkpoint.py` | PostgreSQL LangGraph checkpoint saver，校验 identity hash 并恢复 pending writes。 |
| `src/margin/research/delta_repository.py` | `ResearchDeltaReview` 与 `research_delta_outbox` 的内存/PostgreSQL 持久化。 |
| `src/margin/research/graph_audit_repository.py` | LLM/tool 调用审计 PostgreSQL repository。 |
| `src/margin/research/production_graph.py` | 生产分析 handler、决策 handler 和引用校验器构造。 |
| `src/margin/research/db_models.py` | graph run、node run、checkpoint、tool call、LLM call、delta review、outbox 表。 |
| `src/margin/agent_runtime/models.py` | v0.4 agent runtime 的 run、step、plan、ContextArtifact、GuardrailDecision、AgentCard 等 Pydantic 模型。 |
| `src/margin/agent_runtime/flows/scheduled_stock_analysis_steps.json` / `step_schema.json` | 定时股票分析固定流程 JSON 及其 schema：数据检查、量化分析、新闻获取、股票分析、MainAgent 最终复查。 |
| `src/margin/agent_runtime/step_definitions.py` | 加载并校验固定 step JSON，运行时按 `order` 生成稳定步骤序列。 |
| `src/margin/agent_runtime/context_store.py` | Shared Context Store 的内存与 SQLAlchemy repository，写入 run、step、artifact、guardrail decision，并校验 artifact payload hash。 |
| `src/margin/agent_runtime/db_models.py` | v0.4 agent runtime Context Store ORM 表：run、step、artifact、guardrail decision。 |
| `src/margin/agent_runtime/guardrails.py` | 规则型输入和计划防护栏，拦截保证收益、提示注入和固定流程篡改。 |
| `src/margin/agent_runtime/cards.py` | A2A 风格 ExpertAgent Card 注册表，MainAgent 只发现专家 agent 与其技能，不暴露专家内部工具；定时写权限专家不允许进入用户问答计划。 |
| `src/margin/agent_runtime/quant_agent.py` | QuantAgent 当前 ML 生命周期策略画像，固定 profile ID、策略族、80% 股票仓位/20% 现金、所需特征组和 metadata 输出；底层 scorer 仍在 `valuation_discovery.quant`，Agent 只负责选择与审计指纹。 |
| `src/margin/agent_runtime/main_agent.py` | MainAgent foundation：创建定时固定计划、用户问答 LLM 动态计划，写入 Context Store，并按所需 artifact 执行最终复查。 |
| `src/margin/agent_runtime/expert_agents.py` | ExpertAgent executor：`GeneralQnaAgent` 与 `DataAnalystAgent` 都通过真实 LLM 生成用户问答；`StockAnalystAgent` 在定时研究链路中生成可追溯 `portfolio_adjustment` 与 `dashboard_projection_event` artifact，允许删除风险候选或下调仓位，并可把调整后的 dashboard 投影写库，但仍不输出交易指令。 |
| `src/margin/prompts/` | 集中 Prompt Repository、Renderer、agent runtime prompt 模板与 guardrail prompt 模板。 |
| `src/margin/api/dependencies.py` | 暴露缓存的 `get_main_agent_runtime()` FastAPI dependency。 |
| `alembic/versions/20260707_0047_agent_runtime.py` | 创建 agent runtime run、step、artifact、guardrail decision 持久化表。 |
| `scripts/smoke_ai_delta_review.py` | AI delta review smoke，支持 carry/delta/full 和真实 LLM 要求模式。 |

### v0.4 Agent Runtime Foundation

当前实现新增 v0.4 agent runtime foundation，用于承载用户问答窗口和定时股票分析的上层编排基础：

- Prompt 统一放在 `src/margin/prompts/`，通过 `PromptRegistry` 与 `PromptRenderer` 按版本加载、渲染和生成 hash，避免提示词散落在业务代码中。
- 定时股票分析固定步骤由 `scheduled_stock_analysis_steps.json` 定义，MainAgent 创建计划时只能使用该 JSON 中的步骤顺序和专家技能。
- Shared Context Store 支持内存和 SQLAlchemy 两种 repository，artifact 写入时使用稳定 JSON hash；Context Store 存储 run、step、artifact、guardrail decision，专家 agent 之间不直接通信。
- 防护栏当前包含确定性规则层：输入层拦截保证收益/保本/稳赚/确定上涨等金融承诺请求，拦截提示注入；计划层校验定时任务不能重排或替换固定流程。
- ExpertAgent Card 使用 A2A 风格字段暴露 `DataInspectionAgent`、`QuantAgent`、`NewsAcquisitionAgent`、`StockAnalystAgent`、`GeneralQnaAgent`、`DataAnalystAgent`、`CodeSandboxAgent` 的技能；`quant_screening_tool`、`data_sync_tool` 等底层工具不暴露给 MainAgent。
- `QuantAgent` 的定时技能为 `run_ml_lifecycle_quant_analysis`，策略选择封装在 `agent_runtime.quant_agent`；schedule 启动 valuation refresh 时会把该 profile 写入 metadata 和 ContextArtifact，量化层据此走 `ml_lgbm_lifecycle` serving 路径。
- `CodeSandboxAgent` 仅作为用户问答专家 card 暴露，`schedule_allowed=False`；当前 foundation 不执行 sandbox，只记录其发现边界。
- `MainAgentRuntime` 只负责创建计划和最终复查，不调用确定性工具，不写业务表；用户问答计划必须通过真实 LLM planner 读取 A2A 风格 ExpertAgent Cards 后选择只读 Q&A 专家，规划失败、LLM 失败或输出没有合法只读专家时返回明确失败，不使用本地关键词兜底。
- `GeneralQnaAgent` 负责问候、产品使用和不需要研究数据的普通问答；`DataAnalystAgent` 负责股票、推荐、量化结果、估值、证据、指标、新闻和 dashboard 数据类问答。两者均使用集中 Prompt Repository 渲染 prompt，并调用真实 LLM 生成最终回答，不使用模板字符串冒充 Agent 输出。
- `DataAnalystAgent` 的确定性部分只读取 dashboard service 并生成 `analysis_table` artifact；最终 `explanation` 必须来自 LLM，并记录 prompt id/hash、输入 hash、模型和耗时。
- `StockAnalystAgent.adjust_quant_candidates()` 消费量化/Analysis Mart 候选摘要，按 review/risk flags 生成 `keep`、`reduce_weight` 或 `delete` 调整，并写入 `portfolio_adjustment` artifact；payload 包含 `removed_security_ids`、目标仓位、调整后仓位、原因、最高股票仓位和最低现金比例。
- 当注入 `DashboardRepository` 时，`StockAnalystAgent` 会基于默认量化投影发布新的 adjusted dashboard run：删除项不进入最新候选列表，保留/降权项写入 `adjusted_weight` 与 `agent_adjustment.source=StockAnalystAgent`；同时写入 `dashboard_projection_event` artifact，供 MainAgent 最终复查和 Q&A 读取。
- 自动研究 schedule 启动 valuation refresh 时会把 `agent_run_id` 写入 orchestration metadata；worker 末端 dashboard refresh 会把该 ID 传给 `StockAnalystAgent`，确保专家 overlay artifact 归属到同一个 MainAgent run。
- `get_main_agent_runtime()` 生产依赖已切到 `SQLAlchemyAgentContextStore`，worker 写入的 run/step/artifact/guardrail decision 可被 API/Q&A 进程读取；单元测试仍可显式注入 `MemoryAgentContextStore`。

## 3. 核心模型

### 3.1 LangGraph review 状态

主要定义在 `src/margin/research/graph/state.py`。

| 类型 | 说明 |
| --- | --- |
| `ReviewMode` | `FULL_REVIEW`、`DELTA_REVIEW`、`CARRY_FORWARD_FAST_PATH`、`REVIEW_DEFERRED`、`ABSTAIN`。 |
| `ReviewOutcome` | `CARRY_FORWARD_VERIFIED`、`UPDATE_ASSESSMENT`、`DOWNGRADE_CONFIDENCE`、`INVALIDATE`、`ABSTAIN`、`REVIEW_DEFERRED`。 |
| `AIDeltaGraphState` | 图运行状态，包含 context、evidence package、节点输出、引用校验结果、错误与最终 review。 |
| `GraphNodeStatus` | 节点运行状态，供审计和恢复使用。 |

### 3.2 Delta review 持久化

主要定义在 `src/margin/research/delta_repository.py`。

| 类型 | 说明 |
| --- | --- |
| `ResearchDeltaReview` | 本轮 AI 复核的不可变结果，包含 `review_id`、`graph_run_id`、`context_snapshot_id`、`outcome`、`effective_assessment_id`、`reason`、`citation_status`、`created_at`。 |
| `MemoryResearchDeltaRepository` | 测试用内存实现，保证同一 graph run 的 outbox 幂等。 |
| `SQLAlchemyResearchDeltaRepository` | PostgreSQL 实现，在一个事务内写 delta review、终结 graph run、创建 outbox。 |

### 3.3 LLM 与工具审计

| 类型 | 位置 | 说明 |
| --- | --- | --- |
| `LLMCallAuditRecord` | `execution/llm_service.py` | 记录节点、模型、输入 hash、输出 hash、token、耗时、错误，不保存明文 prompt。 |
| `ToolCallAuditRecord` | `tools/executor.py` | 记录工具、节点、权限决策、参数 hash、结果 hash、耗时、错误。 |
| `SQLAlchemyLLMCallAuditRepository` | `graph_audit_repository.py` | 写入 `llm_call_records`。 |
| `SQLAlchemyToolCallAuditRepository` | `graph_audit_repository.py` | 写入 `tool_call_records`。 |

## 4. 编排流程

```text
ResearchService.run_delta_review(context_snapshot_id)
  -> load frozen ResearchContextSnapshot
  -> decide ReviewMode
  -> create graph run audit row
  -> LangGraph
       route_context
       evidence_plan
       retrieve_evidence
       fundamental_analysis
       valuation_analysis
       risk_review
       counter_argument
       analysis_join
       additional_evidence_retrieval?
       targeted_reanalysis?
       delta_decision
       citation_validation
       repair_decision?
       finalize
  -> persist ResearchDeltaReview + outbox event
```

路由规则：

- `CARRY_FORWARD_FAST_PATH`：上下文无实质变化且有效结论仍可引用，直接进入 finalize。
- `REVIEW_DEFERRED`：外部依赖短期不可用或预算/限流阻塞，保留上一有效结论指针并标记延期。
- `ABSTAIN`：关键输入缺失、PIT 违规、证据不可校验或策略禁止输出时拒绝产生新结论。
- `DELTA_REVIEW` / `FULL_REVIEW`：进入完整分析链路，最终必须经过引用校验。

## 5. 工具权限系统

工具系统不向模型暴露全局工具集合。每个节点执行前由 `ScopedToolFactory.create(...)` 生成当前节点可见的 `ToolManifest`。

| 组件 | 说明 |
| --- | --- |
| `ToolDefinitionRegistry` | 注册工具定义、参数 schema、返回 schema、所需权限和是否可被 LLM 看见。 |
| `ScopedToolFactory` | 按 node name、execution context、policy version、budget 生成当前节点工具清单。 |
| `ToolPolicyEngine` | 默认拒绝；校验工具是否属于节点白名单、是否越权、是否跨 scope/security、是否超预算和 deadline。 |
| `ToolExecutor` | 统一执行入口；调用前策略校验，调用后截断超大结果并写 hash-only 审计。 |

当前设计原则：

- 图内工具只读。
- Analysis Mart 工具只读第四层 `analysis_*` 表，按 security/scope/PIT 查最新可见快照或子行；跨证券、未来快照或不存在的 snapshot 返回空结果。
- AI 节点不能发起实时 WebSearch；新闻/WebSearch 由上游 refresh 流程存储后作为快照进入上下文。
- 工具结果只能作为证据或计算输入，不能覆盖系统提示词、策略权限或输出 schema。

当前内置第四层 Mart 工具：

| 工具 | capability | 输入 | 输出 |
| --- | --- | --- | --- |
| `analysis_snapshot_get` | `QUANT_READ` | `security_id`, `scope_version_id`, `decision_at` | 最新可见 `AnalysisSnapshot` 或 `null`。 |
| `analysis_metrics_list` | `QUANT_READ` | `security_id`, `decision_at`, `analysis_snapshot_id` | 该 snapshot 的结构化 metrics；无权限或不存在返回空列表。 |
| `analysis_findings_list` | `QUANT_READ` | `security_id`, `decision_at`, `analysis_snapshot_id` | 该 snapshot 的结构化 findings；无权限或不存在返回空列表。 |
| `quant_feature_snapshot_get` | `QUANT_READ` | `scope_version_id`, `decision_at` | 最新可见 `QuantFeatureSnapshot` 元数据或 `null`，不返回全市场明细。 |
| `quant_feature_rows_list` | `QUANT_READ` | `security_id`, `decision_at`, `feature_snapshot_id` | 当前 scoped security 在该 feature snapshot 中的特征行；跨 security 或未来时间被策略拒绝。 |

默认 `ResearchService` 在传入 `session_factory` 且未显式提供 repository 时，会构造 `SQLAlchemyAnalysisMartRepository` 并把这些工具注册进默认 registry。`valuation_analysis` 节点拥有 `QUANT_READ` grant，因此可以读取第四层 Mart；其他节点仍按 node grant 限制。

当前 RAG evidence 工具：

| 工具 | capability | 输入 | 输出 |
| --- | --- | --- | --- |
| `rag_evidence_retrieve` | `EVIDENCE_RETRIEVE` | `security_id`, `decision_at`, `query`, `questions`, `evidence_gaps`, `doc_types`, `top_k`, `prefer_official`, `supplemental`, `build_package` | PIT-safe `evidence_blocks`、稳定 `evidence_ids`、检索 query 元数据，以及可选 EvidencePackage 的 `package_id/version/quality_status/coverage`。 |
| `evidence_retrieve` | `EVIDENCE_RETRIEVE` | 同上；未接入 RAG 依赖时保留旧版 `questions/evidence_gaps/supplemental` 上下文读取输入 | 接入 RAG 依赖时是 `rag_evidence_retrieve` 的兼容别名；未接入时返回冻结 context payload 中已有的 evidence package 引用。 |

`ResearchService` 支持通过 `rag_retrieval_tool`、`rag_evidence_package_builder`
和 `rag_scope_hash_factory` 注入 RAG 检索依赖。默认图构造时，如果提供
`rag_retrieval_tool`，`retrieve_evidence` 与 `additional_evidence_retrieval` 节点看到
`evidence_retrieve` 兼容名和 `rag_evidence_retrieve` 显式名；如果未提供，则继续使用
旧版冻结 context 读取工具。

RAG 工具自身不直接发起 WebSearch，只读取已经索引入 `04-text_indexing` 的向量块；
跨证券、未来 `decision_at`、越权节点和超预算调用仍由 `ToolPolicyEngine` 与底层
`RetrievalTool`/`EvidencePackageBuilder` 共同拒绝或过滤。

## 6. Prompt 工厂

`PromptFactory` 保证所有节点提示词具有固定 section 顺序：

1. `SYSTEM SAFETY`
2. `NODE TASK`
3. `STRATEGY AND USER STYLE`
4. `CONTEXT SUMMARY`
5. `EVIDENCE PACKAGE`
6. `TOOL MANIFEST`
7. `OUTPUT SCHEMA`
8. `BUDGET AND STOP RULES`
9. `UNTRUSTED DATA BLOCK`

外部新闻、公告、网页和用户可配置文本只能进入 untrusted block。节点只接受结构化 JSON 输出，解析失败或 citation 失败会进入 revision/repair 或最终 ABSTAIN。

## 7. 服务入口与 API

当前 `06-multi_agent_research` 不直接暴露 FastAPI 路由。它由 valuation discovery / dashboard / worker 等上游模块调用服务或 repository。

| 入口 | 说明 |
| --- | --- |
| `ResearchService.run_delta_review(context_snapshot_id)` | 生产 AI 复核入口。 |
| `build_production_analysis_handlers(...)` | 构造真实 LLM 分析节点 handler。 |
| `build_production_decision_handler(...)` | 构造真实 LLM 决策 handler。 |
| `build_production_citation_validator(...)` | 构造 evidence-bound 引用校验器。 |

已删除入口：

- `POST /api/v1/research/run`
- `GET /api/v1/research/tools`
- `src/margin/research/workflow.py`
- `src/margin/research/agents.py`
- `src/margin/research/production_tools.py`
- `src/margin/research/tools/legacy.py`

## 8. 验证

核心测试覆盖：

- review mode 路由；
- LangGraph 正常/延期/拒绝/修复路径；
- checkpoint identity hash 与 pending writes 恢复；
- scoped tool permission；
- Analysis Mart tool scope/security/PIT 限制；
- prompt factory section 顺序与 untrusted data 隔离；
- node runner 反思、revision 与 evidence ID 约束；
- delta review repository 与 outbox 幂等；
- 真实 LLM smoke 的缺配置失败语义。

常用命令：

```bash
pytest -q tests/research
python scripts/smoke_ai_delta_review.py --mode carry
python scripts/smoke_ai_delta_review.py --mode delta
python scripts/smoke_ai_delta_review.py --mode full
python scripts/smoke_ai_delta_review.py --mode delta --require-real-llm
```

`--require-real-llm` 要求 `MARGIN_LLM_API_KEY`、`MARGIN_LLM_BASE_URL`、`MARGIN_LLM_MODEL` 可用；缺配置时脚本以外部阻塞退出，不使用离线 handler 冒充真实调用。

## 9. 跨模块关系

| 上游/下游 | 关系 |
| --- | --- |
| `01-data_provider` | 提供 PIT 数据快照和量化输入；研究模块不直接采集外部数据。 |
| `03-filing_websearch` | 新闻/公告 refresh 先落库，再作为冻结上下文进入研究。 |
| `04-text_indexing` / `05-rag_evidence` | 提供可定位、可校验的 EvidencePackage。 |
| `07-strategy_config` | 提供策略、prompt、工具权限和 scope 版本。 |
| `08-research_candidate_dashboard` | 展示 current review、effective assessment、证据摘要，并把首页问答请求提交给 MainAgent API。 |
| `11-valuation_discovery` | 发布 Analysis Mart 第四层，触发量化通过公司池的新闻、RAG 和 AI delta review，并发布有效 assessment 指针。 |
