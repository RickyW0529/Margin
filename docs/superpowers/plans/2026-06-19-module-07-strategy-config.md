# Module 07 Strategy Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the strategy configuration module (07) that lets users define, version, validate, and activate investment strategies, including built-in templates, layered prompts, guardrails, and a lifecycle state machine.

**Architecture:** A `StrategyService` exposes create/update/activate operations over a `StrategyRepository`. Strategies are immutable `StrategyVersion` snapshots referenced by a mutable `StrategyProfile`. `StrategyConfig` is validated by `StrategyValidator`, prompts are layered by `PromptLayerBuilder`, and lifecycle transitions are handled by `StrategyLifecycle` with a lightweight `StrategySandbox`.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, pytest, ruff.

---

## Task 1: Domain models

**Files:**
- Create: `src/margin/strategy/models.py`
- Test: `tests/strategy/test_models.py`

- [ ] **Step 1: Write failing test**

```python
def test_strategy_version_is_immutable():
    from margin.strategy.models import StrategyVersion, StrategyState, StrategyConfig
    version = StrategyVersion(
        strategy_id="st_001",
        version_id="sv_001",
        name="Value Quality",
        config=StrategyConfig(),
        state=StrategyState.DRAFT,
    )
    assert version.state == StrategyState.DRAFT
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/strategy/test_models.py::test_strategy_version_is_immutable -v
```
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement models**

Create `src/margin/strategy/models.py` with:
- `StrategyState` enum: DRAFT, VALIDATING, INVALID, BACKTESTING, PAPER_TRADING, ACTIVE, ARCHIVED, SUSPENDED.
- `StrategyConfig` Pydantic model with fields: `universe` (list[str]), `horizon` (int days), `valuation`, `quality`, `risk`, `ai` (provider/model/websearch_provider/system_prompt_template/custom_instructions), `evidence` (required_levels/min_evidence_count), `decision` (research_states/position_review_states/prohibited_outputs).
- `PromptLayer` Pydantic model with `layer`, `content`, `editable`.
- `StrategyVersion` frozen Pydantic model with `strategy_id`, `version_id`, `name`, `description`, `config`, `prompt_layers`, `state`, `created_at`, `prompt_version`.
- `StrategyProfile` Pydantic model with `strategy_id`, `owner_id`, `name`, `active_version_id`, `versions`, `created_at`, `updated_at`.
- `StrategySandboxResult` model with validation/sample/backtest/data_leak/cost/preview flags and messages.

- [ ] **Step 4: Run tests**

```bash
pytest tests/strategy/test_models.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/margin/strategy/models.py tests/strategy/test_models.py
git commit -m "feat(strategy): add domain models for strategy config"
```

---

## Task 2: Built-in strategy templates

**Files:**
- Create: `src/margin/strategy/templates.py`
- Test: `tests/strategy/test_templates.py`

- [ ] **Step 1: Write failing test**

```python
def test_value_quality_template_has_universe():
    from margin.strategy.templates import BUILTIN_TEMPLATES
    template = BUILTIN_TEMPLATES["value_quality"]
    assert "000001.SZ" in template.config.universe
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement templates**

Create `src/margin/strategy/templates.py` with 6 built-in templates:
- value_quality
- undervalued_recovery
- high_dividend
- growth_at_reasonable_price
- cyclical_reversal
- custom

Each returns a `StrategyConfig` with sensible defaults. `custom` is a minimal empty-ish template.

- [ ] **Step 4: Run tests**

```bash
pytest tests/strategy/test_templates.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/margin/strategy/templates.py tests/strategy/test_templates.py
git commit -m "feat(strategy): add built-in strategy templates"
```

---

## Task 3: Schema validation and guardrails

**Files:**
- Create: `src/margin/strategy/validator.py`
- Test: `tests/strategy/test_validator.py`

- [ ] **Step 1: Write failing test**

```python
def test_validator_rejects_prohibited_output():
    from margin.strategy.models import StrategyConfig
    from margin.strategy.validator import StrategyValidator
    config = StrategyConfig(decision={"prohibited_outputs": ["GUARANTEED_RETURN"]})
    ok, errors = StrategyValidator().validate(config)
    assert not ok
    assert "prohibited_outputs" in errors[0]
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Implement validator**

