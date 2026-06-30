"""Deterministic materiality scoring for acquired documents."""

from __future__ import annotations

from margin.news.models import DocumentMaterialityScore


class DocumentMaterialityService:
    """Score document relevance/materiality without using AI state decisions."""

    RULES: tuple[tuple[str, tuple[str, ...], str, str, float], ...] = (
        (
            "regulatory_penalty",
            ("监管处罚", "行政处罚", "立案调查"),
            "negative",
            "regulatory_penalty",
            0.95,
        ),
        (
            "trading_status_change",
            ("停牌", "复牌"),
            "neutral",
            "trading_status_change",
            0.9,
        ),
        (
            "major_contract",
            ("重大合同", "中标", "订单"),
            "positive",
            "major_contract",
            0.8,
        ),
        (
            "litigation",
            ("诉讼", "仲裁"),
            "negative",
            "litigation",
            0.85,
        ),
        (
            "control_change",
            ("控制权", "实控人", "股权转让"),
            "neutral",
            "control_change",
            0.9,
        ),
    )

    def __init__(self, scoring_version: str = "materiality-v0.2.0") -> None:
        """Initialize the materiality service.

        Args:
            scoring_version: Version label for the scoring rules, used for audit and
                deduplication of persisted scores.
        """
        self.scoring_version = scoring_version

    def score(
        self,
        *,
        title: str,
        content: str | None,
        symbols: tuple[str, ...],
        target_symbol: str,
        source_level: int,
        event_id: str | None = None,
    ) -> DocumentMaterialityScore:
        """Return a deterministic score for one document/security relation.

        Args:
            title: Document title.
            content: Document body text, if available.
            symbols: Tuple of security symbols mentioned in the document.
            target_symbol: Security symbol to score relevance against.
            source_level: Numeric source level of the document (1-5).
            event_id: Optional event identifier to attach to the score.

        Returns:
            A ``DocumentMaterialityScore`` with deterministic relevance, materiality,
            novelty, and trust flags.
        """
        text = f"{title} {content or ''}"
        trigger_type = "general_news"
        risk_polarity = "neutral"
        materiality_score = 0.35
        reason_codes: list[str] = []
        for _, keywords, polarity, reason, score in self.RULES:
            if any(keyword in text for keyword in keywords):
                trigger_type = reason
                risk_polarity = polarity
                materiality_score = score
                reason_codes.append(reason)
                break

        relevance_score = 1.0 if target_symbol in symbols else 0.25
        novelty_score = 0.5
        is_material = relevance_score >= 0.8 and materiality_score >= 0.75
        is_untrusted = source_level >= 4
        return DocumentMaterialityScore(
            event_id=event_id,
            security_id=target_symbol,
            relevance_score=relevance_score,
            materiality_score=materiality_score,
            novelty_score=novelty_score,
            trigger_type=trigger_type,
            risk_polarity=risk_polarity,
            is_material=is_material,
            reason_codes=tuple(reason_codes or (trigger_type,)),
            scoring_version=self.scoring_version,
            is_untrusted_external_text=is_untrusted,
            can_directly_change_research_state=is_material and source_level <= 3,
        )


__all__ = ["DocumentMaterialityService"]
