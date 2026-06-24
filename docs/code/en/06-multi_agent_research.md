# 06-multi_agent_research Module

This document describes the current multi-agent research implementation. v0.2 removed the v0.1 synchronous `ResearchWorkflow`, the 12 sequential agents, the global tool-registry compatibility entrypoint, and the `/api/v1/research/run` plus `/api/v1/research/tools` APIs. The current module consumes frozen research context snapshots, runs an auditable LangGraph delta review, and persists the review outcome.

## 1. Responsibilities

`src/margin/research/` takes a frozen `ResearchContextSnapshot`, routes it through deterministic review-mode selection, executes only scoped read-only tools, and persists the current AI review result together with LLM/tool audit records and outbox events.

Current boundaries:

- Input: a frozen context snapshot ID. The module does not fetch live market data, perform live news search, or read transient frontend state.
- Orchestration: LangGraph topology with context routing, evidence planning, retrieval, fundamental analysis, valuation analysis, risk review, counter-argument review, decision, citation validation, optional repair, and finalize.
- Tools: `ScopedToolFactory`, `ToolPolicyEngine`, and `ToolExecutor` expose only node-specific minimal tool manifests, including the three read-only Analysis Mart tools. Cross-scope, cross-security, PIT-invalid, over-budget, over-deadline, and unauthorized calls are denied by default.
- Prompts: `PromptFactory` produces fixed-section prompts. External text is always placed in an untrusted data block.
- Reflection: `NodeExecutionRunner` performs draft → deterministic validation → critic → at most one revision. Critic/revision cannot introduce new evidence IDs.
- Output: `ResearchDeltaReview`, which records the current review outcome and effective-assessment pointer. It never emits BUY/SELL instructions.

## 2. File Map

| Path | Current role |
| --- | --- |
| `src/margin/research/models.py` | Historical snapshot/signal models still read by dashboard compatibility aggregation. |
| `src/margin/research/llm.py` | OpenAI-compatible LLM provider, deterministic provider, model router, and structured-output guardrail. |
| `src/margin/research/service.py` | High-level service; production entrypoint is `ResearchService.run_delta_review(context_snapshot_id)`. |
| `src/margin/research/graph/state.py` | LangGraph state, review modes, review outcomes, node status, and graph event models. |
| `src/margin/research/graph/routing.py` | Deterministic review-mode routing. |
| `src/margin/research/graph/builder.py` | LangGraph topology builder. |
| `src/margin/research/graph/nodes/` | Context, evidence, analysis, and decision nodes. |
| `src/margin/research/execution/llm_service.py` | LLM execution service with hash-only audit. |
| `src/margin/research/execution/node_runner.py` | Node runner with reflection and one bounded revision. |
| `src/margin/research/execution/reflection.py` | Draft, critic, and revision result models. |
| `src/margin/research/execution/model_router.py` | Node-to-model task routing. |
| `src/margin/research/prompts/` | Prompt models, repository, and factory. |
| `src/margin/research/tools/definitions.py` | Tool definitions, permission levels, params, and execution context. |
| `src/margin/research/tools/factory.py` | Scoped tool manifest factory. |
| `src/margin/research/tools/policy.py` | Default-deny tool policy engine. |
| `src/margin/research/tools/executor.py` | Audited tool executor. |
| `src/margin/research/tools/manifests.py` | LLM-facing tool manifest DTOs. |
| `src/margin/research/analysis_tools.py` | Registers the read-only `analysis_snapshot_get`, `analysis_metrics_list`, and `analysis_findings_list` tools. |
| `src/margin/research/checkpoint.py` | PostgreSQL LangGraph checkpointer with identity-hash validation and pending-write recovery. |
| `src/margin/research/delta_repository.py` | Memory/PostgreSQL persistence for `ResearchDeltaReview` and `research_delta_outbox`. |
| `src/margin/research/graph_audit_repository.py` | PostgreSQL repositories for LLM/tool call audits. |
| `src/margin/research/production_graph.py` | Production analysis handlers, decision handler, and citation validator. |
| `src/margin/research/db_models.py` | Graph run, node run, checkpoint, tool call, LLM call, delta review, and outbox rows. |
| `scripts/smoke_ai_delta_review.py` | Carry/delta/full AI delta-review smoke script. |

## 3. Core Models

| Type | Role |
| --- | --- |
| `ReviewMode` | `FULL_REVIEW`, `DELTA_REVIEW`, `CARRY_FORWARD_FAST_PATH`, `REVIEW_DEFERRED`, `ABSTAIN`. |
| `ReviewOutcome` | `CARRY_FORWARD_VERIFIED`, `UPDATE_ASSESSMENT`, `DOWNGRADE_CONFIDENCE`, `INVALIDATE`, `ABSTAIN`, `REVIEW_DEFERRED`. |
| `AIDeltaGraphState` | Mutable graph state containing context, evidence, node outputs, citation validation, errors, and final review. |
| `ResearchDeltaReview` | Immutable final review record persisted at graph completion. |
| `LLMCallAuditRecord` | Hash-only LLM call audit; no plaintext prompt is stored. |
| `ToolCallAuditRecord` | Tool-call audit with policy decision and hashed params/result. |

## 4. Flow