Create `src/margin/strategy/validator.py` with:
- `StrategyValidator.validate(config)` returns `(bool, list[str])`.
- Pydantic schema validation.
- Guardrail rules: `prohibited_outputs` must not contain `GUARANTEED_RETURN` or `DIRECT_BUY_SELL_ORDER`; `evidence.min_evidence_count >= 1`; `horizon > 0`; `risk.max_position_weight` in (0, 1].
- `merge_with_guardrails(user_config)` applies system guardrails on top of user config.

- [ ] **Step 4: Run tests**

```bash
pytest tests/strategy/test_validator.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/margin/strategy/validator.py tests/strategy/test_validator.py
git commit -m "feat(strategy): add schema validation and guardrails"
```

---

## Task 4: Prompt layering

**Files:**
- Create: `src/margin/strategy/prompt.py`
- Test: `tests/strategy/test_prompt.py`

- [ ] **Step 1: Write failing test**

```python
def test_prompt_layers_include_guardrail():
    from margin.strategy.prompt import PromptLayerBuilder
    from margin.strategy.models import StrategyConfig
    prompt = PromptLayerBuilder().build(StrategyConfig(), custom_instructions="focus on ROE")
    assert "evidence" in prompt.lower()
    assert "focus on ROE" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Implement prompt builder**

Create `src/margin/strategy/prompt.py` with:
- `PromptLayerBuilder` that composes layers in order:
  1. System Guardrail Prompt
  2. Platform Research Prompt
  3. Strategy Template Prompt
  4. User Custom Prompt
  5. Current Task Context
  6. Retrieved Evidence (placeholder)
- `build(config, custom_instructions="", evidence_context="", task="")` returns final string.
- Guardrail text includes: evidence citation requirement, PIT constraints, risk disclosure, structured output schema, no return guarantee, no auto-order.

- [ ] **Step 4: Run tests**

```bash
pytest tests/strategy/test_prompt.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/margin/strategy/prompt.py tests/strategy/test_prompt.py
git commit -m "feat(strategy): add layered prompt builder"
```

---

## Task 5: Lifecycle state machine

**Files:**
- Create: `src/margin/strategy/lifecycle.py`
- Test: `tests/strategy/test_lifecycle.py`

- [ ] **Step 1: Write failing test**

```python
def test_draft_can_validate():
    from margin.strategy.lifecycle import StrategyLifecycle
    from margin.strategy.models import StrategyState
    lifecycle = StrategyLifecycle()
    assert lifecycle.can_transition(StrategyState.DRAFT, StrategyState.VALIDATING)
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Implement lifecycle**

Create `src/margin/strategy/lifecycle.py` with:
- `StrategyLifecycle` class.
- `can_transition(from_state, to_state)` based on spec state machine.
- `transition(version, to_state, reason="")` returns updated version or raises `ValueError`.
- Allowed: DRAFT→VALIDATING; VALIDATING→INVALID/BACKTESTING; BACKTESTING→PAPER_TRADING; PAPER_TRADING→ACTIVE; ACTIVE→ARCHIVED/SUSPENDED; SUSPENDED→ACTIVE/ARCHIVED.

- [ ] **Step 4: Run tests**

```bash
pytest tests/strategy/test_lifecycle.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/margin/strategy/lifecycle.py tests/strategy/test_lifecycle.py
git commit -m "feat(strategy): add strategy lifecycle state machine"
```

---

## Task 6: Strategy sandbox

**Files:**
- Create: `src/margin/strategy/sandbox.py`
- Test: `tests/strategy/test_sandbox.py`

- [ ] **Step 1: Write failing test**

