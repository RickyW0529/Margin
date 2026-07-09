"""Tests for reusable document-to-Markdown conversion.

This module verifies that the document format router detects all common
input formats, that the Docling Markdown converter routes every supported
format through a single backend, and that the converter fails closed with
a ``DoclingUnavailableError`` when Docling is not installed and fallback
is disabled.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest

from margin.documents.markdown import (
    DoclingMarkdownConverter,
    DoclingUnavailableError,
    DocumentFormat,
    DocumentFormatRouter,
    MarkdownConversionRequest,
    MarkdownConversionResult,
)


class FakeDoclingBackend:
    """Small fake backend that records conversion requests.."""

    def __init__(self) -> None:
        """Initialize the fake backend with an empty request list.

        Returns:
            None: .
        """
        self.requests: list[MarkdownConversionRequest] = []

    def convert(self, request: MarkdownConversionRequest) -> MarkdownConversionResult:
        """Return a deterministic Markdown conversion result.

        Args:
            request: MarkdownConversionRequest: .

        Returns:
            MarkdownConversionResult: .
        """
        self.requests.append(request)
        return MarkdownConversionResult(
            document_id=request.document_id,
            source_url=request.source_url,
            content_type=request.content_type,
            document_format=request.document_format,
            markdown=f"# converted {request.document_format.value}\n\n{request.source_url}",
            json_document={"format": request.document_format.value},
            page_images=("page-1.png",) if request.document_format == DocumentFormat.PDF else (),
            tables=({"table_id": "table_1", "rows": 1},)
            if request.document_format in {DocumentFormat.PDF, DocumentFormat.XLSX}
            else (),
            parser_name="fake_docling",
            warnings=(),
        )


def test_document_format_router_detects_common_input_formats() -> None:
    """Verify the router detects all formats the shared Docling interface must support.

    Returns:
        None: .
    """
    router = DocumentFormatRouter()

    assert router.detect(content_type="application/pdf", source_url=None) == DocumentFormat.PDF
    assert router.detect(content_type="text/html", source_url=None) == DocumentFormat.HTML
    assert (
        router.detect(content_type=None, source_url="https://x/report.docx") == DocumentFormat.DOCX
    )
    assert (
        router.detect(content_type=None, source_url="https://x/report.xlsx") == DocumentFormat.XLSX
    )
    assert router.detect(content_type="text/csv", source_url=None) == DocumentFormat.CSV
    assert router.detect(content_type="application/json", source_url=None) == DocumentFormat.JSON
    assert router.detect(content_type="text/plain", source_url=None) == DocumentFormat.TEXT


@pytest.mark.parametrize(
    ("content_type", "source_url", "expected_format"),
    [
        ("application/pdf", "https://example.com/report.pdf", DocumentFormat.PDF),
        ("text/html", "https://example.com/news.html", DocumentFormat.HTML),
        (None, "https://example.com/report.docx", DocumentFormat.DOCX),
        (None, "https://example.com/table.xlsx", DocumentFormat.XLSX),
        ("text/csv", "https://example.com/table.csv", DocumentFormat.CSV),
        ("application/json", "https://example.com/data.json", DocumentFormat.JSON),
        ("text/plain", "https://example.com/article.txt", DocumentFormat.TEXT),
    ],
)
def test_docling_markdown_converter_routes_every_format_to_backend(
    content_type: str | None,
    source_url: str,
    expected_format: DocumentFormat,
) -> None:
    """Verify the converter normalizes all supported inputs into Markdown through one backend.

    Args:
        content_type: str | None: .
        source_url: str: .
        expected_format: DocumentFormat: .

    Returns:
        None: .
    """
    backend = FakeDoclingBackend()
    converter = DoclingMarkdownConverter(backend=backend)

    result = converter.convert(
        content=b"raw content",
        document_id="doc_1",
        source_url=source_url,
        content_type=content_type,
    )

    assert result.document_format == expected_format
    assert result.markdown.startswith(f"# converted {expected_format.value}")
    assert result.parser_name == "fake_docling"
    assert backend.requests[0].document_format == expected_format


def test_docling_markdown_converter_reports_missing_docling_without_fallback() -> None:
    """Verify production callers can fail closed when Docling is not installed.

    Returns:
        None: .
    """
    converter = DoclingMarkdownConverter(backend=None, allow_fallback=False)

    with pytest.raises(DoclingUnavailableError, match="docling"):
        converter.convert(
            content=b"raw content",
            document_id="doc_missing",
            source_url="https://example.com/report.pdf",
            content_type="application/pdf",
        )


def test_docling_backend_enables_pdf_ocr_with_onnxruntime_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify real Docling backend construction enables PDF OCR with onnxruntime.

    Args:
        monkeypatch: pytest.MonkeyPatch: .

    Returns:
        None: .
    """
    captured: dict[str, object] = {}

    class FakeDocumentConverter:
        """Class implementing FakeDocumentConverter.."""

        def __init__(self, **kwargs: object) -> None:
            """Helper _init__.

            Args:
                **kwargs: object: .

            Returns:
                None: .
            """
            captured["converter_kwargs"] = kwargs

    class FakePdfFormatOption:
        """Class implementing FakePdfFormatOption.."""

        def __init__(self, *, pipeline_options: object) -> None:
            """Helper _init__.

            Args:
                pipeline_options: object: .

            Returns:
                None: .
            """
            captured["pipeline_options"] = pipeline_options

    class FakePdfPipelineOptions:
        """Class implementing FakePdfPipelineOptions.."""

        def __init__(self) -> None:
            """Helper _init__.

            Returns:
                None: .
            """
            self.do_ocr = False
            self.ocr_options = None

    class FakeRapidOcrOptions:
        """Class implementing FakeRapidOcrOptions.."""

        def __init__(self, *, backend: str, lang: list[str]) -> None:
            """Helper _init__.

            Args:
                backend: str: .
                lang: list[str]: .

            Returns:
                None: .
            """
            self.backend = backend
            self.lang = lang

    document_converter_module = ModuleType("docling.document_converter")
    document_converter_module.DocumentConverter = FakeDocumentConverter
    document_converter_module.PdfFormatOption = FakePdfFormatOption

    base_models_module = ModuleType("docling.datamodel.base_models")
    base_models_module.InputFormat = SimpleNamespace(PDF="pdf")

    pipeline_options_module = ModuleType("docling.datamodel.pipeline_options")
    pipeline_options_module.PdfPipelineOptions = FakePdfPipelineOptions
    pipeline_options_module.RapidOcrOptions = FakeRapidOcrOptions

    monkeypatch.setitem(sys.modules, "docling", ModuleType("docling"))
    monkeypatch.setitem(sys.modules, "docling.document_converter", document_converter_module)
    monkeypatch.setitem(sys.modules, "docling.datamodel", ModuleType("docling.datamodel"))
    monkeypatch.setitem(sys.modules, "docling.datamodel.base_models", base_models_module)
    monkeypatch.setitem(
        sys.modules,
        "docling.datamodel.pipeline_options",
        pipeline_options_module,
    )

    backend = DoclingMarkdownConverter._load_docling_backend()

    assert backend is not None
    assert captured["pipeline_options"].do_ocr is True
    assert captured["pipeline_options"].ocr_options.backend == "onnxruntime"
    assert captured["pipeline_options"].ocr_options.lang == ["chinese"]
