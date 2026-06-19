# Module 06 Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make module 06 fail closed, use real module boundaries, enforce tool permissions, validate citations, and persist immutable snapshots for every terminal workflow state.

**Architecture:** Keep the existing research package, but replace successful placeholder behavior with injected typed adapters. Route LLM calls through the existing Provider Registry, delegate evidence checks to module 05, and finalize every workflow through one append-only snapshot path.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2, FastAPI, httpx, pytest, Ruff.

---

### Task 1: Lock regression behavior with failing tests

**Files:**
- Create: `tests/research/test_hardening.py`
- Modify: `tests/research/test_tools.py`
- Modify: `tests/research/test_llm.py`
- Modify: `tests/research/test_workflow.py`
- Modify: `tests/api/test_research.py`

- [ ] **Step 1: Add tests for fail-closed workflow behavior**

Add tests asserting that all LLM Providers failing results in `ABSTAINED`, that
invalid citation IDs fail validation, and that `ABSTAINED` and `ABORTED` runs
both contain persisted snapshots.

- [ ] **Step 2: Add tests for tool permissions and audit**

Test:

```python
result = registry.call("alert", {"message": "x"})
assert result.success is False
assert result.error == "confirmation required"
assert registry.audit_records[-1].success is False
```

Also assert unconfigured market/financial/factor/WebSearch tools fail instead of
returning placeholder data.

- [ ] **Step 3: Add tests for schema validation and deep immutability**

Test wrong scalar types, enum violations, nested array item types, and attempts
to mutate snapshot tuples.

- [ ] **Step 4: Run tests and verify RED**

Run:

```bash
pytest -q tests/research tests/api/test_research.py
```

Expected: failures demonstrating the reviewed defects.

### Task 2: Harden tools and Provider routing

**Files:**
- Modify: `src/margin/research/tools.py`
- Modify: `src/margin/research/llm.py`
- Modify: `src/margin/research/service.py`
- Test: `tests/research/test_tools.py`
- Test: `tests/research/test_llm.py`

- [ ] **Step 1: Implement permission-aware Tool Registry**

Add:

```python
class ToolPermission(StrEnum):
    READ = "read"
    WRITE_WITH_CONFIRM = "write_with_confirm"
    FORBIDDEN = "forbidden"
```

`ToolRegistry.call()` accepts `trace_id` and `confirmed`, enforces permission,
redacts sensitive parameters, and appends a `ToolCallRecord` for success,
failure, not-found, and denied calls.

- [ ] **Step 2: Replace successful stubs with typed adapters**

Market, financial, factor, portfolio, WebSearch, filing, calendar, alert, and
backtest tools accept injected callables. Missing callables return
`"<tool> adapter not configured"` with `success=False`.

- [ ] **Step 3: Integrate Model Router with Provider Registry**

`LLMProvider` exposes a registry-callable method that raises `ProviderError` on
failure. `ModelRouter.complete()` selects a task route and calls the existing
`ProviderRegistry`, preserving retries, fallback, audit, and actual selected
Provider metadata.

- [ ] **Step 4: Implement recursive schema validation**

Validate JSON Schema object properties, required fields, arrays/items, scalar
types, enum, minimum, and maximum.

- [ ] **Step 5: Run focused tests**

Run:

```bash
pytest -q tests/research/test_tools.py tests/research/test_llm.py
```

Expected: PASS.

### Task 3: Connect evidence validation and fail-closed Agent execution

**Files:**
- Modify: `src/margin/research/agents.py`
- Modify: `src/margin/research/workflow.py`
- Test: `tests/research/test_agents.py`
- Test: `tests/research/test_workflow.py`
- Test: `tests/research/test_hardening.py`

- [ ] **Step 1: Record real Agent hashes and tool-call IDs**

Hash the Agent input context before execution and structured output after
execution. Copy Tool Registry audit IDs into the Agent trace.

- [ ] **Step 2: Make data tools fail closed**

