# Module 05 — RAG Evidence

**Location:** `src/margin/evidence`

This document describes the `05-rag_evidence` module of Margin v0.1. It covers
structured evidence records, citation locators, claim/conflict models,
validation/audit logic, and the PostgreSQL persistence layer used by the
research pipeline.

---

## Table of Contents

- [Module Overview and Responsibilities](#module-overview-and-responsibilities)
- [File-level Summaries](#file-level-summaries)
- [Domain Models](#domain-models)
  - [Evidence](#evidence)
  - [Claim](#claim)
  - [ConflictRecord](#conflictrecord)
  - [Enumerations](#enumerations)
  - [Factory and utility functions](#factory-and-utility-functions)
  - [Conflict detection and L5 restriction](#conflict-detection-and-l5-restriction)
- [Locator](#locator)
  - [SourceType](#sourcetype)
  - [CitationLocator](#citationlocator)
  - [WebSearchVerificationResult](#websearchverificationresult)
  - [PointInTimeCheckResult](#pointintimecheckresult)
  - [LocatorValidationResult](#locatorvalidationresult)
  - [Locator builders](#locator-builders)
  - [Verification and point-in-time checks](#verification-and-point-in-time-checks)
- [Validation](#validation)
  - [ValidationStatus and FailReason](#validationstatus-and-failreason)
  - [ValidationResult](#validationresult)
  - [ValidationAuditRecord and ValidationAuditor](#validationauditrecord-and-validationauditor)
  - [ValidationReport](#validationreport)
  - [CitationValidator](#citationvalidator)
  - [validate_claims_with_audit](#validate_claims_with_audit)
- [Repository](#repository)
  - [ResearchEvidenceLink](#researchevidencelink)
  - [EvidenceRepository](#evidencerepository)
- [Cross-Module Usage Notes](#cross-module-usage-notes)

---

## Module Overview and Responsibilities

The RAG Evidence module transforms raw document chunks (produced by
`04-text_indexing`) into auditable research artifacts. Its responsibilities are:

1. **Evidence modeling** — wrap chunks into immutable `Evidence` records with
   source level, quality score, content hash, and locator fields.
2. **Claim modeling** — represent research conclusions as structured `Claim`
   objects, distinguishing facts from inferences and tracking conflicts.
3. **Citation location** — build `CitationLocator` objects that trace every
   conclusion back to a PDF page, HTML paragraph, table row, or snapshot.
4. **Validation** — enforce source-level rules, point-in-time constraints,
   locator traceability, WebSearch original-source verification, and conflict
   confidence capping.
5. **Conflict detection** — identify contradictory claims and L1-vs-L5 evidence
   gaps, then cap confidence and flag counter-review.
6. **Persistence** — provide an append-only SQLAlchemy repository for evidence,
   claims, validation audits, and research-item links.

All public exports are listed in `src/margin/evidence/__init__.py`.

---

## File-level Summaries

| File | Purpose |
|------|---------|
| `src/margin/evidence/__init__.py` | Public package exports. Re-exports all domain models, locators, validators, and repository classes. |
| `src/margin/evidence/models.py` | Core Pydantic domain models: `Evidence`, `Claim`, `ConflictRecord`, claim/enumerations, factories, conflict detection, and L5 restriction logic. |
| `src/margin/evidence/locator.py` | `CitationLocator` model and helpers to build locators from PDF, HTML, or table chunks, verify WebSearch originals, and run point-in-time checks. |
| `src/margin/evidence/validator.py` | `CitationValidator`, validation result/report models, audit records, and the `validate_claims_with_audit` convenience function. |
| `src/margin/evidence/repository.py` | SQLAlchemy `EvidenceRepository` and `ResearchEvidenceLink` for persisting evidence, claims, audits, and research-evidence links. |
| `src/margin/evidence/db_models.py` | SQLAlchemy ORM row models mapped to PostgreSQL tables: `evidence_records`, `evidence_claims`, `evidence_validation_audits`, and `research_evidence`. |

---

## Domain Models

Defined in `src/margin/evidence/models.py`.

### Enumerations

| Enum | Values | Description |
|------|--------|-------------|
| `ClaimType` | `cash_flow_improvement`, `valuation_change`, `risk_event`, `growth_signal`, `earnings_beat`, `dividend_change`, `governance_issue`, `industry_trend`, `custom` | Classification of a research claim. |
| `FactOrInference` | `fact`, `inference`, `unknown` | Distinguishes a factual statement from an inferred conclusion. |
| `ConflictSeverity` | `low`, `medium`, `high` | Severity assigned to a detected conflict. |

### Evidence

`class Evidence(BaseModel)` — immutable record built from a document chunk.

| Attribute | Type | Description |
|-----------|------|-------------|
| `evidence_id` | `str` | Unique evidence identifier. |
| `chunk_id` | `str` | Originating chunk identifier. |
| `document_id` | `str` | Originating document identifier. |
| `source_type` | `str` | Source kind (`filing_pdf`, `web_page`, `table`, `api_record`, `user_file`). |
| `source_url` | `str \| None` | URL of the original source. |
| `source_name` | `str \| None` | Human-readable source name. |
| `source_level` | `SourceLevel` | Priority level (L1–L5). |
| `content_hash` | `str` | Hash of the cited content. |
| `content` | `str` | Text content of the evidence. |
| `symbol` | `str \| None` | Optional ticker symbol. |
| `quality_score` | `float \| None` | Optional score in `[0, 1]`. |
| `published_at` | `datetime` | Publication timestamp (UTC). |
| `available_at` | `datetime` | Availability timestamp (UTC). |
| `retrieved_at` | `datetime` | Retrieval timestamp (UTC). |
| `page` | `int \| None` | Page number in the original document. |
| `section` | `str \| None` | Section name. |
| `paragraph_index` | `int \| None` | Paragraph index (HTML). |
| `table_id` | `str \| None` | Table identifier. |
| `row_id` | `str \| None` | Row identifier. |
| `quote_span` | `tuple[int, int] \| None` | Character span `(start, end)`. |
| `snapshot_id` | `str \| None` | Snapshot identifier. |
| `snapshot_hash` | `str \| None` | Snapshot content hash. |

| Method / Property | Description |
|-------------------|-------------|
| `can_change_research_state` | `True` when `source_level <= L3`; L4/L5 cannot change state. |
| `effective_quality_score` | Returns explicit `quality_score` or the default score for the source level. |
| `is_locatable` | `True` when a `source_url` and at least one structural locator field exist. |
| `from_chunk(chunk, source_type=None)` | Class method that builds an `Evidence` from a chunk object. |

### Claim

`class Claim(BaseModel)` — a structured research conclusion.

| Attribute | Type | Description |
|-----------|------|-------------|
| `claim_id` | `str` | Unique claim identifier. |
| `claim_type` | `ClaimType` | Claim classification. |
| `statement` | `str` | Human-readable claim text. |
| `fact_or_inference` | `FactOrInference` | Whether the claim is fact, inference, or unknown. |
| `evidence_ids` | `list[str]` | IDs of supporting evidence records. |
| `confidence` | `float` | Confidence in `[0, 1]`. |
| `conflicts` | `list[ConflictRecord]` | Associated conflict records. |
| `effective_at` | `datetime` | Timestamp when the claim becomes effective (UTC). |
| `locator` | `dict[str, Any] \| None` | Primary citation locator snapshot. |
| `symbol` | `str \| None` | Optional ticker symbol. |

| Property | Description |
|----------|-------------|
| `has_conflict` | `True` if the claim has one or more conflicts. |
| `has_evidence` | `True` if the claim references evidence. |
| `conflict_confidence_cap` | Returns original confidence if no conflicts; otherwise caps at `0.5` (or `0.3` for high severity). |
| `is_fact` | `True` when `fact_or_inference == FACT`. |
| `is_inference` | `True` when `fact_or_inference == INFERENCE`. |

### ConflictRecord

`class ConflictRecord(BaseModel)` — records a detected conflict.

| Attribute | Type | Description |
|-----------|------|-------------|
| `conflict_id` | `str` | Unique conflict identifier. |
| `claim_id` | `str` | Claim involved in the conflict. |
| `conflicting_evidence_ids` | `list[str]` | Evidence IDs that conflict. |
| `description` | `str` | Human-readable description. |
| `severity` | `ConflictSeverity` | Conflict severity. |

### Factory and utility functions

| Function | Signature | Description |
|----------|-----------|-------------|
| `make_claim` | `(statement, claim_type=CUSTOM, fact_or_inference=UNKNOWN, evidence_ids=None, confidence=0.0, conflicts=None, locator=None, symbol=None, effective_at=None)` | Creates a `Claim` with an auto-generated ID. |
| `make_conflict` | `(claim_id, conflicting_evidence_ids, description="", severity=MEDIUM)` | Creates a `ConflictRecord` with an auto-generated ID. |
| `quality_score_for_level` | `(source_level: SourceLevel) -> float` | Returns the default quality score for L1–L5 (`1.0`, `0.88`, `0.76`, `0.52`, `0.2`). |

### Conflict detection and L5 restriction

| Function | Signature | Description |
|----------|-----------|-------------|
| `detect_conflicts` | `(claims: list[Claim], evidences: dict[str, Evidence]) -> dict[str, list[ConflictRecord]]` | Detects two conflict patterns: (1) same `claim_type` with opposite statement direction using Chinese antonym markers, and (2) an L5-vs-L1/L2 source gap within a single claim's evidence. Returns a map from `claim_id` to conflicts. |
| `check_l5_restriction` | `(claim: Claim, evidences: dict[str, Evidence]) -> bool` | Returns `False` if the claim is supported solely by L5 evidence or has no evidence; otherwise `True`. L5 evidence may only trigger investigation and cannot change research/position state. |

---

## Locator

Defined in `src/margin/evidence/locator.py`.

### SourceType

`class SourceType(StrEnum)` — source kind for a citation.

| Value | Meaning |
|-------|---------|
| `FILING_PDF` | `filing_pdf` |
| `WEB_PAGE` | `web_page` |
| `TABLE` | `table` |
| `API_RECORD` | `api_record` |
| `USER_FILE` | `user_file` |

### CitationLocator

`class CitationLocator(BaseModel)` — immutable locator tracing a claim back to
its original source.

| Attribute | Type | Description |
|-----------|------|-------------|
| `evidence_id` | `str` | Related evidence record ID. |
| `document_id` | `str` | Originating document ID. |
| `source_type` | `SourceType` | Source type (defaults to `WEB_PAGE`). |
| `source_url` | `str \| None` | Original source URL. |
| `source_level` | `SourceLevel` | Source priority (defaults to L4). |
| `content_hash` | `str` | Hash of cited content. |
| `published_at` | `datetime` | Publication timestamp (UTC). |
| `available_at` | `datetime` | Availability timestamp (UTC). |
| `retrieved_at` | `datetime` | Retrieval timestamp (UTC). |
| `page` | `int \| None` | Page number. |
| `section` | `str \| None` | Section name. |
| `paragraph_index` | `int \| None` | Paragraph index. |
| `table_id` | `str \| None` | Table ID. |
| `row_id` | `str \| None` | Row ID. |
| `quote_span` | `tuple[int, int] \| None` | Character span. |
| `snapshot_id` | `str \| None` | Snapshot ID. |
| `snapshot_hash` | `str \| None` | Snapshot content hash. |

| Method / Property | Description |
|-------------------|-------------|
| `is_locatable` | `True` when `source_url` is present and at least one structural locator field is set. |
| `has_snapshot` | `True` when `snapshot_id` is present. |
| `from_evidence(evidence)` | Builds a locator from an `Evidence` instance. |
| `from_chunk(chunk)` | Builds a locator from a chunk via `Evidence.from_chunk`. |

### WebSearchVerificationResult

`class WebSearchVerificationResult(BaseModel)` — result of verifying that a
WebSearch result lands on an original source.

| Attribute | Type | Description |
|-----------|------|-------------|
| `evidence_id` | `str` | Evidence being verified. |
| `passed` | `bool` | Whether verification passed. |
| `reason` | `str` | Human-readable explanation. |

### PointInTimeCheckResult

`class PointInTimeCheckResult(BaseModel)` — result of a point-in-time check.

| Attribute | Type | Description |
|-----------|------|-------------|
| `evidence_id` | `str` | Evidence being checked. |
| `passed` | `bool` | Whether `available_at <= decision_at`. |
| `reason` | `str` | Human-readable explanation. |
| `available_at` | `datetime \| None` | Availability timestamp used. |
| `decision_at` | `datetime \| None` | Decision timestamp used. |

### LocatorValidationResult

`class LocatorValidationResult(BaseModel)` — aggregated locator validation.

| Attribute | Type | Description |
|-----------|------|-------------|
| `evidence_id` | `str` | Evidence being validated. |
| `is_locatable` | `bool` | Locator traceability result. |
| `pit_passed` | `bool` | Point-in-time result. |
| `websearch_passed` | `bool \| None` | WebSearch verification result (None if not checked). |
| `reasons` | `list[str]` | Failure reasons. |

| Property | Description |
|----------|-------------|
| `all_passed` | `True` when `is_locatable`, `pit_passed`, and (when applicable) `websearch_passed` are all true. |

### Locator builders

| Function | Signature | Description |
|----------|-----------|-------------|
| `build_locator_from_pdf` | `(chunk, page=None, section=None, quote_span=None) -> CitationLocator` | Builds a PDF locator using page, section, and character span. |
| `build_locator_from_html` | `(chunk, paragraph_index=None) -> CitationLocator` | Builds an HTML/web-page locator using URL, paragraph index, and content hash; clears page/table/row fields. |
| `build_locator_from_table` | `(chunk, table_id=None, row_id=None) -> CitationLocator` | Builds a table locator using table ID, row ID, and page; clears the character span. |

### Verification and point-in-time checks

| Function | Signature | Description |
|----------|-----------|-------------|
| `verify_websearch_original` | `(locator, require_snapshot=True, snapshot_resolver=None) -> WebSearchVerificationResult` | Verifies that a `WEB_PAGE` locator points to an accessible original page or compliant snapshot, not only a search snippet. Non-web sources pass automatically. |
| `check_point_in_time` | `(locator, decision_at) -> PointInTimeCheckResult` | Checks `available_at <= decision_at` after normalizing timestamps to UTC. |
| `check_locators_point_in_time` | `(locators, decision_at) -> tuple[list[CitationLocator], list[PointInTimeCheckResult]]` | Runs point-in-time checks on a batch and returns the locators that passed plus all results. |
| `validate_locator` | `(locator, decision_at, check_websearch=True, snapshot_resolver=None) -> LocatorValidationResult` | Comprehensive locator validation combining `is_locatable`, point-in-time, and optional WebSearch verification. |

---

## Validation

Defined in `src/margin/evidence/validator.py`.

### ValidationStatus and FailReason

`ValidationStatus(StrEnum)`

| Value | Meaning |
|-------|---------|
| `PASS` | Validation passed. |
| `FAIL` | Validation failed; claim should be suppressed. |
| `ABSTAINED` | Insufficient evidence; claim should not be emitted. |

`FailReason(StrEnum)` — classification of validation failures.

| Value | Meaning |
|-------|---------|
| `NO_EVIDENCE` | Claim has no evidence references. |
| `EVIDENCE_NOT_FOUND` | Referenced evidence is missing. |
| `NOT_LOCATABLE` | Evidence locator cannot trace back to source. |
| `LOOKAHEAD` | `available_at > decision_at` (future-data leakage). |
| `L5_ONLY` | Claim relies solely on L5 evidence. |
| `WEBSEARCH_NO_ORIGINAL` | WebSearch result lacks original source/snapshot. |
| `CONFLICT_HIGH` | High-severity conflict detected. |
| `INSUFFICIENT_EVIDENCE` | Too few valid evidences. |
| `L4_NO_CROSS_VALIDATION` | L4 evidence is not cross-validated by L1–L3. |

### ValidationResult

`class ValidationResult(BaseModel)` — outcome for a single claim.

| Attribute | Type | Description |
|-----------|------|-------------|
| `claim_id` | `str` | Validated claim ID. |
| `status` | `ValidationStatus` | `PASS`, `FAIL`, or `ABSTAINED`. |
| `reason` | `str` | Human-readable explanation. |
| `fail_reason` | `FailReason \| None` | Failure classification. |
| `original_confidence` | `float` | Claim confidence before capping. |
| `capped_confidence` | `float` | Confidence after conflict capping. |
| `conflicts_found` | `int` | Number of conflicts detected. |
| `evidences_checked` | `int` | Evidence references examined. |
| `evidences_passed` | `int` | Evidence references that passed locator validation. |
| `requires_counter_review` | `bool` | Whether the claim should be escalated for counter-review. |
| `checked_at` | `datetime` | Validation timestamp (UTC). |

| Property | Description |
|----------|-------------|
| `should_suppress` | `True` for `FAIL` or `ABSTAINED`. |

### ValidationAuditRecord and ValidationAuditor

`class ValidationAuditRecord(BaseModel)` — immutable audit row materialized by
the auditor and persisted by the repository.

| Attribute | Type | Description |
|-----------|------|-------------|
| `audit_id` | `str` | Unique audit identifier. |
| `claim_id` | `str` | Claim that was validated. |
| `status` | `ValidationStatus` | Validation status. |
| `reason` | `str` | Explanation. |
| `fail_reason` | `FailReason \| None` | Failure classification. |
| `original_confidence` | `float` | Original confidence. |
| `capped_confidence` | `float` | Capped confidence. |
| `conflicts_found` | `int` | Conflict count. |
| `evidences_checked` | `int` | Evidence count checked. |
| `evidences_passed` | `int` | Evidence count passed. |
| `requires_counter_review` | `bool` | Counter-review flag. |
| `checked_at` | `datetime` | Timestamp (UTC). |

`class ValidationAuditor`

| Method / Property | Description |
|-------------------|-------------|
| `log(result: ValidationResult) -> ValidationAuditRecord` | Converts a `ValidationResult` into an audit record and stores it. |
| `records` | All logged audit records. |
| `pass_count` | Number of `PASS` records. |
| `fail_count` | Number of `FAIL` records. |
| `abstained_count` | Number of `ABSTAINED` records. |

### ValidationReport

`class ValidationReport(BaseModel)` — aggregated result of a batch validation.

| Attribute | Type | Description |
|-----------|------|-------------|
| `results` | `list[ValidationResult]` | Per-claim results. |
| `total` | `int` | Total claims. |
| `passed` | `int` | Passed count. |
| `failed` | `int` | Failed count. |
| `abstained` | `int` | Abstained count. |
| `checked_at` | `datetime` | Report timestamp (UTC). |

| Property | Description |
|----------|-------------|
| `should_suppress_research` | `True` when any result is `ABSTAINED`, any result `FAIL`ed, or a high-confidence claim requires counter-review with capped confidence. |
| `passed_claims` | Results with status `PASS`. |
| `failed_claims` | Results with status `FAIL`. |
| `abstained_claims` | Results with status `ABSTAINED`. |

### CitationValidator

`class CitationValidator` — enforces the module's evidence rules.

| Constructor parameter | Default | Description |
|-----------------------|---------|-------------|
| `min_evidence_count` | `1` | Minimum evidence references that must pass locator validation. |
| `conflict_cap` | `0.5` | Confidence cap for non-high conflicts. |
| `high_conflict_cap` | `0.3` | Confidence cap for high-severity conflicts. |
| `high_confidence_threshold` | `0.7` | Threshold used when reporting high-confidence counter-review cases. |
| `snapshot_resolver` | `None` | Optional `SnapshotResolver` for WebSearch snapshot verification. |

| Method | Signature | Description |
|--------|-----------|-------------|
| `validate_claim` | `(claim, evidences, decision_at, precomputed_conflicts=None) -> ValidationResult` | Validates a single claim. Steps: evidence existence, L5 restriction, L4 cross-validation, locator/point-in-time/WebSearch checks, minimum evidence count, conflict capping. |
| `validate_batch` | `(claims, evidences, decision_at) -> ValidationReport` | Runs `detect_conflicts` once for the batch, then validates each claim using precomputed conflicts. |

### validate_claims_with_audit

```python
def validate_claims_with_audit(
    claims: list[Claim],
    evidences: dict[str, Evidence],
    decision_at: datetime,
    validator: CitationValidator | None = None,
    auditor: ValidationAuditor | None = None,
) -> tuple[ValidationReport, ValidationAuditor]
```

Convenience function that validates a list of claims and logs every result to a
`ValidationAuditor`. Returns the `ValidationReport` and the populated auditor.

---

## Repository

Defined in `src/margin/evidence/repository.py`.

### ResearchEvidenceLink

`class ResearchEvidenceLink(BaseModel)` — persisted association between a
research item, a claim, and an evidence record.

| Attribute | Type | Description |
|-----------|------|-------------|
| `research_item_id` | `str` | Research item identifier. |
| `claim_id` | `str` | Claim identifier. |
| `evidence_id` | `str` | Evidence identifier. |
| `role` | `str` | Role of the evidence for this research item (e.g. `support`, `oppose`). |
| `rank` | `int` | Ordering rank. |
| `created_at` | `datetime` | Creation timestamp (UTC). |

### EvidenceRepository

`class EvidenceRepository` — append-only persistence boundary backed by SQLAlchemy.

| Constructor parameter | Description |
|-----------------------|-------------|
| `session_factory` | Callable returning a SQLAlchemy `Session`. Used with `begin()` for write operations. |

| Method | Signature | Description |
|--------|-----------|-------------|
| `add_evidence` | `(evidence: Evidence) -> None` | Persists an evidence record idempotently; raises `ValueError` on mutation attempts. |
| `get_evidence` | `(evidence_id: str) -> Evidence \| None` | Fetches an evidence record by ID. |
| `add_claim` | `(claim: Claim) -> None` | Persists a claim idempotently; raises `ValueError` on mutation attempts. |
| `get_claim` | `(claim_id: str) -> Claim \| None` | Fetches a claim by ID. |
| `add_validation_audit` | `(audit: ValidationAuditRecord) -> None` | Appends a validation audit record idempotently. |
| `list_validation_audits` | `(claim_id: str) -> list[ValidationAuditRecord]` | Returns audits for a claim ordered by `checked_at`, `audit_id`. |
| `link_research_evidence` | `(*, research_item_id, claim_id, evidence_id, role, rank) -> None` | Persists a research-evidence link idempotently; raises `ValueError` if an existing link has a different rank. |
| `list_research_evidence` | `(research_item_id: str) -> list[ResearchEvidenceLink]` | Returns links for a research item ordered by `rank`, `created_at`. |

---

## Cross-Module Usage Notes

- **Upstream dependency** — `Evidence.from_chunk` accepts chunks produced by
  `04-text_indexing`. The chunk object is expected to expose fields such as
  `chunk_id`, `document_id`, `doc_type`, `source_url`, `source_name`,
  `source_level`, `content_hash`, `content`, `symbol`, timestamps, and locator
  fields (`page`, `section`, `paragraph_index`, `table_id`, `row_id`,
  `quote_span`, `snapshot_id`, `snapshot_hash`).

- **News module** — `src/margin/evidence/models.py` and
  `src/margin/evidence/locator.py` import `SourceLevel`, `ensure_utc`, and
  `utc_now` from `margin.news.models`. `locator.py` also imports `RawSnapshot`
  for WebSearch snapshot verification.

- **Storage module** — `src/margin/evidence/db_models.py` inherits from
  `margin.storage.base.Base` and defines the tables used by
  `EvidenceRepository`.

- **Research pipeline** — downstream modules can call
  `validate_claims_with_audit` to filter claims before converting them into
  research signals. Claims that validate as `FAIL` or `ABSTAINED`, or that
  require counter-review with capped high confidence, should not drive
  high-confidence research output.

- **Immutability contract** — evidence, claims, validation audits, and
  research-evidence links are append-only. Repository methods raise
  `ValueError` when a re-insertion would change an existing row.
