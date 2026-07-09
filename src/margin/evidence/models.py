"""RAG evidence data models: Evidence, Claim, ClaimType, FactOrInference, ConflictRecord.

Corresponds to spec 05 §3 / §4, architecture §10.3 evidence Claim structure,
and §6.1 source priority.
Corresponds to plan 0501:
    0501.1 Evidence level model — L1-L5 source grading and quality score integration.
    0501.2 Claim structure and fact_or_inference — structured Claim persistence.
    0501.3 conflicts conflict detection — multi-evidence conflict detection and tagging.
    0501.4 L5 usage restriction — L5 only triggers investigation, does not change research or
        position state.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from margin.news.models import SourceLevel, ensure_utc, utc_now

# ---------------------------------------------------------------------------
# 0501.2 Enumerations
# ---------------------------------------------------------------------------


class ClaimType(StrEnum):
    """Classification of claim types.."""

    CASH_FLOW_IMPROVEMENT = "cash_flow_improvement"
    VALUATION_CHANGE = "valuation_change"
    RISK_EVENT = "risk_event"
    GROWTH_SIGNAL = "growth_signal"
    EARNINGS_BEAT = "earnings_beat"
    DIVIDEND_CHANGE = "dividend_change"
    GOVERNANCE_ISSUE = "governance_issue"
    INDUSTRY_TREND = "industry_trend"
    CUSTOM = "custom"


class FactOrInference(StrEnum):
    """Distinguish facts from inferences (architecture §10.1 goal).."""

    FACT = "fact"
    INFERENCE = "inference"
    UNKNOWN = "unknown"


class ConflictSeverity(StrEnum):
    """Severity level of a conflict.."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ClaimStatus(StrEnum):
    """v0.2 validation status for a research claim.."""

    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONFLICTED = "conflicted"
    UNSUPPORTED = "unsupported"
    ABSTAINED = "abstained"


class ClaimEvidenceRole(StrEnum):
    """Role of an evidence item relative to a claim.."""

    SUPPORTS = "supports"
    REFUTES = "refutes"
    CONTEXT = "context"
    CONFLICTS = "conflicts"


class EvidencePackageQualityStatus(StrEnum):
    """Aggregate quality status for a frozen evidence package.."""

    USABLE = "usable"
    PARTIAL = "partial"
    ABSTAIN_REQUIRED = "abstain_required"
    INVALID = "invalid"


class EvidencePackage(BaseModel):
    """Frozen package of evidence/claim IDs served to one research decision.."""

    package_id: str
    version: int
    security_id: str
    decision_at: datetime
    scope_hash: str
    questions: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    claim_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]
    coverage: float = Field(ge=0.0, le=1.0)
    quality_status: EvidencePackageQualityStatus
    max_available_at: datetime | None
    retrieval_audit_id: str | None
    parent_package_id: str | None = None
    added_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}

    @field_validator("decision_at", "max_available_at")
    @classmethod
    def normalize_package_timestamps(cls, value: datetime | None) -> datetime | None:
        """Normalize package timestamps to UTC.

        Args:
            value: datetime | None: .

        Returns:
            datetime | None: .
        """
        return ensure_utc(value) if value is not None else None


class EvidenceConflict(BaseModel):
    """Conflict between two evidence records within a frozen package.."""

    conflict_id: str
    package_id: str
    version: int
    security_id: str
    evidence_id: str
    conflicting_evidence_id: str
    reason: str
    severity: ConflictSeverity = ConflictSeverity.MEDIUM
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Normalize conflict creation timestamp to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)


