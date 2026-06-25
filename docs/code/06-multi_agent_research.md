# 06-multi_agent_research 模块文档

本文件描述当前仓库中的多 Agent 研究流程实现。v0.2 已删除 v0.1 的同步 `ResearchWorkflow`、12 个顺序 Agent、全局工具注册表兼容入口以及 `/api/v1/research/run`、`/api/v1/research/tools` API；当前模块只承担“冻结上下文进入 LangGraph delta review，输出可审计研究复核结果”的职责。

## 1. 模块职责

`src/margin/research/` 负责消费上游冻结的 `ResearchContextSnapshot`，在确定性路由与受限工具权限下执行 AI delta review，并把本轮结论、引用校验、LLM 调用、工具调用和 outbox 事件持久化。

当前边界：

- 输入：已冻结的研究上下文快照 ID，不直接抓行情、搜索新闻或读取用户前端临时状态。
- 编排：LangGraph 图，含路由、证据计划、检索、基本面分析、估值分析、风险复核、反方论证、决策、引用校验、修复与 finalize。
- 工具：通过 `ScopedToolFactory`、`ToolPolicyEngine`、`ToolExecutor` 按节点生成最小权限工具清单；包含 Analysis Mart 三个只读工具；默认拒绝越权、跨 scope、跨 security、PIT 违规、预算超限和 deadline 过期。
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
| `src/margin/research/graph/routing.py` | 根据快照差异、证据状态、provider 状态和策略约束确定 review mode。 |
| `src/margin/research/graph/builder.py` | 构建 AI delta review LangGraph 拓扑。 |
| `src/margin/research/graph/nodes/` | context、evidence、analysis、decision 等节点实现。 |
| `src/margin/research/execution/llm_service.py` | LLM 调用服务，记录 hash-only prompt/output 审计。 |
| `src/margin/research/execution/node_runner.py` | 带反思机制的节点执行器。 |
| `src/margin/research/execution/reflection.py` | 节点 draft/critic/revision 结果结构。 |
| `src/margin/research/execution/model_router.py` | 节点到模型任务的路由。 |
| `src/margin/research/prompts/` | Prompt 模型、仓库与工厂。 |
| `src/margin/research/tools/definitions.py` | 工具定义、权限级别、工具参数与执行上下文。 |
| `src/margin/research/tools/factory.py` | 按节点和上下文生成 scoped tool manifest。 |
| `src/margin/research/tools/policy.py` | 默认拒绝的工具权限策略。 |
| `src/margin/research/tools/executor.py` | 统一工具执行器，执行前校验策略并写审计。 |
| `src/margin/research/tools/manifests.py` | 面向 LLM 的工具 manifest 结构。 |
| `src/margin/research/analysis_tools.py` | 注册 `analysis_snapshot_get`、`analysis_metrics_list`、`analysis_findings_list`、`quant_feature_snapshot_get`、`quant_feature_rows_list` 五个第四层 Mart 只读工具。 |
| `src/margin/research/checkpoint.py` | PostgreSQL LangGraph checkpoint saver，校验 identity hash 并恢复 pending writes。 |
| `src/margin/research/delta_repository.py` | `ResearchDeltaReview` 与 `research_delta_outbox` 的内存/PostgreSQL 持久化。 |
| `src/margin/research/graph_audit_repository.py` | LLM/tool 调用审计 PostgreSQL repository。 |
| `src/margin/research/production_graph.py` | 生产分析 handler、决策 handler 和引用校验器构造。 |
| `src/margin/research/db_models.py` | graph run、node run、checkpoint、tool call、LLM call、delta review、outbox 表。 |
| `scripts/smoke_ai_delta_review.py` | AI delta review smoke，支持 carry/delta/full 和真实 LLM 要求模式。 |

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
| `08-research_candidate_dashboard` | 展示 current review、effective assessment、证据 locator 与只读 Copilot。 |
| `11-valuation_discovery` | 发布 Analysis Mart 第四层，触发量化通过公司池的新闻、RAG 和 AI delta review，并发布有效 assessment 指针。 |
