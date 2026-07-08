# 06-multi_agent_research — Multi-Agent Research

This module lets Agents combine quant output, evidence, risk review, and user questions.

## What It Does

- `src/margin/agents/` provides the new three-layer Agent protocol and control plane: L1 MainAgent -> L2 Domain ExpertAgent -> L3 WorkerAgent.
- MainAgent plans, dispatches, and performs final review. Domain ExpertAgents decompose work inside one domain. WorkerAgents execute concrete capabilities and write artifacts.
- CapabilityToken, DataAccessPolicy, and ToolPolicy control what Agents may read, write, and call.
- ContextPack, DomainContextCapsule, and AuditReport make context transfer, compression, and final output traceable.
- The old `src/margin/agent_runtime/` package remains the compatibility execution entry point for the API, worker, and Dashboard.

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

- The Q&A planner only sees WorkerAgent cards that have registered executors.
- `CodeSandboxAgent` is hidden from the planner by default and only becomes visible after an executable executor is registered.
- Q&A execution status is tracked by `step_id`, so multiple steps from the same Agent do not overwrite each other.
- Artifact detail API responses use a safe view by default and redact or truncate secrets, tokens, and long raw payload fields.
- MainAgent final review checks artifact existence, payload hash, expected producer/type, evidence/source reference boundaries, and writes a `final_audit_report` artifact.

## Main Entry Points

- `src/margin/agents/`
- `src/margin/agent_runtime/`
- `src/margin/research/`
- `src/margin/prompts/`
- `src/margin/api/routes/agent_runtime.py`

## Who Uses It

Dashboard shows Agent state and adjusted recommendations. The home page Q&A reads Agent output and evidence references.