class ClaimEvidenceLink(BaseModel):
    """Append-only role link between a claim and an evidence record.."""

    claim_id: str
    evidence_id: str
    role: ClaimEvidenceRole
    rank: int = 0
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"frozen": True}

    @field_validator("created_at")
    @classmethod
    def normalize_link_created_at(cls, value: datetime) -> datetime:
        """Normalize link creation timestamp to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)


# ---------------------------------------------------------------------------
# Evidence — a single evidence record built from a Chunk
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """A single evidence record (maps to architecture §5.3 EVIDENCE_CLAIM entity).."""

    evidence_id: str
    chunk_id: str
    document_id: str
    source_type: str = "unknown"  # filing_pdf / web_page / table / api_record / user_file
    source_url: str | None = None
    source_name: str | None = None
    source_level: SourceLevel = SourceLevel.L4
    content_hash: str
    content: str = ""
    symbol: str | None = None
    quality_score: float | None = None
    published_at: datetime = Field(default_factory=utc_now)
    available_at: datetime = Field(default_factory=utc_now)
    retrieved_at: datetime = Field(default_factory=utc_now)
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    section: str | None = None
    paragraph_index: int | None = None
    dom_path: str | None = None
    table_id: str | None = None
    row_id: str | None = None
    column_id: str | None = None
    quote_span: tuple[int, int] | None = None
    snapshot_id: str | None = None
    snapshot_hash: str | None = None

    model_config = {"frozen": True}

    @field_validator("published_at", "available_at", "retrieved_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        """Normalize timestamp fields to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    @field_validator("quality_score")
    @classmethod
    def validate_quality_score(cls, value: float | None) -> float | None:
        """Validate that an optional quality score is within [0, 1].

        Args:
            value: float | None: .

        Returns:
            float | None: .
        """
        if value is None:
            return None
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"quality_score must be in [0, 1], got {value}")
        return value

    @property
    def can_change_research_state(self) -> bool:
        """Return whether this evidence may directly change research/position state.

        Returns:
            bool: .
        """
        return self.source_level <= SourceLevel.L3

    @property
    def effective_quality_score(self) -> float:
        """Return the explicit quality score or the default score for the source level.

        Returns:
            float: .
        """
        return (
            self.quality_score
            if self.quality_score is not None
            else quality_score_for_level(self.source_level)
        )

    @property
    def is_locatable(self) -> bool:
        """Return whether the evidence can be located in the original source.

        Returns:
            bool: .
        """
        has_structural = (
            self.page is not None
            or self.bbox is not None
            or bool(self.section)
            or self.paragraph_index is not None
            or bool(self.dom_path)
            or bool(self.table_id)
            or bool(self.row_id)
            or bool(self.column_id)
            or self.quote_span is not None
        )
        return bool(self.source_url) and has_structural

    @classmethod
    def from_chunk(
        cls,
        chunk: Any,
        source_type: str | None = None,
    ) -> Evidence:
        """Build an Evidence instance from a Chunk of the text indexing module.

        Args:
            chunk: Any: .
            source_type: str | None: .

        Returns:
            Evidence: .
        """
        inferred_type = source_type or _infer_source_type(chunk)
        locator = getattr(chunk, "locator", None)
        return cls(
            evidence_id=f"ev_{uuid.uuid4().hex[:12]}",
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            source_type=inferred_type,
            source_url=chunk.source_url,
            source_name=chunk.source_name,
            source_level=chunk.source_level,
            content_hash=chunk.content_hash,
            content=chunk.content,
            symbol=chunk.symbol,
            published_at=chunk.published_at,
            available_at=chunk.available_at,
            retrieved_at=utc_now(),
            page=chunk.page if chunk.page is not None else getattr(locator, "page", None),
            bbox=getattr(locator, "bbox", None),
            section=chunk.section or getattr(locator, "section", None),
            paragraph_index=(
                chunk.paragraph_index
                if chunk.paragraph_index is not None
                else getattr(locator, "paragraph_index", None)
            ),
            dom_path=getattr(locator, "dom_path", None),
            table_id=chunk.table_id or getattr(locator, "table_id", None),
            row_id=chunk.row_id or getattr(locator, "row_id", None),
            column_id=getattr(locator, "column_id", None),
            quote_span=chunk.quote_span or getattr(locator, "quote_span", None),
            snapshot_id=getattr(chunk, "snapshot_id", None),
            snapshot_hash=getattr(chunk, "snapshot_hash", None),
        )


def _infer_source_type(chunk: Any) -> str:
    """Infer source_type from a chunk's doc_type.

    Args:
        chunk: Any: .

    Returns:
        str: .
    """
    doc_type = str(getattr(chunk, "doc_type", "unknown"))
    if doc_type in ("annual_report", "quarterly_report", "filing"):
        return "filing_pdf"
    if doc_type == "news":
        return "web_page"
    if doc_type == "ir":
        return "web_page"
    if doc_type == "user_note":
        return "user_file"
    if "table" in doc_type:
        return "table"
    return "web_page"


