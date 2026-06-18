"""Citation Validator — Claim 校验、冲突封顶、ABSTAINED 判定、审计。

对应 spec 05 §7 风险与降级、架构 §10.2 RAG 工作流、§25 故障降级。
对应 plan 0503：
  0503.1 引用与来源等级校验 — 校验 evidence_ids、source_level、时点
  0503.2 冲突处理 — 冲突 Claim 提升反方审查、置信度封顶
  0503.3 ABSTAINED 判定 — 证据不足/冲突过高时拒绝输出高置信结论
  0503.4 校验审计 — 记录校验通过/失败原因

原则（架构 §25）：宁可 ABSTAINED，也不输出虚假的高置信结论。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator

from margin.evidence.locator import (
    CitationLocator,
    LocatorValidationResult,
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
# 0503.1 / 0503.3 校验状态
# ---------------------------------------------------------------------------


class ValidationStatus(StrEnum):
    """校验结果状态。"""

    PASS = "pass"
    FAIL = "fail"
    ABSTAINED = "abstained"


class FailReason(StrEnum):
    """校验失败原因分类。"""

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
# 校验结果
# ---------------------------------------------------------------------------


class ValidationResult(BaseModel):
    """单条 Claim 的校验结果。"""

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
        return ensure_utc(value)

    @property
    def should_suppress(self) -> bool:
        """是否应抑制该 Claim（不进入研究信号）。"""
        return self.status in (ValidationStatus.FAIL, ValidationStatus.ABSTAINED)


# ---------------------------------------------------------------------------
# 0503.4 校验审计
# ---------------------------------------------------------------------------


class ValidationAuditRecord(BaseModel):
    """校验审计记录（plan 0503.4：记录校验通过/失败原因）。

    落库后不可篡改。
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
        return ensure_utc(value)


class ValidationAuditor:
    """校验审计器 — 记录每次校验，支持审计回溯。"""

    def __init__(self) -> None:
        self._records: list[ValidationAuditRecord] = []

    def log(self, result: ValidationResult) -> ValidationAuditRecord:
        """记录一次校验结果。"""
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
        return list(self._records)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self._records if r.status == ValidationStatus.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self._records if r.status == ValidationStatus.FAIL)

    @property
    def abstained_count(self) -> int:
        return sum(1 for r in self._records if r.status == ValidationStatus.ABSTAINED)


# ---------------------------------------------------------------------------
# 批量校验报告
# ---------------------------------------------------------------------------


class ValidationReport(BaseModel):
    """批量校验报告。"""

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
        return ensure_utc(value)

    @property
    def should_suppress_research(self) -> bool:
        """是否应停止高置信研究信号输出。

        当存在 ABSTAINED 或高置信度 Claim 校验失败时，停止高置信输出
        （对应产品 §15 条目 8）。
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
        return [r for r in self.results if r.status == ValidationStatus.PASS]

    @property
    def failed_claims(self) -> list[ValidationResult]:
        return [r for r in self.results if r.status == ValidationStatus.FAIL]

    @property
    def abstained_claims(self) -> list[ValidationResult]:
        return [r for r in self.results if r.status == ValidationStatus.ABSTAINED]


# ---------------------------------------------------------------------------
# 0503 Citation Validator
# ---------------------------------------------------------------------------


class CitationValidator:
    """Citation Validator — 校验证据引用、来源等级与时点。

    校验流程（架构 §10.2 RAG 工作流）：
    1. 引用存在性校验（evidence_ids 非空且每条都能找到 Evidence）
    2. 来源等级校验（L5 不能单独支撑；L4 需与 L1-L3 交叉验证）
    3. 时点校验（available_at <= decision_at）
    4. 定位校验（每条 Evidence 的 locator 可回溯到原文）
    5. WebSearch 原文落校验（web_page 类型需有 snapshot）
    6. 冲突检测（同 claim_type 相反 statement → 冲突，置信度封顶）
    7. 证据不足判定（无通过校验的 Evidence → ABSTAINED）

    降级规则（架构 §25）：
    - 引用校验失败 → Claim 标记 FAIL，不进入研究信号
    - 证据冲突 → 置信度封顶，提升反方审查
    - 证据不足 → ABSTAINED
    - 原则：宁可 ABSTAINED，也不输出虚假的高置信结论
    """

    def __init__(
        self,
        min_evidence_count: int = 1,
        conflict_cap: float = 0.5,
        high_conflict_cap: float = 0.3,
        high_confidence_threshold: float = 0.7,
        snapshot_resolver: SnapshotResolver | None = None,
    ) -> None:
        self._min_evidence = min_evidence_count
        self._conflict_cap = conflict_cap
        self._high_conflict_cap = high_conflict_cap
        self._high_conf_threshold = high_confidence_threshold
        self._snapshot_resolver = snapshot_resolver

    def validate_claim(
        self,
        claim: Claim,
        evidences: dict[str, Evidence],
        decision_at: datetime,
        precomputed_conflicts: list | None = None,
    ) -> ValidationResult:
        """校验单个 Claim。

        Args:
            claim: 待校验的 Claim。
            evidences: evidence_id → Evidence 的字典。
            decision_at: 决策时点。

        Returns:
            ValidationResult。
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
        """批量校验 Claim，返回报告。"""
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

    def _fail(
        self,
        claim: Claim,
        reason: FailReason,
        message: str,
        *,
        evidences_checked: int = 0,
        evidences_passed: int = 0,
    ) -> ValidationResult:
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
        return ValidationResult(
            claim_id=claim.claim_id,
            status=ValidationStatus.ABSTAINED,
            reason=message,
            fail_reason=FailReason.INSUFFICIENT_EVIDENCE,
            original_confidence=claim.confidence,
            capped_confidence=0.0,
        )


def _fail_reason_from_locator(result: LocatorValidationResult) -> FailReason:
    """Map a locator validation failure to a stable failure reason."""
    reasons = " ".join(result.reasons).lower()
    if "lookahead" in reasons:
        return FailReason.LOOKAHEAD
    if "web search" in reasons or "snapshot" in reasons:
        return FailReason.WEBSEARCH_NO_ORIGINAL
    if "not locatable" in reasons:
        return FailReason.NOT_LOCATABLE
    return FailReason.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------


def validate_claims_with_audit(
    claims: list[Claim],
    evidences: dict[str, Evidence],
    decision_at: datetime,
    validator: CitationValidator | None = None,
    auditor: ValidationAuditor | None = None,
) -> tuple[ValidationReport, ValidationAuditor]:
    """校验 Claim 并记录审计。

    Args:
        claims: 待校验的 Claim 列表。
        evidences: evidence_id → Evidence 字典。
        decision_at: 决策时点。
        validator: 可选的自定义校验器。
        auditor: 可选的自定义审计器。

    Returns:
        (校验报告, 审计器)
    """
    val = validator or CitationValidator()
    aud = auditor or ValidationAuditor()

    report = val.validate_batch(claims, evidences, decision_at)
    for result in report.results:
        aud.log(result)

    return report, aud
