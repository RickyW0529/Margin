"""Tests for document normalization after Docling conversion."""

from __future__ import annotations

from margin.documents.markdown import DocumentFormat, MarkdownConversionResult
from margin.documents.pipeline import (
    DocumentNormalizationPipeline,
    DocumentPipelineRequest,
    VerificationLevel,
    VisualVerificationStatus,
)


class FakeMarkdownConverter:
    """Fake converter returning deterministic Markdown conversion output."""

    def __init__(self, result: MarkdownConversionResult) -> None:
        """Initialize the fake converter with one result."""
        self.result = result

    def convert(self, **kwargs):  # noqa: ANN003, ANN201
        """Return the configured conversion result."""
        return self.result.model_copy(
            update={
                "document_id": str(kwargs["document_id"]),
                "source_url": kwargs.get("source_url"),
                "content_type": kwargs.get("content_type"),
            }
        )


class MultimodalVerifier:
    """Verifier stub that records visual verification calls."""

    supports_multimodal = True

    def __init__(self) -> None:
        """Initialize an empty call list."""
        self.visual_calls: list[tuple[str, ...]] = []

    def verify_text(self, **kwargs):  # noqa: ANN003, ANN201
        """Accept text verification."""
        from margin.documents.pipeline import TextVerificationResult

        return TextVerificationResult(passed=True, notes=("text_ok",))

    def verify_visual(self, **kwargs):  # noqa: ANN003, ANN201
        """Record visual verification and accept it."""
        from margin.documents.pipeline import VisualVerificationResult

        page_images = tuple(kwargs["page_images"])
        self.visual_calls.append(page_images)
        return VisualVerificationResult(
            status=VisualVerificationStatus.PASSED,
            notes=("visual_ok",),
        )


def test_text_only_verifier_skips_visual_verification() -> None:
    """Text-only providers such as DeepSeek must not block the document flow."""
    converter = FakeMarkdownConverter(
        MarkdownConversionResult(
            document_id="ignored",
            document_format=DocumentFormat.PDF,
            markdown="# 平安银行年度报告\n\n正文内容",
            page_images=("page-1.png",),
            parser_name="docling",
        )
    )
    pipeline = DocumentNormalizationPipeline(converter=converter)

    result = pipeline.normalize(
        DocumentPipelineRequest(
            document_id="doc_1",
            content=b"raw",
            content_type="application/pdf",
            source_url="https://example.com/report.pdf",
        )
    )

    assert result.verification_level == VerificationLevel.TEXT_VERIFIED
    assert result.visual_verification.status == (
        VisualVerificationStatus.SKIPPED_NO_MULTIMODAL_MODEL
    )
    assert result.final_markdown == "# 平安银行年度报告\n\n正文内容"
    assert result.rag_chunks


def test_multimodal_verifier_runs_visual_verification_when_page_images_exist() -> None:
    """A multimodal verifier should receive Docling page images for screenshot checks."""
    converter = FakeMarkdownConverter(
        MarkdownConversionResult(
            document_id="ignored",
            document_format=DocumentFormat.PDF,
            markdown="# 平安银行年度报告\n\n正文内容",
            page_images=("page-1.png", "page-2.png"),
            parser_name="docling",
        )
    )
    verifier = MultimodalVerifier()
    pipeline = DocumentNormalizationPipeline(converter=converter, verifier=verifier)

    result = pipeline.normalize(
        DocumentPipelineRequest(
            document_id="doc_1",
            content=b"raw",
            content_type="application/pdf",
            source_url="https://example.com/report.pdf",
        )
    )

    assert result.verification_level == VerificationLevel.VISUAL_VERIFIED
    assert result.visual_verification.status == VisualVerificationStatus.PASSED
    assert verifier.visual_calls == [("page-1.png", "page-2.png")]


def test_review_repair_only_changes_problem_spans() -> None:
    """Repair should remove only reviewed problem spans before final chunking."""
    converter = FakeMarkdownConverter(
        MarkdownConversionResult(
            document_id="ignored",
            document_format=DocumentFormat.PDF,
            markdown="# 标题\n\n正文�内容\n\n\n\n尾段",
            parser_name="docling",
        )
    )
    pipeline = DocumentNormalizationPipeline(converter=converter)

    result = pipeline.normalize(
        DocumentPipelineRequest(
            document_id="doc_1",
            content=b"raw",
            content_type="application/pdf",
        )
    )

    assert "�" not in result.final_markdown
    assert "\n\n\n" not in result.final_markdown
    assert result.audit.issues
    assert result.audit.patches


def test_rag_chunking_splits_single_oversized_block() -> None:
    """A single long Docling block must not exceed the embedding chunk budget."""
    long_table = "\n".join(
        f"| 指标 {index} | {index} | {index + 1} |"
        for index in range(20)
    )
    converter = FakeMarkdownConverter(
        MarkdownConversionResult(
            document_id="ignored",
            document_format=DocumentFormat.PDF,
            markdown=long_table,
            parser_name="docling",
        )
    )
    pipeline = DocumentNormalizationPipeline(
        converter=converter,
        max_chunk_chars=120,
    )

    result = pipeline.normalize(
        DocumentPipelineRequest(
            document_id="doc_1",
            content=b"raw",
            content_type="application/pdf",
        )
    )

    assert len(result.rag_chunks) > 1
    assert all(len(chunk.content) <= 120 for chunk in result.rag_chunks)
    assert all(patch.before for patch in result.audit.patches)
    assert all(patch.issue_id for patch in result.audit.patches)
