"""Citation Validator — claim validation, conflict capping, ABSTAINED decisions, audit.

Corresponds to spec 05 §7 risk and downgrade, architecture §10.2 RAG workflow,
and §25 fault degradation.
Corresponds to plan 0503:
    0503.1 Citation and source-level validation — validate evidence_ids, source_level,
        and point-in-time.
    0503.2 Conflict handling — conflicting claims trigger counter-review and confidence
        capping.
    0503.3 ABSTAINED decision — refuse high-confidence conclusions when evidence is
        insufficient or conflicts are too high.
    0503.4 Validation audit — record pass/fail reasons for each validation.

Principle (architecture §25): prefer ABSTAINED over false high-confidence conclusions.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from margin.evidence.locator import (
    CitationLocator,
    LocatorValidationResult,
    LocatorValidator,
    SnapshotResolver,
    validate_locator,
)
from margin.evidence.models import (
    Claim,
    ConflictSeverity,
    Evidence,
    check_l5_restriction,
    detect_conflicts,
)
from margin.news.models import SourceLevel, ensure_utc, utc_now

# ---------------------------------------------------------------------------
# 0503.1 / 0503.3 Validation status
# ---------------------------------------------------------------------------


class ValidationStatus(StrEnum):
    """Status of a single claim validation result."""

    PASS = "pass"
    FAIL = "fail"
    ABSTAINED = "abstained"


class FailReason(StrEnum):
    """Categorized reason why a claim validation failed or abstained."""

    NO_EVIDENCE = "no_evidence"
    EVIDENCE_NOT_FOUND = "evidence_not_found"
    NOT_LOCATABLE = "not_locatable"
    LOOKAHEAD = "lookahead"
    L5_ONLY = "l5_only"
    WEBSSEARCH_NO_ORIGINAL = "websearch_no_original"
    WEBSEARCH_NO_ORIGINAL = "websearch_no_original"
    CONFLICT_HIGH = "conflict_high"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    L4_NO_CROSS_VALIDATION = "l4_no_cross_validation"


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """Result of validating a single claim.

    Attributes:
        claim_id: Identifier of the validated claim.
        status: Validation status (PASS, FAIL, or ABSTAINED).
        reason: Human-readable explanation of the outcome.
        fail_reason: Categorized failure reason, if applicable.
        original_confidence: Confidence of the claim before any capping.
        capped_confidence: Confidence after conflict capping.
        conflicts_found: Number of conflicts detected for the claim.
        evidences_checked: Number of evidence items examined.
        evidences_passed: Number of evidence items that passed locator checks.
        requires_counter_review: Whether a conflict warrants counter-review.
        checked_at: Timestamp when validation occurred (UTC).
    """

    claim_id: str
    status: ValidationStatus
    reason: str = ""
    fail_reason: FailReason | None = None
    original_confidence: float = 0.0
    capped_confidence: float = 0.0
    conflicts_found: int = 0
    evidences_checked: int = 0
    evidences_passed: int = 0
    requires_counter_review: bool = False
    checked_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("checked_at")
    @classmethod
    def normalize_checked_at(cls, value: datetime) -> datetime:
        """Normalize the checked-at timestamp to UTC.

        Args:
            value: A datetime value to normalize.

        Returns:
            The datetime normalized to UTC.
        """
        return ensure_utc(value)

    @property
    def should_suppress(self) -> bool:
        """Return whether the claim should be suppressed from research signals.

        FAIL and ABSTAINED results are not allowed to feed high-confidence research
        conclusions.

        Returns:
            True if the validation status is FAIL or ABSTAINED.
        """
        return self.status in (ValidationStatus.FAIL, ValidationStatus.ABSTAINED)


# ---------------------------------------------------------------------------
# 0503.4 Validation audit
# ---------------------------------------------------------------------------


class ValidationAuditRecord(BaseModel):
    """Append-only audit record capturing the outcome of a claim validation.

    Immutable after persistence.

    Attributes:
        audit_id: Unique identifier of the audit record.
        claim_id: Identifier of the audited claim.
        status: Validation status.
        reason: Human-readable explanation of the outcome.
        fail_reason: Categorized failure reason, if applicable.
        original_confidence: Claim confidence before capping.
        capped_confidence: Claim confidence after capping.
        conflicts_found: Number of conflicts detected.
        evidences_checked: Number of evidence items examined.
        evidences_passed: Number of evidence items that passed.
        requires_counter_review: Whether counter-review is required.
        checked_at: Timestamp when validation occurred (UTC).
    """

    audit_id: str
    claim_id: str
    status: ValidationStatus
    reason: str
    fail_reason: FailReason | None = None
    original_confidence: float = 0.0
    capped_confidence: float = 0.0
    conflicts_found: int = 0
    evidences_checked: int = 0
    evidences_passed: int = 0
    requires_counter_review: bool = False
    checked_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("checked_at")
    @classmethod
    def normalize_checked_at(cls, value: datetime) -> datetime:
        """Normalize the checked-at timestamp to UTC.

        Args:
            value: A datetime value to normalize.

        Returns:
            The datetime normalized to UTC.
        """
        return ensure_utc(value)


class ValidationAuditor:
    """Records validation results for later audit and counter-review."""

    def __init__(self) -> None:
        """Initialize an empty auditor."""
        self._records: list[ValidationAuditRecord] = []

    def log(self, result: ValidationResult) -> ValidationAuditRecord:
        """Record a validation result as an append-only audit record.

        Args:
            result: The validation result to record.

        Returns:
            The created audit record.
        """
        record = ValidationAuditRecord(
            audit_id=f"aud_{uuid.uuid4().hex[:12]}",
            claim_id=result.claim_id,
            status=result.status,
            reason=result.reason,
            fail_reason=result.fail_reason,
            original_confidence=result.original_confidence,
            capped_confidence=result.capped_confidence,
            conflicts_found=result.conflicts_found,
            evidences_checked=result.evidences_checked,
            evidences_passed=result.evidences_passed,
            requires_counter_review=result.requires_counter_review,
        )
        self._records.append(record)
        return record

    @property
    def records(self) -> list[ValidationAuditRecord]:
        """Return a copy of all recorded audit records.

        Returns:
            List of recorded validation audit records.
        """
        return list(self._records)

    @property
    def pass_count(self) -> int:
        """Return the number of PASS records.

        Returns:
            Count of records with status PASS.
        """
        return sum(1 for r in self._records if r.status == ValidationStatus.PASS)

    @property
    def fail_count(self) -> int:
        """Return the number of FAIL records.

        Returns:
            Count of records with status FAIL.
        """
        return sum(1 for r in self._records if r.status == ValidationStatus.FAIL)

    @property
    def abstained_count(self) -> int:
        """Return the number of ABSTAINED records.

        Returns:
            Count of records with status ABSTAINED.
        """
        return sum(1 for r in self._records if r.status == ValidationStatus.ABSTAINED)


# ---------------------------------------------------------------------------
# Batch validation report
# ---------------------------------------------------------------------------


class ValidationReport(BaseModel):
    """Aggregated report for a batch of claim validations.

    Attributes:
        results: Individual validation results.
        total: Total number of claims validated.
        passed: Number of claims that passed.
        failed: Number of claims that failed.
        abstained: Number of claims that abstained.
        checked_at: Timestamp when the report was generated (UTC).
    """

    results: list[ValidationResult] = Field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    abstained: int = 0
    checked_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("checked_at")
    @classmethod
    def normalize_checked_at(cls, value: datetime) -> datetime:
        """Normalize the report timestamp to UTC.

        Args:
            value: A datetime value to normalize.

        Returns:
            The datetime normalized to UTC.
        """
        return ensure_utc(value)

    @property
    def should_suppress_research(self) -> bool:
        """Return whether high-confidence research signals should be suppressed.

        Suppression occurs when any claim abstained, failed, or had a high-confidence
        conflict downgrade (product §15 item 8).

        Returns:
            True if high-confidence research output should be blocked.
        """
        has_abstained = any(
            r.status == ValidationStatus.ABSTAINED for r in self.results
        )
        has_high_conf_fail = any(
            r.status == ValidationStatus.FAIL
            for r in self.results
        )
        has_high_conf_counter_review = any(
            r.requires_counter_review
            and r.original_confidence >= 0.7
            and r.capped_confidence < r.original_confidence
            for r in self.results
        )
        return has_abstained or has_high_conf_fail or has_high_conf_counter_review

    @property
    def passed_claims(self) -> list[ValidationResult]:
        """Return the results that passed validation.

        Returns:
            List of PASS validation results.
        """
        return [r for r in self.results if r.status == ValidationStatus.PASS]

    @property
    def failed_claims(self) -> list[ValidationResult]:
        """Return the results that failed validation.

        Returns:
            List of FAIL validation results.
        """
        return [r for r in self.results if r.status == ValidationStatus.FAIL]

    @property
    def abstained_claims(self) -> list[ValidationResult]:
        """Return the results that abstained.

        Returns:
            List of ABSTAINED validation results.
        """
        return [r for r in self.results if r.status == ValidationStatus.ABSTAINED]


# ---------------------------------------------------------------------------
# 0503 Citation Validator
# ---------------------------------------------------------------------------


class CitationValidator:
    """Validates claim evidence references, source levels, and point-in-time.

    Validation flow (architecture §10.2 RAG workflow):
        1. Evidence reference existence (evidence_ids non-empty and resolvable).
        2. Source-level rules (L5 cannot stand alone; L4 needs L1-L3 cross-validation).
        3. Point-in-time check (available_at <= decision_at).
        4. Locator check (each evidence can be traced back to the original source).
        5. WebSearch original-source check (web_page sources must have a snapshot).
        6. Conflict detection (opposite statement direction within the same claim_type
           triggers confidence capping and counter-review).
        7. Insufficient-evidence decision (no evidence passes -> ABSTAINED).

    Degradation rules (architecture §25):
        - Citation failure -> FAIL, do not feed research signals.
        - Conflicts -> cap confidence and raise counter-review.
        - Insufficient evidence -> ABSTAINED.
        - Principle: prefer ABSTAINED over false high-confidence conclusions.
    """

    def __init__(
        self,
        min_evidence_count: int = 1,
        conflict_cap: float = 0.5,
        high_conflict_cap: float = 0.3,
        high_confidence_threshold: float = 0.7,
        l4_only_status: ValidationStatus = ValidationStatus.FAIL,
        snapshot_resolver: SnapshotResolver | None = None,
    ) -> None:
        """Initialize the validator with configurable thresholds.

        Args:
            min_evidence_count: Minimum number of evidence items that must pass
                validation for a claim to PASS.
            conflict_cap: Confidence cap applied when non-high conflicts exist.
            high_conflict_cap: Confidence cap applied when a high-severity conflict
                exists.
            high_confidence_threshold: Confidence level considered high-confidence.
            l4_only_status: Validation status for L4-only evidence. Defaults to FAIL
                for backward compatibility; v0.2 workflows can set ABSTAINED.
            snapshot_resolver: Optional callable that resolves snapshot IDs to
                RawSnapshot instances.
        """
        self._min_evidence = min_evidence_count
        self._conflict_cap = conflict_cap
        self._high_conflict_cap = high_conflict_cap
        self._high_conf_threshold = high_confidence_threshold
        self._l4_only_status = l4_only_status
        self._snapshot_resolver = snapshot_resolver

    def validate_claim(
        self,
        claim: Claim,
        evidences: dict[str, Evidence],
        decision_at: datetime,
        precomputed_conflicts: list | None = None,
    ) -> ValidationResult:
        """Validate a single claim against its evidence.

        Args:
            claim: The claim to validate.
            evidences: Mapping from evidence_id to Evidence.
            decision_at: Decision timestamp; evidence must be available at or before
                this time.
            precomputed_conflicts: Optional list of precomputed ConflictRecord items
                for the claim. If omitted, conflicts are detected on the fly.

        Returns:
            A ValidationResult describing the outcome.
        """
        if not claim.has_evidence:
            return self._fail(
                claim, FailReason.NO_EVIDENCE,
                "Claim has no evidence references",
            )

        found_evidences: list[Evidence] = []
        for eid in claim.evidence_ids:
            if eid not in evidences:
                return self._fail(
                    claim, FailReason.EVIDENCE_NOT_FOUND,
                    f"Evidence '{eid}' not found",
                )
            found_evidences.append(evidences[eid])

        if not check_l5_restriction(claim, evidences):
            return self._fail(
                claim, FailReason.L5_ONLY,
                "Claim relies solely on L5 evidence — cannot change research state",
            )

        l4_evidences = [e for e in found_evidences if e.source_level == SourceLevel.L4]
        l1_l3_evidences = [
            e for e in found_evidences if e.source_level <= SourceLevel.L3
        ]
        if l4_evidences and not l1_l3_evidences:
            if self._l4_only_status == ValidationStatus.ABSTAINED:
                return self._abstain_with_reason(
                    claim,
                    FailReason.L4_NO_CROSS_VALIDATION,
                    "L4 evidence requires cross-validation with L1-L3",
                )
            return self._fail(
                claim, FailReason.L4_NO_CROSS_VALIDATION,
                "L4 evidence requires cross-validation with L1-L3",
            )

        passed_evidences: list[Evidence] = []
        for ev in found_evidences:
            locator = CitationLocator.from_evidence(ev)
            loc_result = validate_locator(
                locator,
                decision_at,
                snapshot_resolver=self._snapshot_resolver,
            )
            if loc_result.all_passed:
                replay_result = self._replay_locator(locator, ev)
                if replay_result is not None and not replay_result.valid:
                    return self._fail(
                        claim,
                        FailReason.NOT_LOCATABLE,
                        replay_result.reason_code,
                        evidences_checked=len(found_evidences),
                        evidences_passed=len(passed_evidences),
                    )
                passed_evidences.append(ev)
            else:
                return self._fail(
                    claim,
                    _fail_reason_from_locator(loc_result),
                    "; ".join(loc_result.reasons),
                    evidences_checked=len(found_evidences),
                    evidences_passed=len(passed_evidences),
                )

        if len(passed_evidences) < self._min_evidence:
            return self._abstain(
                claim,
                f"Insufficient valid evidence: {len(passed_evidences)}/{self._min_evidence}",
            )

        claim_conflicts = (
            precomputed_conflicts
            if precomputed_conflicts is not None
            else detect_conflicts([claim], evidences).get(claim.claim_id, [])
        )
        all_conflicts = list(claim.conflicts) + claim_conflicts

        capped = claim.confidence
        requires_counter_review = False
        if all_conflicts:
            requires_counter_review = True
            high = any(c.severity == ConflictSeverity.HIGH for c in all_conflicts)
            cap = self._high_conflict_cap if high else self._conflict_cap
            capped = min(claim.confidence, cap)

        return ValidationResult(
            claim_id=claim.claim_id,
            status=ValidationStatus.PASS,
            reason=f"Passed with {len(passed_evidences)} valid evidences",
            original_confidence=claim.confidence,
            capped_confidence=capped,
            conflicts_found=len(all_conflicts),
            evidences_checked=len(found_evidences),
            evidences_passed=len(passed_evidences),
            requires_counter_review=requires_counter_review,
        )

    def validate_batch(
        self,
        claims: list[Claim],
        evidences: dict[str, Evidence],
        decision_at: datetime,
    ) -> ValidationReport:
        """Validate a batch of claims and produce an aggregated report.

        Args:
            claims: Claims to validate.
            evidences: Mapping from evidence_id to Evidence.
            decision_at: Decision timestamp.

        Returns:
            A ValidationReport summarizing all results.
        """
        results: list[ValidationResult] = []
        conflicts_map = detect_conflicts(claims, evidences)
        for claim in claims:
            result = self.validate_claim(
                claim,
                evidences,
                decision_at,
                precomputed_conflicts=conflicts_map.get(claim.claim_id, []),
            )
            results.append(result)

        passed = sum(1 for r in results if r.status == ValidationStatus.PASS)
        failed = sum(1 for r in results if r.status == ValidationStatus.FAIL)
        abstained = sum(1 for r in results if r.status == ValidationStatus.ABSTAINED)

        return ValidationReport(
            results=results,
            total=len(results),
            passed=passed,
            failed=failed,
            abstained=abstained,
        )

    def _replay_locator(self, locator: CitationLocator, evidence: Evidence):
        """Replay locator against snapshot content when available."""
        if self._snapshot_resolver is None:
            return None
        if not evidence.snapshot_id or not evidence.snapshot_hash:
            return None
        if not evidence.content:
            return None
        return LocatorValidator(self._snapshot_resolver).validate(
            snapshot_id=evidence.snapshot_id,
            snapshot_hash=evidence.snapshot_hash,
            locator=locator,
            expected_text=evidence.content,
        )

    def _fail(
        self,
        claim: Claim,
        reason: FailReason,
        message: str,
        *,
        evidences_checked: int = 0,
        evidences_passed: int = 0,
    ) -> ValidationResult:
        """Return a FAIL result for a claim.

        Args:
            claim: The claim being validated.
            reason: Categorized failure reason.
            message: Human-readable failure message.
            evidences_checked: Number of evidence items examined.
            evidences_passed: Number of evidence items that passed.

        Returns:
            A ValidationResult with status FAIL.
        """
        return ValidationResult(
            claim_id=claim.claim_id,
            status=ValidationStatus.FAIL,
            reason=message,
            fail_reason=reason,
            original_confidence=claim.confidence,
            capped_confidence=0.0,
            evidences_checked=evidences_checked,
            evidences_passed=evidences_passed,
        )

    def _abstain(self, claim: Claim, message: str) -> ValidationResult:
        """Return an ABSTAINED result for a claim.

        Args:
            claim: The claim being validated.
            message: Human-readable explanation.

        Returns:
            A ValidationResult with status ABSTAINED.
        """
        return ValidationResult(
            claim_id=claim.claim_id,
            status=ValidationStatus.ABSTAINED,
            reason=message,
            fail_reason=FailReason.INSUFFICIENT_EVIDENCE,
            original_confidence=claim.confidence,
            capped_confidence=0.0,
        )

    def _abstain_with_reason(
        self,
        claim: Claim,
        reason: FailReason,
        message: str,
    ) -> ValidationResult:
        """Return an ABSTAINED result with an explicit categorized reason."""
        return ValidationResult(
            claim_id=claim.claim_id,
            status=ValidationStatus.ABSTAINED,
            reason=message,
            fail_reason=reason,
            original_confidence=claim.confidence,
            capped_confidence=0.0,
        )


def _fail_reason_from_locator(result: LocatorValidationResult) -> FailReason:
    """Map a locator validation failure to a stable failure reason.

    Args:
        result: The locator validation result to map.

    Returns:
        A FailReason matching the locator failure.
    """
    reasons = " ".join(result.reasons).lower()
    if "lookahead" in reasons:
        return FailReason.LOOKAHEAD
    if "web search" in reasons or "snapshot" in reasons:
        return FailReason.WEBSEARCH_NO_ORIGINAL
    if "not locatable" in reasons:
        return FailReason.NOT_LOCATABLE
    return FailReason.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def validate_claims_with_audit(
    claims: list[Claim],
    evidences: dict[str, Evidence],
    decision_at: datetime,
    validator: CitationValidator | None = None,
    auditor: ValidationAuditor | None = None,
) -> tuple[ValidationReport, ValidationAuditor]:
    """Validate claims and append each result to an audit trail.

    Args:
        claims: Claims to validate.
        evidences: Mapping from evidence_id to Evidence.
        decision_at: Decision timestamp.
        validator: Optional custom CitationValidator.
        auditor: Optional custom ValidationAuditor.

    Returns:
        A tuple of (validation report, auditor).
    """
    val = validator or CitationValidator()
    aud = auditor or ValidationAuditor()

    report = val.validate_batch(claims, evidences, decision_at)
    for result in report.results:
        aud.log(result)

    return report, aud