Universe and quantitative agents fail when required adapters fail. They must not
fall back to the unverified input universe or fabricated factor scores.

- [ ] **Step 3: Carry Claims and Evidence through the workflow**

Evidence Research accepts preloaded module 05 objects or converts valid
retrieval chunks into `Evidence` plus `Claim` records. It outputs Evidence and
Claim IDs, not raw unvalidated string references.

- [ ] **Step 4: Delegate citation checks to module 05**

`CitationValidatorAgent` calls:

```python
CitationValidator(snapshot_resolver=resolver).validate_batch(
    context.claims,
    context.evidences,
    context.decision_at,
)
```

It returns validation status, failure reasons, confidence caps, and
counter-review requirements.

- [ ] **Step 5: Enforce terminal-state rules**

Required LLM analysis/review failure, invalid evidence, or an abstained composed
signal leads to `WorkflowState.ABSTAINED`. Only validated non-abstained signals
reach `PUBLISHED`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
pytest -q tests/research/test_agents.py tests/research/test_workflow.py tests/research/test_hardening.py
```

Expected: PASS.

### Task 4: Persist immutable terminal snapshots

**Files:**
- Modify: `src/margin/research/models.py`
- Modify: `src/margin/research/snapshot.py`
- Create: `src/margin/research/db_models.py`
- Create: `src/margin/research/repository.py`
- Modify: `src/margin/research/workflow.py`
- Modify: `src/margin/research/service.py`
- Test: `tests/research/test_snapshot.py`
- Create: `tests/research/test_repository.py`

- [ ] **Step 1: Convert nested snapshot collections to immutable values**

Use tuples and frozen child models for symbols, versions, Evidence IDs, Claim
IDs, signals, traces, and tool-call records.

- [ ] **Step 2: Build one terminal snapshot path**

Create `_finish(state, signals, error)` in `ResearchWorkflow`. It builds and
persists the snapshot for `PUBLISHED`, `ABSTAINED`, and `ABORTED`.

- [ ] **Step 3: Add append-only repositories**

Define `ResearchRepository`, `MemoryResearchRepository`, and
`SQLAlchemyResearchRepository`. Duplicate identical snapshots are idempotent;
attempted mutation under an existing ID raises `ValueError`.

- [ ] **Step 4: Add SQLAlchemy snapshot row**

Store snapshot ID, run ID, terminal state, canonical JSON payload, input/output
hashes, and created timestamp. No update method is exposed.

- [ ] **Step 5: Run snapshot/repository tests**

Run:

```bash
pytest -q tests/research/test_snapshot.py tests/research/test_repository.py
```

Expected: PASS.

### Task 5: Finish API boundary and verification

**Files:**
- Modify: `src/margin/api/dependencies.py`
- Modify: `src/margin/api/routes/research.py`
- Modify: `src/margin/research/service.py`
- Modify: `src/margin/research/__init__.py`
- Test: `tests/api/test_research.py`

- [ ] **Step 1: Expose public tool metadata**

Add `ResearchService.list_tools()` and stop reading `service._tools` from the
route.

- [ ] **Step 2: Return snapshot identity**

Add `snapshot_id` to `ResearchRunResponse`. Reject blank symbols with Pydantic
validation.

- [ ] **Step 3: Wire production repository**

Build the SQLAlchemy repository from the existing database session factory.
Build an LLM Provider/Router only from configured environment or Secret
references; absent configuration remains fail closed.

- [ ] **Step 4: Run complete verification**

Run:

```bash
ruff check src tests
pytest -q tests/research tests/api/test_research.py
pytest -q tests/core tests/evidence tests/vector tests/portfolio \
  --ignore=tests/evidence/test_repository_postgres.py \
  --ignore=tests/vector/test_repository_postgres.py \
  --ignore=tests/portfolio/test_repository_postgres.py
```

Expected: Ruff clean and all selected tests passing.

- [ ] **Step 5: Review the final diff**

Confirm no files outside module 06, research API wiring, and research tests were
changed by this repair.
