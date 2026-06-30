"""Docling-backed document-to-Markdown conversion.

The interface lives outside the news package so later research-report imports can
reuse the same router and converter.
"""

from __future__ import annotations

import json
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class DocumentFormat(StrEnum):
    """Supported source document formats."""

    PDF = "pdf"
    HTML = "html"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    JSON = "json"
    TEXT = "text"
    UNKNOWN = "unknown"


class DoclingUnavailableError(RuntimeError):
    """Raised when Docling conversion is required but unavailable."""


class MarkdownConversionRequest(BaseModel):
    """Input payload for document-to-Markdown conversion."""

    document_id: str
    content: bytes
    document_format: DocumentFormat
    source_url: str | None = None
    content_type: str | None = None
    filename: str | None = None

    model_config = {"frozen": True}


class MarkdownConversionResult(BaseModel):
    """Canonical Markdown conversion artifact."""

    document_id: str
    markdown: str
    document_format: DocumentFormat
    source_url: str | None = None
    content_type: str | None = None
    json_document: dict[str, Any] = Field(default_factory=dict)
    page_images: tuple[str, ...] = Field(default_factory=tuple)
    tables: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    parser_name: str = "docling"
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    parse_status: str = "ready"

    model_config = {"frozen": True}


class MarkdownBackend(Protocol):
    """Backend protocol implemented by Docling and tests."""

    def convert(self, request: MarkdownConversionRequest) -> MarkdownConversionResult:
        """Convert a request into canonical Markdown."""


class DocumentFormatRouter:
    """Detect document format from Content-Type and URL/file extension."""

    CONTENT_TYPE_MAP: tuple[tuple[str, DocumentFormat], ...] = (
        ("pdf", DocumentFormat.PDF),
        ("html", DocumentFormat.HTML),
        ("wordprocessingml.document", DocumentFormat.DOCX),
        ("msword", DocumentFormat.DOCX),
        ("spreadsheetml.sheet", DocumentFormat.XLSX),
        ("excel", DocumentFormat.XLSX),
        ("csv", DocumentFormat.CSV),
        ("json", DocumentFormat.JSON),
        ("text/plain", DocumentFormat.TEXT),
        ("xml", DocumentFormat.TEXT),
    )
    EXTENSION_MAP: dict[str, DocumentFormat] = {
        ".pdf": DocumentFormat.PDF,
        ".html": DocumentFormat.HTML,
        ".htm": DocumentFormat.HTML,
        ".docx": DocumentFormat.DOCX,
        ".xlsx": DocumentFormat.XLSX,
        ".xls": DocumentFormat.XLSX,
        ".csv": DocumentFormat.CSV,
        ".json": DocumentFormat.JSON,
        ".txt": DocumentFormat.TEXT,
        ".md": DocumentFormat.TEXT,
    }

    def detect(
        self,
        *,
        content_type: str | None,
        source_url: str | None,
        filename: str | None = None,
    ) -> DocumentFormat:
        """Detect a document format from MIME type, filename, or URL."""
        normalized_content_type = (content_type or "").lower()
        for marker, document_format in self.CONTENT_TYPE_MAP:
            if marker in normalized_content_type:
                return document_format

        path = filename or urlparse(source_url or "").path
        suffix = Path(path).suffix.lower()
        return self.EXTENSION_MAP.get(suffix, DocumentFormat.UNKNOWN)


class DoclingMarkdownConverter:
    """Convert arbitrary document bytes into Markdown using Docling when available."""

    def __init__(
        self,
        *,
        backend: MarkdownBackend | None = None,
        router: DocumentFormatRouter | None = None,
        allow_fallback: bool = True,
        pdf_do_ocr: bool = True,
    ) -> None:
        """Initialize the converter.

        Args:
            backend: Optional injected backend. Tests and future import flows can provide
                a backend without importing Docling.
            router: Optional format router.
            allow_fallback: Whether to use lightweight local conversion if Docling is
                absent. Set False for fail-closed production smoke checks.
            pdf_do_ocr: Whether Docling should initialize OCR for PDF conversion.
                Defaults to True so scanned filings and research reports can be
                normalized through the same Markdown path.
        """
        self._backend = backend
        self._router = router or DocumentFormatRouter()
        self._allow_fallback = allow_fallback
        self._pdf_do_ocr = pdf_do_ocr

    def convert(
        self,
        *,
        content: bytes,
        document_id: str,
        source_url: str | None = None,
        content_type: str | None = None,
        filename: str | None = None,
    ) -> MarkdownConversionResult:
        """Convert source bytes into a canonical Markdown artifact."""
        document_format = self._router.detect(
            content_type=content_type,
            source_url=source_url,
            filename=filename,
        )
        request = MarkdownConversionRequest(
            document_id=document_id,
            content=content,
            document_format=document_format,
            source_url=source_url,
            content_type=content_type,
            filename=filename,
        )
        backend = self._backend or self._load_docling_backend(pdf_do_ocr=self._pdf_do_ocr)
        if backend is None:
            if not self._allow_fallback:
                raise DoclingUnavailableError(
                    "docling is not installed; install margin[docling] to enable "
                    "Docling Markdown conversion"
                )
            return _fallback_convert(request)
        return backend.convert(request)

    @staticmethod
    def _load_docling_backend(*, pdf_do_ocr: bool = True) -> MarkdownBackend | None:
        """Return the real Docling backend when the optional dependency is installed."""
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            return None

        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
            from docling.document_converter import PdfFormatOption
        except ImportError:
            return _DoclingBackend(DocumentConverter())

        pdf_options = PdfPipelineOptions()
        pdf_options.do_ocr = pdf_do_ocr
        if pdf_do_ocr:
            pdf_options.ocr_options = RapidOcrOptions(
                backend="onnxruntime",
                lang=["chinese"],
            )
        return _DoclingBackend(
            DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
                }
            )
        )


