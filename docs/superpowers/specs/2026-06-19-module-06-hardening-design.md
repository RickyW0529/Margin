# Module 06 Hardening Design

## 1. Goal

Bring `06-multi_agent_research` from a runnable prototype to the v0.1 acceptance
boundary defined by its spec and plans. The repair is limited to the research
module, its API wiring, and its tests.

## 2. Scope

Included:

- `src/margin/research/`
- `src/margin/api/routes/research.py`
- Research-related dependency wiring in `src/margin/api/`
- `tests/research/` and `tests/api/test_research.py`
- Research persistence models/repository owned by module 06

Excluded:

- v0.2 multi-provider configuration UI
- Changes to modules 01–05, 07–10
- MCP or custom HTTP tools
- General refactoring unrelated to module 06
- Real network smoke tests requiring external credentials

Existing modules are consumed through their public interfaces. Module 06 must not
duplicate evidence validation, Provider resilience, portfolio calculations, or
document acquisition logic already implemented elsewhere.

## 3. Architecture

### 3.1 Provider and model routing

`ModelRouter` selects a registered LLM Provider for each `TaskType`. Selection
uses explicit task mapping and an ordered fallback chain. Provider calls go
through the existing `ProviderRegistry`, which owns Secret injection, retries,
fallback execution, health checks, cost metadata, and audit logging.

The workflow must not instantiate an unregistered network client implicitly.
When no suitable Provider exists, LLM-dependent nodes return a structured
failure and the workflow degrades to `ABSTAINED`.

### 3.2 Tool system

`ToolRegistry` contains typed, code-defined tools only. It enforces:

- `read`: executable without confirmation;
- `write_with_confirm`: requires an explicit confirmation flag;
- `forbidden`: never executable.

Every call creates an immutable `ToolCallRecord` containing parameters, success,
output hash, error, latency, timestamp, and trace ID. Sensitive values are
redacted before audit storage.

Production defaults must not return fabricated successful financial data.
Unconfigured adapters return explicit failures. Tests may register deterministic
fake tools.

### 3.3 Agent execution

Each Agent receives a task-specific Provider selected by the router and a
permission-aware Tool Registry. Every Agent output records:

- actual input hash;
- actual output hash;
- selected Provider/model version;
- tool-call audit references;
- latency and error.

Critical node failures cannot be silently ignored:

- universe or quantitative preparation failure → `ABORTED`;
- missing/invalid evidence → `ABSTAINED`;
- required LLM analysis/review failure → `ABSTAINED`;
- citation validation failure → `ABSTAINED`;
- portfolio violation → an `ABSTAINED` signal.

Only a fully validated signal may reach `PUBLISHED`.

### 3.4 Evidence and citation validation

The Citation Validator Agent delegates to module 05's `CitationValidator`.
It validates Claims against actual Evidence records using:

- reference existence;
- source level restrictions;
- point-in-time correctness;
- original-source locator and snapshot requirements;
- conflicts and confidence caps.

A non-empty string reference is not sufficient. The workflow must carry
`Claim` and `Evidence` objects through `AgentContext`, and persist their IDs in
the research snapshot.

### 3.5 Document collection

The Document Collector consumes already acquired compliant source records or a
typed collector adapter. It must preserve source URL, publication/availability
time, snapshot ID/hash, content hash, and acquisition status. It must never
claim a document was collected by hashing search-result metadata alone.

When no collector is configured, the node may reuse existing compliant
snapshots supplied in the context; otherwise it returns a structured failure or
empty result that leads to `ABSTAINED`.

### 3.6 Structured output

LLM responses are parsed into Pydantic output models or validated against the
declared JSON Schema. Validation covers required fields, types, nested items,
enums, and numeric bounds. Invalid output is a node failure.

### 3.7 Snapshot and persistence

Every terminal state—`PUBLISHED`, `ABSTAINED`, and `ABORTED`—produces a research
snapshot. The snapshot freezes:

- run and terminal state;
- symbols and decision time;
- strategy and Prompt versions;
- Provider/model and tool versions;
- retrieval results, Evidence IDs, and Claim IDs;
- Agent traces and tool-call records;
- structured signals and errors;
- canonical input/output hashes.

Snapshot collections use immutable tuples/frozen mappings or defensive deep
copies so nested mutation cannot invalidate stored hashes.

Module 06 owns an append-only repository interface. The default in-memory
repository supports local execution and tests; a SQLAlchemy repository persists
research runs, snapshots, signals, traces, and tool-call audit records without
allowing updates to an existing snapshot ID.

## 4. API behavior

- `POST /research/run` returns `200` for `PUBLISHED` and `ABSTAINED`.
- It returns `422` for `ABORTED`.
- The response includes the snapshot ID when a terminal snapshot was persisted.
- `GET /research/tools` uses a public service method and returns tool metadata,
  including permission, without accessing private service attributes.
- Invalid or empty symbols are rejected by request validation.

## 5. Error handling

- External Provider and tool errors are recorded without leaking credentials.
- No exception path may publish a candidate signal.
- A workflow-level unexpected exception produces an `ABORTED` snapshot before
  returning.
- Snapshot persistence failure is surfaced as `ABORTED`; a run is not reported
  as successfully published without its audit snapshot.

## 6. Testing

Tests must prove:

- all LLM nodes failing cannot publish a candidate;
- unconfigured production tools never return fabricated success;
- write tools require confirmation and forbidden tools cannot run;
- every tool invocation creates an audit record;
- invalid Evidence IDs and point-in-time violations fail citation validation;
- malformed JSON output fails schema validation;
- model routing uses the selected Provider and fallback path;
- every terminal state has a persisted snapshot;
- snapshot nested data cannot be mutated;
- trace hashes are populated;
- API responses expose terminal state and snapshot identity correctly.

All existing module 06 tests remain green after being tightened. Relevant tests
from core Provider Registry, evidence validation, vector retrieval, portfolio,
and API routing run as regression coverage.

## 7. Acceptance

Module 06 is complete when:

- no critical path uses successful placeholder financial or WebSearch data;
- no failed LLM or citation path can produce `PUBLISHED`;
- model and tool calls are permission-controlled and auditable;
- module 05 performs the actual citation validation;
- all terminal workflow runs have immutable, append-only snapshots;
- lint and all relevant tests pass.
