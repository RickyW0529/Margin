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
    """Classification of claim types."""

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
    """Distinguish facts from inferences (architecture §10.1 goal)."""

    FACT = "fact"
    INFERENCE = "inference"
    UNKNOWN = "unknown"


class ConflictSeverity(StrEnum):
    """Severity level of a conflict."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ---------------------------------------------------------------------------
# Evidence — a single evidence record built from a Chunk
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    """A single evidence record (maps to architecture §5.3 EVIDENCE_CLAIM entity).

    Built from a Chunk produced by 04-text_indexing, carrying complete locator fields.
    Immutable after persistence.

    Attributes:
        evidence_id: Unique identifier for this evidence record.
        chunk_id: Identifier of the originating chunk.
        document_id: Identifier of the originating document.
        source_type: Source type string (e.g. filing_pdf, web_page, table, api_record,
            user_file).
        source_url: Optional URL of the original source.
        source_name: Optional human-readable source name.
        source_level: Source level priority (L1-L5).
        content_hash: Hash of the evidence content.
        content: Text content of the evidence.
        symbol: Optional ticker symbol associated with the evidence.
        published_at: Publication timestamp (UTC).
        available_at: Availability timestamp (UTC).
        retrieved_at: Retrieval timestamp (UTC).
        page: Optional page number in the original document.
        section: Optional section name in the original document.
        paragraph_index: Optional paragraph index in the original document.
        table_id: Optional table identifier.
        row_id: Optional row identifier.
        quote_span: Optional character span tuple (start, end).
        snapshot_id: Optional snapshot identifier.
        snapshot_hash: Optional snapshot content hash.
    """

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
    section: str | None = None
    paragraph_index: int | None = None
    table_id: str | None = None
    row_id: str | None = None
    quote_span: tuple[int, int] | None = None
    snapshot_id: str | None = None
    snapshot_hash: str | None = None

    model_config = {"frozen": True}

    @field_validator("published_at", "available_at", "retrieved_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime) -> datetime:
        """Normalize timestamp fields to UTC.

        Args:
            value: A datetime value to normalize.

        Returns:
            The datetime normalized to UTC.
        """
        return ensure_utc(value)

    @field_validator("quality_score")
    @classmethod
    def validate_quality_score(cls, value: float | None) -> float | None:
        """Validate that an optional quality score is within [0, 1]."""
        if value is None:
            return None
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"quality_score must be in [0, 1], got {value}")
        return value

    @property
    def can_change_research_state(self) -> bool:
        """Return whether this evidence may directly change research/position state.

        Only L1-L3 sources can change state; L4/L5 cannot (architecture §6.2.1).

        Returns:
            True if the evidence source level is L3 or higher priority, else False.
        """
        return self.source_level <= SourceLevel.L3

    @property
    def effective_quality_score(self) -> float:
        """Return the explicit quality score or the default score for the source level."""
        return self.quality_score if self.quality_score is not None else quality_score_for_level(
            self.source_level
        )

    @property
    def is_locatable(self) -> bool:
        """Return whether the evidence can be located in the original source.

        Requires at least a source_url plus one structural locator field.

        Returns:
            True if both source_url and a structural locator are present.
        """
        has_structural = (
            self.page is not None
            or bool(self.section)
            or self.paragraph_index is not None
            or bool(self.table_id)
            or bool(self.row_id)
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
            chunk: A Chunk object containing locator fields and source level.
            source_type: Source type; if None, inferred from chunk.doc_type.

        Returns:
            A new Evidence instance.
        """
        inferred_type = source_type or _infer_source_type(chunk)
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
            page=chunk.page,
            section=chunk.section,
            paragraph_index=chunk.paragraph_index,
            table_id=chunk.table_id,
            row_id=chunk.row_id,
            quote_span=chunk.quote_span,
            snapshot_id=getattr(chunk, "snapshot_id", None),
            snapshot_hash=getattr(chunk, "snapshot_hash", None),
        )