def quality_score_for_level(source_level: SourceLevel) -> float:
    """Map a source level to a default evidence quality score.

    Args:
        source_level: SourceLevel: .

    Returns:
        float: .
    """
    return {
        SourceLevel.L1: 1.0,
        SourceLevel.L2: 0.88,
        SourceLevel.L3: 0.76,
        SourceLevel.L4: 0.52,
        SourceLevel.L5: 0.2,
    }[source_level]


# ---------------------------------------------------------------------------
# 0501.3 Conflict record
# ---------------------------------------------------------------------------


class ConflictRecord(BaseModel):
    """Conflict record (architecture §10.3 conflicts field).."""

    conflict_id: str
    claim_id: str
    conflicting_evidence_ids: list[str] = Field(default_factory=list)
    description: str = ""
    severity: ConflictSeverity = ConflictSeverity.MEDIUM

    model_config = {"frozen": True}


# ---------------------------------------------------------------------------
# 0501.2 Claim structure (architecture §10.3)
# ---------------------------------------------------------------------------


class Claim(BaseModel):
    """Evidence Claim (architecture §10.3).."""

    claim_id: str
    claim_type: ClaimType = ClaimType.CUSTOM
    statement: str
    status: ClaimStatus = ClaimStatus.UNSUPPORTED
    fact_or_inference: FactOrInference = FactOrInference.UNKNOWN
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    effective_at: datetime = Field(default_factory=utc_now)
    locator: dict[str, Any] | None = None
    symbol: str | None = None

    model_config = {"frozen": True}

    @field_validator("effective_at")
    @classmethod
    def normalize_effective_at(cls, value: datetime) -> datetime:
        """Normalize the effective timestamp to UTC.

        Args:
            value: datetime: .

        Returns:
            datetime: .
        """
        return ensure_utc(value)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        """Validate that confidence is within the valid range [0, 1].

        Args:
            value: float: .

        Returns:
            float: .
        """
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {value}")
        return value

    @property
    def has_conflict(self) -> bool:
        """Return whether the claim has any conflicts.

        Returns:
            bool: .
        """
        return len(self.conflicts) > 0

    @property
    def has_evidence(self) -> bool:
        """Return whether the claim references any evidence.

        Returns:
            bool: .
        """
        return len(self.evidence_ids) > 0

    @property
    def conflict_confidence_cap(self) -> float:
        """Return the confidence cap when conflicts exist (architecture §25).

        Returns:
            float: .
        """
        if not self.has_conflict:
            return self.confidence
        high_severity = any(c.severity == ConflictSeverity.HIGH for c in self.conflicts)
        if high_severity:
            return min(self.confidence, 0.3)
        return min(self.confidence, 0.5)

    @property
    def is_fact(self) -> bool:
        """Return whether the claim is marked as a fact (not an inference).

        Returns:
            bool: .
        """
        return self.fact_or_inference == FactOrInference.FACT

    @property
    def is_inference(self) -> bool:
        """Return whether the claim is marked as an inference.

        Returns:
            bool: .
        """
        return self.fact_or_inference == FactOrInference.INFERENCE


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------


def make_claim(
    statement: str,
    claim_type: ClaimType = ClaimType.CUSTOM,
    fact_or_inference: FactOrInference = FactOrInference.UNKNOWN,
    evidence_ids: list[str] | None = None,
    confidence: float = 0.0,
    conflicts: list[ConflictRecord] | None = None,
    locator: dict[str, Any] | None = None,
    symbol: str | None = None,
    effective_at: datetime | None = None,
) -> Claim:
    """Create a Claim with an auto-generated claim_id.

    Args:
        statement: str: .
        claim_type: ClaimType: .
        fact_or_inference: FactOrInference: .
        evidence_ids: list[str] | None: .
        confidence: float: .
        conflicts: list[ConflictRecord] | None: .
        locator: dict[str, Any] | None: .
        symbol: str | None: .
        effective_at: datetime | None: .

    Returns:
        Claim: .
    """
    return Claim(
        claim_id=f"clm_{uuid.uuid4().hex[:12]}",
        claim_type=claim_type,
        statement=statement,
        fact_or_inference=fact_or_inference,
        evidence_ids=evidence_ids or [],
        confidence=confidence,
        conflicts=conflicts or [],
        locator=locator,
        symbol=symbol,
        effective_at=effective_at or utc_now(),
    )


