"""Tests for the public :mod:`margin.evidence` package API."""

from margin import evidence


def test_evidence_package_exposes_public_api() -> None:
    """Domain callers can import the evidence API from the package root.

    Returns:
        None: .
    """
    expected_exports = {
        "CitationLocator",
        "CitationValidator",
        "Claim",
        "ClaimEvidenceLink",
        "ClaimEvidenceRole",
        "ClaimStatus",
        "ClaimType",
        "ConflictRecord",
        "ConflictSeverity",
        "Evidence",
        "EvidenceConflict",
        "EvidenceConflictClassifier",
        "EvidencePackage",
        "EvidencePackageBuilder",
        "EvidencePackageQualityStatus",
        "EvidenceRepository",
        "FactOrInference",
        "FailReason",
        "LocatorReplayResult",
        "LocatorValidationResult",
        "LocatorValidator",
        "NewsContextEvidenceLink",
        "PointInTimeCheckResult",
        "ResearchEvidenceLink",
        "SnapshotResolver",
        "SourceType",
        "ValidationAuditRecord",
        "ValidationAuditor",
        "ValidationReport",
        "ValidationResult",
        "ValidationStatus",
        "WebSearchVerificationResult",
        "build_locator_from_html",
        "build_locator_from_pdf",
        "build_locator_from_table",
        "check_l5_restriction",
        "check_locators_point_in_time",
        "check_point_in_time",
        "detect_conflicts",
        "make_claim",
        "make_conflict",
        "quality_score_for_level",
        "validate_claims_with_audit",
        "validate_locator",
        "verify_websearch_original",
    }

    assert expected_exports == set(evidence.__all__)
    assert all(getattr(evidence, name) is not None for name in expected_exports)