```python
def test_sandbox_flags_missing_evidence():
    from margin.strategy.models import StrategyConfig
    from margin.strategy.sandbox import StrategySandbox
    result = StrategySandbox().evaluate(StrategyConfig(evidence={"min_evidence_count": 0}))
    assert not result.validation_ok
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Implement sandbox**

Create `src/margin/strategy/sandbox.py` with:
- `StrategySandbox.evaluate(config)` returns `StrategySandboxResult`.
- Checks: config validation, sample run feasibility (universe non-empty), backtest placeholder, data leak check (no future dates), cost check (placeholder), preview summary.

- [ ] **Step 4: Run tests**

```bash
pytest tests/strategy/test_sandbox.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/margin/strategy/sandbox.py tests/strategy/test_sandbox.py
git commit -m "feat(strategy): add strategy sandbox checks"
```

---

## Task 7: Repository and service

**Files:**
- Create: `src/margin/strategy/repository.py`, `src/margin/strategy/service.py`
- Test: `tests/strategy/test_repository.py`, `tests/strategy/test_service.py`

- [ ] **Step 1: Write failing test**

```python
def test_service_creates_strategy_from_template():
    from margin.strategy.service import StrategyService
    service = StrategyService()
    profile = service.create_from_template("user_1", "value_quality")
    assert profile.active_version_id == ""
    assert len(profile.versions) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Implement repository and service**

Create `src/margin/strategy/repository.py`:
- `StrategyRepository` Protocol with `add_profile`, `get_profile`, `list_profiles`, `update_profile`.
- `MemoryStrategyRepository` implementation.

Create `src/margin/strategy/service.py`:
- `StrategyService` with injected repository, validator, lifecycle, sandbox.
- `create_from_template(owner_id, template_name, name="", description="")`.
- `create_custom(owner_id, config, name, description)`.
- `update_strategy(strategy_id, config_delta, name, description)` creates new version.
- `validate_version(strategy_id, version_id)`.
- `activate_version(strategy_id, version_id)`.
- `archive_strategy(strategy_id)`.
- `get_prompt(strategy_id, version_id, task, evidence_context)`.
- `list_templates()` returns metadata for built-ins.

- [ ] **Step 4: Run tests**

```bash
pytest tests/strategy/test_repository.py tests/strategy/test_service.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/margin/strategy/repository.py src/margin/strategy/service.py tests/strategy/test_repository.py tests/strategy/test_service.py
git commit -m "feat(strategy): add repository and service layer"
```

---

## Task 8: API routes and package exports

**Files:**
- Create: `src/margin/strategy/__init__.py`, `src/margin/api/routes/strategy.py`
- Modify: `src/margin/api/dependencies.py`, `src/margin/api/main.py`
- Test: `tests/api/test_strategy.py`

- [ ] **Step 1: Write failing test**

```python
def test_create_strategy_endpoint(client):
    response = client.post("/strategies", json={"owner_id": "user_1", "template": "value_quality"})
    assert response.status_code == 200
    assert response.json()["name"] == "Value Quality"
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL.

- [ ] **Step 3: Implement API**

Create `src/margin/strategy/__init__.py` exporting public API.
Create `src/margin/api/routes/strategy.py` with routes:
- `GET /strategies/templates`
- `POST /strategies` (from template or custom)
- `GET /strategies`
- `GET /strategies/{strategy_id}`
- `PUT /strategies/{strategy_id}` (update creates new version)
- `POST /strategies/{strategy_id}/versions/{version_id}/validate`
- `POST /strategies/{strategy_id}/versions/{version_id}/activate`
- `POST /strategies/{strategy_id}/archive`
- `GET /strategies/{strategy_id}/versions/{version_id}/prompt`

Modify `src/margin/api/dependencies.py` to add `get_strategy_service()`.
Modify `src/margin/api/main.py` to include strategy router.

- [ ] **Step 4: Run tests**

```bash
pytest tests/api/test_strategy.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/margin/strategy/__init__.py src/margin/api/routes/strategy.py src/margin/api/dependencies.py src/margin/api/main.py tests/api/test_strategy.py
git commit -m "feat(strategy): add API routes and package exports"
```

---

## Task 9: Final validation

- [ ] **Step 1: Run lint**

```bash
ruff check src tests
```
Expected: 0 errors.

- [ ] **Step 2: Run strategy tests**

```bash
pytest tests/strategy tests/api/test_strategy.py -v
```
Expected: all pass.

- [ ] **Step 3: Run full suite**

```bash
pytest tests/ -v
```
Expected: non-Postgres tests pass.

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(strategy): complete module 07 strategy config MVP"
```
