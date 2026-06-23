"""Document materiality scoring tests for v0.2 news refresh."""

from __future__ import annotations

from margin.news.materiality import DocumentMaterialityService


def test_regulatory_penalty_is_material_for_linked_company() -> None:
    """regulatory penalty is material for linked company."""
    service = DocumentMaterialityService(scoring_version="materiality-v0.2.0")

    score = service.score(
        title="关于平安银行收到监管处罚的公告",
        content="监管机构对公司处以罚款并要求整改。",
        symbols=("000001.SZ",),
        target_symbol="000001.SZ",
        source_level=1,
    )

    assert score.is_material is True
    assert score.trigger_type == "regulatory_penalty"
    assert "regulatory_penalty" in score.reason_codes
    assert score.can_directly_change_research_state is True


def test_websearch_text_is_marked_untrusted() -> None:
    """websearch text is marked untrusted."""
    service = DocumentMaterialityService(scoring_version="materiality-v0.2.0")

    score = service.score(
        title="媒体报道某公司签订合同",
        content="网页正文",
        symbols=("000001.SZ", "000002.SZ"),
        target_symbol="000001.SZ",
        source_level=4,
    )

    assert score.is_untrusted_external_text is True
    assert score.can_directly_change_research_state is False
