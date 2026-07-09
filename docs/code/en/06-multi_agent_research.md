# 06-multi_agent_research — Multi-Agent Research

This module lets Agents combine quant output, evidence, risk review, and user questions.

## What It Does

- `src/margin/agents/` provides the new three-layer Agent protocol and control plane: L1 MainAgent -> L2 Domain ExpertAgent -> L3 WorkerAgent.
- MainAgent plans, dispatches, and performs final review. Domain ExpertAgents decompose work inside one domain. WorkerAgents execute concrete capabilities and write artifacts.
- CapabilityToken, DataAccessPolicy, and ToolPolicy control what Agents may read, write, and call.
- ContextPack, DomainContextCapsule, and AuditReport make context transfer, compression, and final output traceable.
- Context Engineering has a dedicated repository and `agent.context_*` tables, so ContextPack/fact/omission/capsule/lineage records are not hidden only inside artifact payloads.
- ToolGateway centralizes tool registration, authorization, idempotency, redaction, and audit. LangGraph tools/nodes must go through the ToolGateway wrapper.
- PromptBundle / PromptRegistry / PromptRenderer manage v1 system prompts, variable validation, and render hashes. PromptBundle, render history, and LLM call audit now have `prompt.*` persistence boundaries.
- The Q&A API now uses `AgentRuntimeService`, which produces user answers through the v1 `GlobalPlan -> DomainContextCapsule -> FinalAudit -> FinalUserAnswerArtifact` path.
- Scheduled stock research now uses `ScheduledAgentRuntimeRunner`, which writes a v1 scheduled global plan before triggering valuation refresh.
- The old `src/margin/agent_runtime/` package remains only for chat/context/schedule persistence models, historical MainAgent tests, and the old flow loader. It is no longer an API or worker orchestration entry point.

## How It Runs

```text
user or scheduled trigger
  -> MainAgent plan
  -> data inspection
  -> quant branch + filing/RAG branch
  -> fusion research
  -> write Dashboard projection
  -> MainAgent final check
```

The quant branch reads structured PIT data and marts only; it does not use WebSearch. The filing/RAG branch checks coverage first and refreshes missing or stale materials only when needed. The sentiment branch currently uses WebSearch for incremental thesis validation.

Agents should not read raw/source tables directly or bypass Evidence and Analysis Mart.

## Current Safety Boundaries

- The user Q&A endpoint and worker scheduler no longer depend directly on the old MainAgent runtime or legacy ExpertAgent executors.
- The Q&A service uses v1 MainRuntime for domain-task planning and persists context pack, domain capsule, domain audit, final audit, and final answer artifacts.
- The Q&A service also writes ContextPack, DomainContextCapsule, and lineage edges into the structured ContextRepository.
- The scheduled runner maps the fixed flow to v1 DomainTasks and persists `scheduled_global_plan` and `valuation_refresh` artifacts.
- `CodeSandboxAgent` is hidden from the planner by default and only becomes visible after an executable executor is registered.
- Q&A execution status is tracked by `step_id`, so multiple steps from the same Agent do not overwrite each other.
- Artifact detail API responses use a safe view by default and redact or truncate secrets, tokens, and long raw payload fields.
- The API exposes `context-packs/{id}`, `runs/{id}/context-graph`, and `artifacts/{id}/safe` safe views with structured context, metadata, hashes, and redacted content only.
- ToolGateway audit is persisted to `tool.tool_calls` and `tool.tool_results`; the API only returns redacted input/output and hashes.
- Prompt render history and LLM call audit store only hashes, model metadata, token counts, status, and timestamps, not raw prompt text or model response payloads.
- MainAgent final review checks artifact existence, payload hash, expected producer/type, evidence/source reference boundaries, and writes a `final_audit_report` artifact.

## Main Entry Points

- `src/margin/agents/`
- `src/margin/agents/context/repository.py`
- `src/margin/agents/context/db_models.py`
- `src/margin/agents/tools/`
- `src/margin/agents/tools/langgraph_adapter.py`
- `src/margin/agents/prompts/`
- `src/margin/agents/prompts/repository.py`
- `src/margin/agents/prompts/db_models.py`
- `src/margin/agents/runtime/service.py`
- `src/margin/agents/runtime/scheduled.py`
- `src/margin/agents/workers/dashboard_publisher_worker.py`
- `src/margin/agents/domains/`, `src/margin/agents/workers/`
- `src/margin/agent_runtime/` for historical chat/context/schedule persistence and the old flow loader.
- `src/margin/research/`
- `src/margin/prompts/`
- `src/margin/api/routes/agent_runtime.py`
- `src/margin/api/routes/context.py`
- `src/margin/api/routes/tool_audit.py`

## Who Uses It

Dashboard shows Agent state and adjusted recommendations. The home page Q&A reads Agent output and evidence references.