```text
ResearchService.run_delta_review(context_snapshot_id)
  -> load frozen ResearchContextSnapshot
  -> determine ReviewMode
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

Routing semantics:

- `CARRY_FORWARD_FAST_PATH`: no material context change and the existing effective assessment is still citeable.
- `REVIEW_DEFERRED`: provider, budget, or rate-limit state prevents a safe review; the prior effective pointer is kept.
- `ABSTAIN`: critical inputs are missing, PIT is invalid, evidence cannot be validated, or strategy rules prohibit output.
- `DELTA_REVIEW` / `FULL_REVIEW`: full analysis path with mandatory citation validation.

## 5. Tool Permission System

The model never sees a global tool registry. Each node receives only the manifest generated for that node and execution context.

| Component | Role |
| --- | --- |
| `ToolDefinitionRegistry` | Registers tool schema, permission requirements, and visibility. |
| `ScopedToolFactory` | Builds node-specific `ToolManifest` objects. |
| `ToolPolicyEngine` | Default-deny policy for node allowlists, scope/security boundaries, PIT, budgets, and deadlines. |
| `ToolExecutor` | Validates policy, executes handlers, caps oversized results, and writes audit records. |

AI nodes are read-only. They cannot initiate live WebSearch; news/WebSearch data must be acquired by upstream refresh flows and enter research as stored snapshots.

Analysis Mart tools are read-only over the fourth-layer `analysis_*` tables. They enforce security/PIT boundaries by request shape: cross-security, future, or missing snapshots return empty results.

| Tool | Capability | Input | Output |
| --- | --- | --- | --- |
| `analysis_snapshot_get` | `QUANT_READ` | `security_id`, `scope_version_id`, `decision_at` | Latest visible `AnalysisSnapshot` or `null`. |
| `analysis_metrics_list` | `QUANT_READ` | `security_id`, `decision_at`, `analysis_snapshot_id` | Structured metrics for the snapshot; unauthorized or missing reads return an empty list. |
| `analysis_findings_list` | `QUANT_READ` | `security_id`, `decision_at`, `analysis_snapshot_id` | Structured findings for the snapshot; unauthorized or missing reads return an empty list. |

When `ResearchService` receives a `session_factory` and no explicit repository, it builds a `SQLAlchemyAnalysisMartRepository` and registers these tools in the default registry. The `valuation_analysis` node has the `QUANT_READ` grant, so it can read Analysis Mart while other nodes remain constrained by their node grants.

## 6. Prompt Factory

`PromptFactory` emits sections in this order:

1. `SYSTEM SAFETY`
2. `NODE TASK`
3. `STRATEGY AND USER STYLE`
4. `CONTEXT SUMMARY`
5. `EVIDENCE PACKAGE`
6. `TOOL MANIFEST`
7. `OUTPUT SCHEMA`
8. `BUDGET AND STOP RULES`
9. `UNTRUSTED DATA BLOCK`

News, filings, webpages, and user-configurable content can only appear in the untrusted block. Nodes return structured JSON; parse failures or citation failures trigger bounded revision/repair or final abstention.

## 7. Service Entry Points

Module 06 currently exposes no FastAPI router directly. It is invoked by valuation discovery, dashboard, and worker orchestration code.

| Entry point | Role |
| --- | --- |
| `ResearchService.run_delta_review(context_snapshot_id)` | Production AI review entrypoint. |
| `build_production_analysis_handlers(...)` | Builds real LLM-backed analysis node handlers. |
| `build_production_decision_handler(...)` | Builds the real LLM-backed decision handler. |
| `build_production_citation_validator(...)` | Builds the evidence-bound citation validator. |

Removed entrypoints:

- `POST /api/v1/research/run`
- `GET /api/v1/research/tools`
- `src/margin/research/workflow.py`
- `src/margin/research/agents.py`
- `src/margin/research/production_tools.py`
- `src/margin/research/tools/legacy.py`

## 8. Verification

Covered by tests for review routing, graph execution, checkpoint recovery, scoped tool policy, Analysis Mart tool security/PIT reads, prompt ordering, node reflection, delta-review persistence, outbox idempotency, and real-LLM smoke failure semantics.

Useful commands:

```bash
pytest -q tests/research
python scripts/smoke_ai_delta_review.py --mode carry
python scripts/smoke_ai_delta_review.py --mode delta
python scripts/smoke_ai_delta_review.py --mode full
python scripts/smoke_ai_delta_review.py --mode delta --require-real-llm
```

`--require-real-llm` requires `MARGIN_LLM_API_KEY`, `MARGIN_LLM_BASE_URL`, and `MARGIN_LLM_MODEL`. Missing config exits as an external blocker; the script does not silently substitute an offline handler.

## 9. Cross-Module Notes

| Module | Relationship |
| --- | --- |
| `01-data_provider` | Supplies PIT data snapshots and quant inputs; module 06 does not collect external data directly. |
| `03-filing_websearch` | News/filing refresh persists snapshots before research sees them. |
| `04-text_indexing` / `05-rag_evidence` | Provide citeable evidence packages and locators. |
| `07-strategy_config` | Provides strategy, prompt, tool-policy, and scope versions. |
| `08-research_candidate_dashboard` | Displays current review, effective assessment, locators, and read-only Copilot output. |
| `11-valuation_discovery` | Publishes the fourth-layer Analysis Mart, orchestrates quant-passed companies through news, RAG, and AI delta review, then publishes effective assessment pointers. |