class _DoclingBackend:
    """Thin adapter around Docling's ``DocumentConverter`` API."""

    def __init__(self, converter: Any) -> None:
        self._converter = converter

    def convert(self, request: MarkdownConversionRequest) -> MarkdownConversionResult:
        """Convert bytes by writing them to a temporary file for Docling."""
        suffix = _suffix_for_format(request.document_format)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(request.content)
        try:
            converted = self._converter.convert(temp_path)
            document = converted.document
            markdown = str(document.export_to_markdown())
            json_document = _docling_json(document)
            tables = _docling_tables(document)
            return MarkdownConversionResult(
                document_id=request.document_id,
                source_url=request.source_url,
                content_type=request.content_type,
                document_format=request.document_format,
                markdown=markdown,
                json_document=json_document,
                tables=tables,
                parser_name="docling",
            )
        finally:
            temp_path.unlink(missing_ok=True)


def _fallback_convert(request: MarkdownConversionRequest) -> MarkdownConversionResult:
    """Best-effort local Markdown conversion when Docling is not installed."""
    text = request.content.decode("utf-8", errors="replace")
    warnings = ("docling_unavailable_fallback_used",)
    if request.document_format == DocumentFormat.JSON:
        try:
            payload = json.loads(text)
            markdown = "```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```"
            return MarkdownConversionResult(
                document_id=request.document_id,
                source_url=request.source_url,
                content_type=request.content_type,
                document_format=request.document_format,
                markdown=markdown,
                json_document=payload if isinstance(payload, dict) else {"rows": payload},
                parser_name="fallback",
                warnings=warnings,
            )
        except json.JSONDecodeError:
            pass
    if request.document_format == DocumentFormat.CSV:
        markdown = "```csv\n" + text + "\n```"
    elif request.document_format == DocumentFormat.HTML:
        markdown = _html_to_markdownish(text)
    elif request.document_format == DocumentFormat.PDF:
        markdown = _pdf_to_markdownish(request.content)
    else:
        markdown = text
    return MarkdownConversionResult(
        document_id=request.document_id,
        source_url=request.source_url,
        content_type=request.content_type,
        document_format=request.document_format,
        markdown=markdown.strip(),
        parser_name="fallback",
        warnings=warnings,
    )


def _html_to_markdownish(text: str) -> str:
    """Extract visible HTML text as Markdown paragraphs."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    paragraphs = [
        node.get_text(" ", strip=True)
        for node in soup.find_all(["h1", "h2", "h3", "p", "li"])
        if node.get_text(" ", strip=True)
    ]
    body = "\n\n".join(paragraphs) or soup.get_text("\n", strip=True)
    if title:
        return f"# {title}\n\n{body}".strip()
    return body.strip()


def _pdf_to_markdownish(content: bytes) -> str:
    """Extract PDF text with pypdf as a lightweight fallback."""
    import io

    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = page.extract_text() or ""
        pages.append(f"## Page {index}\n\n{page_text}".strip())
    return "\n\n".join(pages).strip()


def _docling_json(document: Any) -> dict[str, Any]:
    """Export Docling document JSON with API-version tolerance."""
    for attr in ("export_to_dict", "model_dump"):
        method = getattr(document, attr, None)
        if callable(method):
            value = method()
            return value if isinstance(value, dict) else {"document": value}
    return {}


def _docling_tables(document: Any) -> tuple[dict[str, Any], ...]:
    """Extract table data from Docling document when exposed by the API."""
    tables = getattr(document, "tables", None) or []
    extracted: list[dict[str, Any]] = []
    for index, table in enumerate(tables, start=1):
        if hasattr(table, "export_to_dataframe"):
            try:
                dataframe = table.export_to_dataframe(doc=document)
            except TypeError:
                dataframe = table.export_to_dataframe()
            extracted.append(
                {
                    "table_id": f"table_{index}",
                    "columns": [str(column) for column in dataframe.columns],
                    "rows": dataframe.astype(str).values.tolist(),
                }
            )
        elif hasattr(table, "model_dump"):
            extracted.append({"table_id": f"table_{index}", **table.model_dump()})
        else:
            extracted.append({"table_id": f"table_{index}", "repr": repr(table)})
    return tuple(extracted)


def _suffix_for_format(document_format: DocumentFormat) -> str:
    """Return a file suffix Docling can use for input detection."""
    if document_format == DocumentFormat.UNKNOWN:
        return ".bin"
    return f".{document_format.value}"
