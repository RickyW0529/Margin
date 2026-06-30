"""Document normalization pipeline after Docling conversion.

The pipeline is shared by news acquisition and future research-report imports:
Docling performs format parsing, then lightweight review/repair/verification
agents normalize the Markdown before it enters RAG chunking.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from margin.documents.markdown import DoclingMarkdownConverter, MarkdownConversionResult


class IssueSeverity(StrEnum):
    """Severity of a document normalization issue."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class VerificationLevel(StrEnum):
    """Level reached by document verification."""

    TEXT_VERIFIED = "text_verified"
    VISUAL_VERIFIED = "visual_verified"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


class VisualVerificationStatus(StrEnum):
    """Status of optional screenshot/page-image verification."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED_NO_MULTIMODAL_MODEL = "skipped_no_multimodal_model"
    SKIPPED_NO_PAGE_IMAGES = "skipped_no_page_images"


class DocumentPipelineRequest(BaseModel):
    """Input payload for the full document normalization pipeline."""

    document_id: str
    content: bytes
    source_url: str | None = None
    content_type: str | None = None
    filename: str | None = None

    model_config = {"frozen": True}


class DocumentIssue(BaseModel):
    """Issue found by the review agent."""

    issue_id: str
    kind: str
    message: str
    severity: IssueSeverity = IssueSeverity.WARNING
    span_start: int | None = None
    span_end: int | None = None

    model_config = {"frozen": True}


class DocumentPatch(BaseModel):
    """Local repair patch tied to a specific reviewed issue."""

    issue_id: str
    span_start: int
    span_end: int
    before: str
    after: str
    reason: str

    model_config = {"frozen": True}


class TextVerificationResult(BaseModel):
    """Text-only verification result."""

    passed: bool
    notes: tuple[str, ...] = Field(default_factory=tuple)

    model_config = {"frozen": True}


class VisualVerificationResult(BaseModel):
    """Optional multimodal screenshot/page-image verification result."""

    status: VisualVerificationStatus
    notes: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """Return whether visual verification succeeded or was safely skipped."""
        return self.status in {
            VisualVerificationStatus.PASSED,
            VisualVerificationStatus.SKIPPED_NO_MULTIMODAL_MODEL,
            VisualVerificationStatus.SKIPPED_NO_PAGE_IMAGES,
        }

    model_config = {"frozen": True}


class RagChunk(BaseModel):
    """Small RAG-ready chunk produced from final Markdown."""

    chunk_id: str
    document_id: str
    content: str
    chunk_index: int
    total_chunks: int
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}


class DocumentPipelineAudit(BaseModel):
    """Audit details for review, repair, and verification."""

    issues: tuple[DocumentIssue, ...] = Field(default_factory=tuple)
    patches: tuple[DocumentPatch, ...] = Field(default_factory=tuple)
    text_verification: TextVerificationResult = Field(
        default_factory=lambda: TextVerificationResult(passed=True)
    )
    visual_verification: VisualVerificationResult = Field(
        default_factory=lambda: VisualVerificationResult(
            status=VisualVerificationStatus.SKIPPED_NO_MULTIMODAL_MODEL
        )
    )

    model_config = {"frozen": True}


class DocumentPipelineResult(BaseModel):
    """Final normalized document artifacts."""

    document_id: str
    conversion: MarkdownConversionResult
    final_markdown: str
    final_json: dict[str, Any]
    rag_chunks: tuple[RagChunk, ...]
    audit: DocumentPipelineAudit
    verification_level: VerificationLevel

    @property
    def visual_verification(self) -> VisualVerificationResult:
        """Return optional visual verification details."""
        return self.audit.visual_verification

    model_config = {"frozen": True}


class DocumentReviewAgent(Protocol):
    """Review agent protocol."""

    def review(self, conversion: MarkdownConversionResult) -> tuple[DocumentIssue, ...]:
        """Return issues in converted Markdown."""


class DocumentRepairAgent(Protocol):
    """Repair agent protocol."""

    def repair(self, markdown: str, issues: tuple[DocumentIssue, ...]) -> tuple[DocumentPatch, ...]:
        """Return local patches for reviewed issues."""


class DocumentVerifierAgent(Protocol):
    """Verifier protocol with optional multimodal support."""

    supports_multimodal: bool

    def verify_text(
        self,
        *,
        raw_markdown: str,
        final_markdown: str,
        issues: tuple[DocumentIssue, ...],
        patches: tuple[DocumentPatch, ...],
        tables: tuple[dict[str, Any], ...],
    ) -> TextVerificationResult:
        """Verify repaired Markdown with text-only artifacts."""

    def verify_visual(
        self,
        *,
        final_markdown: str,
        page_images: tuple[str, ...],
        json_document: dict[str, Any],
    ) -> VisualVerificationResult:
        """Verify final Markdown against page images when available."""


class DocumentSlimmingAgent(Protocol):
    """Final Markdown slimming protocol."""

    def slim(self, markdown: str) -> str:
        """Remove non-useful formatting noise from verified Markdown."""


class HeuristicReviewAgent:
    """Deterministic review agent for parser artifacts."""

    def review(self, conversion: MarkdownConversionResult) -> tuple[DocumentIssue, ...]:
        """Find common Docling/OCR issues without calling an LLM."""
        markdown = conversion.markdown
        issues: list[DocumentIssue] = []
        issue_number = 1

        if not markdown.strip():
            issues.append(
                DocumentIssue(
                    issue_id="issue_1",
                    kind="empty_markdown",
                    message="Converted Markdown is empty.",
                    severity=IssueSeverity.ERROR,
                )
            )
            return tuple(issues)

        for match in re.finditer(r"[�\ue000-\uf8ff]", markdown):
            issues.append(
                DocumentIssue(
                    issue_id=f"issue_{issue_number}",
                    kind="garbled_character",
                    message="Markdown contains replacement or private-use characters.",
                    span_start=match.start(),
                    span_end=match.end(),
                )
            )
            issue_number += 1

        for match in re.finditer(r"\n{3,}", markdown):
            issues.append(
                DocumentIssue(
                    issue_id=f"issue_{issue_number}",
                    kind="excessive_blank_lines",
                    message="Markdown contains excessive blank lines.",
                    severity=IssueSeverity.INFO,
                    span_start=match.start(),
                    span_end=match.end(),
                )
            )
            issue_number += 1

        repeated_lines = _repeated_noise_lines(markdown)
        for line in repeated_lines:
            start = markdown.find(line)
            if start < 0:
                continue
            issues.append(
                DocumentIssue(
                    issue_id=f"issue_{issue_number}",
                    kind="repeated_noise_line",
                    message=f"Repeated low-information line: {line[:40]}",
                    severity=IssueSeverity.INFO,
                    span_start=start,
                    span_end=start + len(line),
                )
            )
            issue_number += 1

        return tuple(issues)


class HeuristicRepairAgent:
    """Deterministic local repair agent."""

    def repair(self, markdown: str, issues: tuple[DocumentIssue, ...]) -> tuple[DocumentPatch, ...]:
        """Return issue-scoped patches without rewriting the whole document."""
        patches: list[DocumentPatch] = []
        for issue in issues:
            if issue.span_start is None or issue.span_end is None:
                continue
            before = markdown[issue.span_start : issue.span_end]
            if issue.kind == "garbled_character":
                after = "".join(char for char in before if not _is_garbled_char(char))
            elif issue.kind == "excessive_blank_lines":
                after = "\n\n"
            elif issue.kind == "repeated_noise_line":
                after = ""
            else:
                continue
            if before == after:
                continue
            patches.append(
                DocumentPatch(
                    issue_id=issue.issue_id,
                    span_start=issue.span_start,
                    span_end=issue.span_end,
                    before=before,
                    after=after,
                    reason=issue.kind,
                )
            )
        return tuple(patches)


class HeuristicVerifierAgent:
    """Text-first verifier that skips visual checks without multimodal support."""

    supports_multimodal = False

    def verify_text(
        self,
        *,
        raw_markdown: str,
        final_markdown: str,
        issues: tuple[DocumentIssue, ...],
        patches: tuple[DocumentPatch, ...],
        tables: tuple[dict[str, Any], ...],
    ) -> TextVerificationResult:
        """Verify patch provenance and basic content integrity."""
        del issues, tables
        if not final_markdown.strip():
            return TextVerificationResult(passed=False, notes=("final_markdown_empty",))
        for patch in patches:
            if not patch.before:
                return TextVerificationResult(
                    passed=False,
                    notes=(f"empty_patch_before:{patch.issue_id}",),
                )
            if patch.before not in raw_markdown:
                return TextVerificationResult(
                    passed=False,
                    notes=(f"patch_not_traceable:{patch.issue_id}",),
                )
        return TextVerificationResult(passed=True, notes=("text_verified",))

    def verify_visual(
        self,
        *,
        final_markdown: str,
        page_images: tuple[str, ...],
        json_document: dict[str, Any],
    ) -> VisualVerificationResult:
        """Skip visual verification for text-only providers."""
        del final_markdown, page_images, json_document
        return VisualVerificationResult(
            status=VisualVerificationStatus.SKIPPED_NO_MULTIMODAL_MODEL,
            notes=("no_multimodal_model",),
        )


class HeuristicSlimmingAgent:
    """Final deterministic Markdown slimming."""

    def slim(self, markdown: str) -> str:
        """Normalize whitespace while preserving document content."""
        lines = [line.rstrip() for line in markdown.splitlines()]
        slimmed = "\n".join(lines)
        slimmed = re.sub(r"\n{3,}", "\n\n", slimmed)
        return slimmed.strip()


class DocumentNormalizationPipeline:
    """Run conversion, review, repair, verification, slimming, and chunking."""

    def __init__(
        self,
        *,
        converter: Any | None = None,
        reviewer: DocumentReviewAgent | None = None,
        repairer: DocumentRepairAgent | None = None,
        verifier: DocumentVerifierAgent | None = None,
        slimmer: DocumentSlimmingAgent | None = None,
        max_chunk_chars: int = 1_200,
    ) -> None:
        """Initialize the pipeline with replaceable agents."""
        self._converter = converter or DoclingMarkdownConverter()
        self._reviewer = reviewer or HeuristicReviewAgent()
        self._repairer = repairer or HeuristicRepairAgent()
        self._verifier = verifier or HeuristicVerifierAgent()
        self._slimmer = slimmer or HeuristicSlimmingAgent()
        self._max_chunk_chars = max_chunk_chars

    def normalize(self, request: DocumentPipelineRequest) -> DocumentPipelineResult:
        """Normalize one source document into final Markdown, JSON, and RAG chunks."""
        conversion = self._converter.convert(
            content=request.content,
            document_id=request.document_id,
            source_url=request.source_url,
            content_type=request.content_type,
            filename=request.filename,
        )
        issues = self._reviewer.review(conversion)
        patches = self._repairer.repair(conversion.markdown, issues)
        repaired = _apply_patches(conversion.markdown, patches)
        slimmed = self._slimmer.slim(repaired)
        text_verification = self._verifier.verify_text(
            raw_markdown=conversion.markdown,
            final_markdown=slimmed,
            issues=issues,
            patches=patches,
            tables=conversion.tables,
        )
        visual_verification = self._verify_visual(
            final_markdown=slimmed,
            conversion=conversion,
        )
        verification_level = _verification_level(text_verification, visual_verification)
        final_markdown = (
            slimmed
            if verification_level != VerificationLevel.NEEDS_MANUAL_REVIEW
            else ""
        )
        chunks = _make_rag_chunks(
            document_id=request.document_id,
            markdown=final_markdown,
            max_chunk_chars=self._max_chunk_chars,
        )
        final_json = {
            "document_id": request.document_id,
            "source_url": request.source_url,
            "document_format": conversion.document_format.value,
            "parser_name": conversion.parser_name,
            "parse_status": conversion.parse_status,
            "verification_level": verification_level.value,
            "visual_verification": visual_verification.status.value,
            "issue_count": len(issues),
            "patch_count": len(patches),
            "table_count": len(conversion.tables),
            "chunk_count": len(chunks),
        }
        return DocumentPipelineResult(
            document_id=request.document_id,
            conversion=conversion,
            final_markdown=final_markdown,
            final_json=final_json,
            rag_chunks=chunks,
            audit=DocumentPipelineAudit(
                issues=issues,
                patches=patches,
                text_verification=text_verification,
                visual_verification=visual_verification,
            ),
            verification_level=verification_level,
        )

    def _verify_visual(
        self,
        *,
        final_markdown: str,
        conversion: MarkdownConversionResult,
    ) -> VisualVerificationResult:
        """Run visual verification only when the verifier can consume images."""
        if not self._verifier.supports_multimodal:
            return VisualVerificationResult(
                status=VisualVerificationStatus.SKIPPED_NO_MULTIMODAL_MODEL,
                notes=("no_multimodal_model",),
            )
        if not conversion.page_images:
            return VisualVerificationResult(
                status=VisualVerificationStatus.SKIPPED_NO_PAGE_IMAGES,
                notes=("no_page_images",),
            )
        return self._verifier.verify_visual(
            final_markdown=final_markdown,
            page_images=conversion.page_images,
            json_document=conversion.json_document,
        )


def _apply_patches(markdown: str, patches: tuple[DocumentPatch, ...]) -> str:
    """Apply non-overlapping local patches from the end of the document."""
    repaired = markdown
    for patch in sorted(patches, key=lambda item: item.span_start, reverse=True):
        repaired = repaired[: patch.span_start] + patch.after + repaired[patch.span_end :]
    return repaired


def _verification_level(
    text: TextVerificationResult,
    visual: VisualVerificationResult,
) -> VerificationLevel:
    """Resolve the final verification level."""
    if not text.passed or not visual.passed:
        return VerificationLevel.NEEDS_MANUAL_REVIEW
    if visual.status == VisualVerificationStatus.PASSED:
        return VerificationLevel.VISUAL_VERIFIED
    return VerificationLevel.TEXT_VERIFIED


def _make_rag_chunks(
    *,
    document_id: str,
    markdown: str,
    max_chunk_chars: int,
) -> tuple[RagChunk, ...]:
    """Split final Markdown into simple paragraph-preserving chunks."""
    if max_chunk_chars <= 0:
        raise ValueError("max_chunk_chars must be positive")

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", markdown) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for part in _split_long_block(paragraph, max_chunk_chars):
            candidate = f"{current}\n\n{part}" if current else part
            if len(candidate) <= max_chunk_chars:
                current = candidate
                continue
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)

    total = len(chunks)
    return tuple(
        RagChunk(
            chunk_id=_rag_chunk_id(document_id, content, index),
            document_id=document_id,
            content=content,
            chunk_index=index,
            total_chunks=total,
            metadata={"source": "document_normalization_pipeline"},
        )
        for index, content in enumerate(chunks)
    )


def _split_long_block(block: str, max_chunk_chars: int) -> list[str]:
    """Split one oversized Markdown block without dropping content."""
    if len(block) <= max_chunk_chars:
        return [block]

    lines = block.splitlines()
    if len(lines) <= 1:
        return _split_text_by_chars(block, max_chunk_chars)

    parts: list[str] = []
    current = ""
    for line in lines:
        line_parts = (
            _split_text_by_chars(line, max_chunk_chars)
            if len(line) > max_chunk_chars
            else [line]
        )
        for line_part in line_parts:
            candidate = f"{current}\n{line_part}" if current else line_part
            if len(candidate) <= max_chunk_chars:
                current = candidate
                continue
            if current:
                parts.append(current)
            current = line_part
    if current:
        parts.append(current)
    return parts


def _split_text_by_chars(text: str, max_chunk_chars: int) -> list[str]:
    """Hard-split an unbroken text span by character count."""
    return [
        text[start : start + max_chunk_chars]
        for start in range(0, len(text), max_chunk_chars)
        if text[start : start + max_chunk_chars].strip()
    ]


def _rag_chunk_id(document_id: str, content: str, index: int) -> str:
    """Create a deterministic pipeline chunk ID."""
    payload = f"{document_id}|{index}|{content}"
    return "rag_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _is_garbled_char(char: str) -> bool:
    """Return whether a single character is parser/OCR garbage."""
    return char == "�" or unicodedata.category(char) == "Co"


def _repeated_noise_lines(markdown: str) -> tuple[str, ...]:
    """Return short repeated low-information lines."""
    counts: dict[str, int] = {}
    for line in markdown.splitlines():
        normalized = line.strip()
        if not normalized or len(normalized) > 80:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    return tuple(
        line for line, count in counts.items() if count >= 3 and _looks_low_information(line)
    )


def _looks_low_information(line: str) -> bool:
    """Return whether a repeated line is likely page/header/footer noise."""
    if re.fullmatch(r"\d{1,6}", line):
        return True
    if len(line) <= 12 and not re.search(r"[\u4e00-\u9fff]{4,}", line):
        return True
    return False