def make_conflict(
    claim_id: str,
    conflicting_evidence_ids: list[str],
    description: str = "",
    severity: ConflictSeverity = ConflictSeverity.MEDIUM,
) -> ConflictRecord:
    """Create a ConflictRecord with an auto-generated conflict_id.

    Args:
        claim_id: str: .
        conflicting_evidence_ids: list[str]: .
        description: str: .
        severity: ConflictSeverity: .

    Returns:
        ConflictRecord: .
    """
    return ConflictRecord(
        conflict_id=f"cfl_{uuid.uuid4().hex[:12]}",
        claim_id=claim_id,
        conflicting_evidence_ids=conflicting_evidence_ids,
        description=description,
        severity=severity,
    )


# ---------------------------------------------------------------------------
# 0501.3 / 0501.4 Conflict detection and L5 restriction
# ---------------------------------------------------------------------------


def detect_conflicts(
    claims: list[Claim],
    evidences: dict[str, Evidence],
) -> dict[str, list[ConflictRecord]]:
    """Detect conflicts among claims.

    Args:
        claims: list[Claim]: .
        evidences: dict[str, Evidence]: .

    Returns:
        dict[str, list[ConflictRecord]]: .
    """
    conflicts_map: dict[str, list[ConflictRecord]] = {}

    for claim in claims:
        claim_conflicts: list[ConflictRecord] = []

        claim_evidence = [evidences[eid] for eid in claim.evidence_ids if eid in evidences]

        levels = [e.source_level for e in claim_evidence]
        if levels and max(levels) == SourceLevel.L5 and min(levels) <= SourceLevel.L2:
            claim_conflicts.append(
                make_conflict(
                    claim_id=claim.claim_id,
                    conflicting_evidence_ids=[e.evidence_id for e in claim_evidence],
                    description="L5 evidence conflicts with L1-L2 evidence",
                    severity=ConflictSeverity.HIGH,
                )
            )

        for other in claims:
            if other.claim_id == claim.claim_id:
                continue
            if other.claim_type != claim.claim_type:
                continue
            if _is_contradictory(claim.statement, other.statement):
                conflict = make_conflict(
                    claim_id=claim.claim_id,
                    conflicting_evidence_ids=other.evidence_ids,
                    description=f"Contradicts claim {other.claim_id}: '{other.statement[:50]}'",
                    severity=ConflictSeverity.MEDIUM,
                )
                claim_conflicts.append(conflict)

        if claim_conflicts:
            conflicts_map[claim.claim_id] = claim_conflicts

    return conflicts_map


_CONTRADICTION_MARKERS = [
    ("改善", "恶化"),
    ("增长", "下降"),
    ("上升", "下跌"),
    ("盈利", "亏损"),
    ("正面", "负面"),
    ("提升", "下降"),
    ("增加", "减少"),
    ("好转", "恶化"),
]


def _is_contradictory(stmt_a: str, stmt_b: str) -> bool:
    """Return whether two statements have opposite direction.

    Args:
        stmt_a: str: .
        stmt_b: str: .

    Returns:
        bool: .
    """
    a_lower = stmt_a.lower()
    b_lower = stmt_b.lower()
    for pos_word, neg_word in _CONTRADICTION_MARKERS:
        if (pos_word in a_lower and neg_word in b_lower) or (
            neg_word in a_lower and pos_word in b_lower
        ):
            return True
    return False


def check_l5_restriction(
    claim: Claim,
    evidences: dict[str, Evidence],
) -> bool:
    """Check the L5 usage restriction (plan 0501.4).

    Args:
        claim: Claim: .
        evidences: dict[str, Evidence]: .

    Returns:
        bool: .
    """
    claim_evidence = [evidences[eid] for eid in claim.evidence_ids if eid in evidences]
    if not claim_evidence:
        return False

    has_non_l5 = any(e.source_level < SourceLevel.L5 for e in claim_evidence)
    return has_non_l5