def _infer_source_type(chunk: Any) -> str:
    """Infer source_type from a chunk's doc_type.

    Args:
        chunk: A chunk object with a doc_type attribute.

    Returns:
        The inferred source type string.
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
        source_level: Source priority level.

    Returns:
        Default score in [0, 1] used when no explicit quality score is attached.
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
    """Conflict record (architecture §10.3 conflicts field).

    Created when multiple pieces of evidence provide opposite support for the same claim.

    Attributes:
        conflict_id: Unique identifier for this conflict record.
        claim_id: Identifier of the claim involved in the conflict.
        conflicting_evidence_ids: IDs of the evidence that conflict with each other.
        description: Human-readable description of the conflict.
        severity: Severity level of the conflict.
    """

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
    """Evidence Claim (architecture §10.3).

    Each key research conclusion is encapsulated as a Claim, including fact/inference marking,
    evidence references, confidence, conflict list, effective timestamp, and citation locators.
    Immutable after persistence.

    Attributes:
        claim_id: Unique identifier for this claim.
        claim_type: Classification of the claim.
        statement: Human-readable claim statement.
        fact_or_inference: Whether the claim is a fact, inference, or unknown.
        evidence_ids: List of referenced evidence IDs.
        confidence: Confidence score in [0, 1].
        conflicts: List of conflict records associated with the claim.
        effective_at: Timestamp when the claim becomes effective (UTC).
        symbol: Optional ticker symbol associated with the claim.
    """

    claim_id: str
    claim_type: ClaimType = ClaimType.CUSTOM
    statement: str
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
            value: A datetime value to normalize.

        Returns:
            The datetime normalized to UTC.
        """
        return ensure_utc(value)

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        """Validate that confidence is within the valid range [0, 1].

        Args:
            value: A confidence score.

        Returns:
            The validated confidence score.

        Raises:
            ValueError: If value is outside [0, 1].
        """
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {value}")
        return value

    @property
    def has_conflict(self) -> bool:
        """Return whether the claim has any conflicts.

        Returns:
            True if the claim has one or more conflicts.
        """
        return len(self.conflicts) > 0

    @property
    def has_evidence(self) -> bool:
        """Return whether the claim references any evidence.

        Returns:
            True if the claim has one or more evidence references.
        """
        return len(self.evidence_ids) > 0

    @property
    def conflict_confidence_cap(self) -> float:
        """Return the confidence cap when conflicts exist (architecture §25).

        When a claim has conflicts, its effective confidence is capped to reduce reliance on
        disputed conclusions.

        Returns:
            The original confidence if no conflicts exist; otherwise the capped value.
        """
        if not self.has_conflict:
            return self.confidence
        high_severity = any(
            c.severity == ConflictSeverity.HIGH for c in self.conflicts
        )
        if high_severity:
            return min(self.confidence, 0.3)
        return min(self.confidence, 0.5)

    @property
    def is_fact(self) -> bool:
        """Return whether the claim is marked as a fact (not an inference).

        Returns:
            True if fact_or_inference is FACT.
        """
        return self.fact_or_inference == FactOrInference.FACT

    @property
    def is_inference(self) -> bool:
        """Return whether the claim is marked as an inference.

        Returns:
            True if fact_or_inference is INFERENCE.
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
        statement: The claim statement text.
        claim_type: The claim classification.
        fact_or_inference: Whether the claim is a fact, inference, or unknown.
        evidence_ids: Optional list of referenced evidence IDs.
        confidence: Optional initial confidence score in [0, 1].
        conflicts: Optional list of conflict records.
        locator: Optional primary citation locator snapshot.
        symbol: Optional associated ticker symbol.
        effective_at: Optional effective timestamp; defaults to now (UTC).

    Returns:
        A new Claim instance.
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
        claim_id: The ID of the claim involved in the conflict.
        conflicting_evidence_ids: IDs of the evidence that conflict with each other.
        description: Human-readable conflict description.
        severity: Conflict severity level.

    Returns:
        A new ConflictRecord instance.
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

    Rules:
        - Same claim_type with opposite statement direction (support vs oppose) marks a conflict.
        - Large source_level gap within the same claim's evidence (L1 vs L5) marks a conflict.

    Args:
        claims: List of claims to check.
        evidences: Mapping from evidence_id to Evidence.

    Returns:
        Mapping from claim_id to a list of ConflictRecord instances.
    """
    conflicts_map: dict[str, list[ConflictRecord]] = {}

    for claim in claims:
        claim_conflicts: list[ConflictRecord] = []

        claim_evidence = [
            evidences[eid] for eid in claim.evidence_ids
            if eid in evidences
        ]

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
        stmt_a: First statement.
        stmt_b: Second statement.

    Returns:
        True if one statement contains a positive marker and the other contains the matching
        negative marker.
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

    L5 evidence may only trigger investigation and must not change research/position state.
    A claim supported solely by L5 evidence cannot directly change state.

    Args:
        claim: The claim to check.
        evidences: Mapping from evidence_id to Evidence.

    Returns:
        True if the claim passes the L5 restriction (has at least one non-L5 evidence);
        False if it relies only on L5 evidence or has no evidence.
    """
    claim_evidence = [
        evidences[eid] for eid in claim.evidence_ids
        if eid in evidences
    ]
    if not claim_evidence:
        return False

    has_non_l5 = any(e.source_level < SourceLevel.L5 for e in claim_evidence)
    return has_non_l5
