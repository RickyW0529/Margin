"""Docling-backed document-to-Markdown conversion.

The interface lives outside the news package so later research-report imports can
reuse the same router and converter.
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import zipfile
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from xml.etree import ElementTree

from pydantic import BaseModel, Field


class DocumentFormat(StrEnum):
    """Supported source document formats.."""

    PDF = "pdf"
    HTML = "html"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    CSV = "csv"
    JSON = "json"
    TEXT = "text"
    MARKDOWN = "markdown"
    UNKNOWN = "unknown"


class DoclingUnavailableError(RuntimeError):
    """Raised when Docling conversion is required but unavailable.."""


class MarkdownConversionRequest(BaseModel):
    """Input payload for document-to-Markdown conversion.."""

    document_id: str
    content: bytes
    document_format: DocumentFormat
    source_url: str | None = None
    content_type: str | None = None
    filename: str | None = None

    model_config = {"frozen": True}


class MarkdownConversionResult(BaseModel):
    """Canonical Markdown conversion artifact.."""

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
    """Backend protocol implemented by Docling and tests.."""

    def convert(self, request: MarkdownConversionRequest) -> MarkdownConversionResult:
        """Convert a request into canonical Markdown.

        Args:
            request: MarkdownConversionRequest: .

        Returns:
            MarkdownConversionResult: .
        """


class DocumentFormatRouter:
    """Detect document format from Content-Type and URL/file extension.."""

    CONTENT_TYPE_MAP: tuple[tuple[str, DocumentFormat], ...] = (
        ("pdf", DocumentFormat.PDF),
        ("html", DocumentFormat.HTML),
        ("wordprocessingml.document", DocumentFormat.DOCX),
        ("msword", DocumentFormat.DOCX),
        ("spreadsheetml.sheet", DocumentFormat.XLSX),
        ("excel", DocumentFormat.XLSX),
        ("presentationml.presentation", DocumentFormat.PPTX),
        ("powerpoint", DocumentFormat.PPTX),
        ("csv", DocumentFormat.CSV),
        ("json", DocumentFormat.JSON),
        ("text/markdown", DocumentFormat.MARKDOWN),
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
        ".pptx": DocumentFormat.PPTX,
        ".csv": DocumentFormat.CSV,
        ".json": DocumentFormat.JSON,
        ".txt": DocumentFormat.TEXT,
        ".md": DocumentFormat.MARKDOWN,
    }

    def detect(
        self,
        *,
        content_type: str | None,
        source_url: str | None,
        filename: str | None = None,
    ) -> DocumentFormat:
        """Detect a document format from MIME type, filename, or URL.

        Args:
            content_type: str | None: .
            source_url: str | None: .
            filename: str | None: .

        Returns:
            DocumentFormat: .
        """
        normalized_content_type = (content_type or "").lower()
        for marker, document_format in self.CONTENT_TYPE_MAP:
            if marker in normalized_content_type:
                return document_format

        path = filename or urlparse(source_url or "").path
        suffix = Path(path).suffix.lower()
        return self.EXTENSION_MAP.get(suffix, DocumentFormat.UNKNOWN)


class DoclingMarkdownConverter:
    """Convert arbitrary document bytes into Markdown using Docling when available.."""

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
            backend: MarkdownBackend | None: .
            router: DocumentFormatRouter | None: .
            allow_fallback: bool: .
            pdf_do_ocr: bool: .

        Returns:
            None: .
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
        """Convert source bytes into a canonical Markdown artifact.

        Args:
            content: bytes: .
            document_id: str: .
            source_url: str | None: .
            content_type: str | None: .
            filename: str | None: .

        Returns:
            MarkdownConversionResult: .
        """
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
        """Return the real Docling backend when the optional dependency is installed.

        Args:
            pdf_do_ocr: bool: .

        Returns:
            MarkdownBackend | None: .
        """
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
    """Thin adapter around Docling's ``DocumentConverter`` API.."""

    def __init__(self, converter: Any) -> None:
        """Process __init__.

        Args:
            converter: Any: .

        Returns:
            None: .
        """
        self._converter = converter

    def convert(self, request: MarkdownConversionRequest) -> MarkdownConversionResult:
        """Convert bytes by writing them to a temporary file for Docling.

        Args:
            request: MarkdownConversionRequest: .

        Returns:
            MarkdownConversionResult: .
        """
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
    """Best-effort local Markdown conversion when Docling is not installed.

    Args:
        request: MarkdownConversionRequest: .

    Returns:
        MarkdownConversionResult: .
    """
    warnings = ("docling_unavailable_fallback_used",)
    binary_parsers = {
        DocumentFormat.PDF: ("pypdf", _pdf_to_markdown),
        DocumentFormat.DOCX: ("stdlib_docx", _docx_to_markdown),
        DocumentFormat.XLSX: ("stdlib_xlsx", _xlsx_to_markdown),
        DocumentFormat.PPTX: ("stdlib_pptx", _pptx_to_markdown),
    }
    binary_parser = binary_parsers.get(request.document_format)
    if binary_parser is not None:
        parser_name, parser = binary_parser
        try:
            markdown, tables = parser(request.content)
        except Exception as exc:  # noqa: BLE001 - malformed/encrypted containers fail closed
            return _parse_failed_result(
                request,
                f"{request.document_format.value}_parse_failed:{type(exc).__name__}",
            )
        if not markdown.strip():
            return _parse_failed_result(
                request,
                f"{request.document_format.value}_parse_failed:empty_document",
            )
        return MarkdownConversionResult(
            document_id=request.document_id,
            source_url=request.source_url,
            content_type=request.content_type,
            document_format=request.document_format,
            markdown=markdown.strip(),
            tables=tables,
            parser_name=parser_name,
            warnings=warnings,
        )

    try:
        text = _decode_text(request.content)
    except UnicodeDecodeError:
        return _parse_failed_result(request, "text_decode_failed")

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
            return _parse_failed_result(request, "invalid_json")
    if request.document_format == DocumentFormat.CSV:
        markdown, tables = _csv_to_markdown(text)
    elif request.document_format == DocumentFormat.HTML:
        markdown = _html_to_markdownish(text)
    else:
        markdown = text
    return MarkdownConversionResult(
        document_id=request.document_id,
        source_url=request.source_url,
        content_type=request.content_type,
        document_format=request.document_format,
        markdown=markdown.strip(),
        tables=tables if request.document_format == DocumentFormat.CSV else (),
        parser_name="fallback",
        warnings=warnings,
    )


def _parse_failed_result(
    request: MarkdownConversionRequest,
    reason: str,
) -> MarkdownConversionResult:
    """Return a safe failed conversion without decoding binary bytes as text."""
    return MarkdownConversionResult(
        document_id=request.document_id,
        source_url=request.source_url,
        content_type=request.content_type,
        document_format=request.document_format,
        markdown="",
        parser_name="unavailable",
        warnings=(reason,),
        parse_status="parse_failed",
    )


def _decode_text(content: bytes) -> str:
    """Decode a textual payload without introducing replacement characters."""
    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = content.decode(encoding, errors="strict")
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        if "\x00" in text or any(
            ord(char) < 32 and char not in "\t\n\r" for char in text
        ):
            break
        return text
    if last_error is not None:
        raise last_error
    raise UnicodeDecodeError("utf-8", content, 0, len(content), "binary payload")


def _csv_to_markdown(text: str) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Convert CSV text into a Markdown table and a structured table artifact."""
    import csv
    import io

    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return "", ()
    width = max(len(row) for row in rows)
    header = [*(rows[0]), *([""] * (width - len(rows[0])))]
    body = [
        [*row, *([""] * (width - len(row)))]
        for row in rows[1:]
    ]

    markdown_rows = [
        "| " + " | ".join(_escape_gfm_cell(value) for value in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
        *(
            "| " + " | ".join(_escape_gfm_cell(value) for value in row) + " |"
            for row in body
        ),
    ]
    table = {
        "table_id": "table_1",
        "columns": header,
        "rows": body,
    }
    return "\n".join(markdown_rows), (table,)


def _html_to_markdownish(text: str) -> str:
    """Extract visible HTML text as Markdown paragraphs.

    Args:
        text: str: .

    Returns:
        str: .
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")
    for node in soup.find_all(["script", "style", "noscript", "template"]):
        node.decompose()
    root = soup.body or soup
    blocks = _html_blocks(root)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    first_heading = next((block for block in blocks if block.startswith("# ")), "")
    if title and first_heading.lstrip("# ").strip() != title:
        blocks.insert(0, f"# {title}")
    return "\n\n".join(block for block in blocks if block.strip()).strip()


def _pdf_to_markdown(content: bytes) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Extract every PDF page with the installed safe local pypdf parser."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        raise ValueError("encrypted PDF is not supported")
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if page_text:
            pages.append(f"## Page {index}\n\n{page_text}")
    return "\n\n".join(pages), ()


def _docx_to_markdown(content: bytes) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Extract DOCX paragraphs and tables from its Open XML package."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        document = ElementTree.fromstring(archive.read("word/document.xml"))
        blocks: list[str] = []
        tables: list[dict[str, Any]] = []
        body = next((node for node in document.iter() if _local_name(node.tag) == "body"), None)
        if body is None:
            raise ValueError("DOCX body is missing")
        for child in body:
            local_name = _local_name(child.tag)
            if local_name == "p":
                paragraph = _docx_paragraph(child)
                if paragraph:
                    blocks.append(paragraph)
            elif local_name == "tbl":
                rows = _docx_table_rows(child)
                markdown, table = _gfm_table(rows, table_id=f"table_{len(tables) + 1}")
                if markdown:
                    blocks.append(markdown)
                    tables.append(table)

        for prefix, label in (("word/header", "Header"), ("word/footer", "Footer")):
            for name in sorted(
                item
                for item in archive.namelist()
                if item.startswith(prefix) and item.endswith(".xml")
            ):
                root = ElementTree.fromstring(archive.read(name))
                text = "\n\n".join(
                    paragraph
                    for node in root.iter()
                    if _local_name(node.tag) == "p"
                    and (paragraph := _docx_paragraph(node))
                )
                if text:
                    blocks.append(f"## {label}\n\n{text}")
    return "\n\n".join(blocks), tuple(tables)


def _xlsx_to_markdown(content: bytes) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Extract XLSX worksheets into GFM tables using Open XML only."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = _xlsx_relationships(archive)
        blocks: list[str] = []
        tables: list[dict[str, Any]] = []
        for sheet_index, sheet in enumerate(
            (node for node in workbook.iter() if _local_name(node.tag) == "sheet"),
            start=1,
        ):
            sheet_name = _attribute_by_local_name(sheet, "name") or f"Sheet {sheet_index}"
            relationship_id = _attribute_by_local_name(sheet, "id")
            target = relationships.get(relationship_id or "")
            if target is None:
                raise ValueError(f"worksheet relationship missing: {sheet_name}")
            sheet_path = _xlsx_target_path(target)
            worksheet = ElementTree.fromstring(archive.read(sheet_path))
            rows = _xlsx_rows(worksheet, shared_strings)
            table_id = f"sheet_{sheet_index}"
            markdown, table = _gfm_table(rows, table_id=table_id)
            blocks.append(f"## Sheet: {sheet_name}" + (f"\n\n{markdown}" if markdown else ""))
            if markdown:
                table["sheet_name"] = sheet_name
                tables.append(table)
    return "\n\n".join(blocks), tuple(tables)


def _pptx_to_markdown(content: bytes) -> tuple[str, tuple[dict[str, Any], ...]]:
    """Extract PPTX slide text into page-addressable Markdown."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        slide_names = sorted(
            (
                name
                for name in archive.namelist()
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)
            ),
            key=_numeric_suffix,
        )
        if not slide_names:
            raise ValueError("PPTX slides are missing")
        blocks: list[str] = []
        for index, name in enumerate(slide_names, start=1):
            slide = ElementTree.fromstring(archive.read(name))
            lines = [
                (node.text or "").strip()
                for node in slide.iter()
                if _local_name(node.tag) == "t" and (node.text or "").strip()
            ]
            body = "\n\n".join(lines)
            blocks.append(f"## Slide {index}" + (f"\n\n{body}" if body else ""))
    return "\n\n".join(blocks), ()


def _html_blocks(root: Any) -> list[str]:
    """Render block-level HTML elements while retaining common Markdown semantics."""
    from bs4 import NavigableString, Tag

    blocks: list[str] = []
    for child in root.children:
        if isinstance(child, NavigableString):
            text = _collapse_whitespace(str(child))
            if text:
                blocks.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in {f"h{level}" for level in range(1, 7)}:
            text = _html_inline(child).strip()
            if text:
                blocks.append(f"{'#' * int(name[1])} {text}")
        elif name == "p":
            text = _html_inline(child).strip()
            if text:
                blocks.append(text)
        elif name in {"ul", "ol"}:
            items = []
            for index, item in enumerate(child.find_all("li", recursive=False), start=1):
                marker = f"{index}." if name == "ol" else "-"
                value = _html_inline(item, exclude_blocks={"ul", "ol"}).strip()
                if value:
                    items.append(f"{marker} {value}")
            if items:
                blocks.append("\n".join(items))
        elif name == "table":
            rows = [
                [_html_inline(cell).strip() for cell in row.find_all(["th", "td"], recursive=False)]
                for row in child.find_all("tr")
            ]
            markdown, _table = _gfm_table(rows, table_id="html_table")
            if markdown:
                blocks.append(markdown)
        elif name == "pre":
            value = child.get_text("", strip=False).strip("\n")
            if value:
                blocks.append(f"```\n{value}\n```")
        elif name == "blockquote":
            value = child.get_text(" ", strip=True)
            if value:
                blocks.append("\n".join(f"> {line}" for line in value.splitlines()))
        elif name == "hr":
            blocks.append("---")
        else:
            nested = _html_blocks(child)
            if nested:
                blocks.extend(nested)
            else:
                value = _html_inline(child).strip()
                if value:
                    blocks.append(value)
    return blocks


def _html_inline(node: Any, *, exclude_blocks: set[str] | None = None) -> str:
    """Render inline HTML nodes, retaining links and emphasis."""
    from bs4 import NavigableString, Tag

    excluded = exclude_blocks or set()
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(_collapse_whitespace(str(child)))
            continue
        if not isinstance(child, Tag) or child.name in excluded:
            continue
        value = _html_inline(child, exclude_blocks=excluded)
        name = child.name.lower()
        if name == "a" and value.strip():
            href = str(child.get("href") or "").strip()
            parts.append(f"[{value.strip()}]({href})" if href else value)
        elif name in {"strong", "b"} and value.strip():
            parts.append(f"**{value.strip()}**")
        elif name in {"em", "i"} and value.strip():
            parts.append(f"*{value.strip()}*")
        elif name == "code" and value.strip():
            parts.append(f"`{value.strip()}`")
        elif name == "br":
            parts.append("\n")
        else:
            parts.append(value)
    return "".join(parts)


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value)


def _docx_paragraph(paragraph: ElementTree.Element) -> str:
    text = "".join(
        node.text or "" for node in paragraph.iter() if _local_name(node.tag) == "t"
    ).strip()
    if not text:
        return ""
    style = next(
        (
            _attribute_by_local_name(node, "val") or ""
            for node in paragraph.iter()
            if _local_name(node.tag) == "pStyle"
        ),
        "",
    )
    heading = re.search(r"heading\s*([1-6])", style, flags=re.IGNORECASE)
    return f"{'#' * int(heading.group(1))} {text}" if heading else text


def _docx_table_rows(table: ElementTree.Element) -> list[list[str]]:
    return [
        [
            " ".join(
                value
                for paragraph in cell.iter()
                if _local_name(paragraph.tag) == "p"
                and (value := _docx_paragraph(paragraph))
            )
            for cell in row
            if _local_name(cell.tag) == "tc"
        ]
        for row in table
        if _local_name(row.tag) == "tr"
    ]


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter() if _local_name(node.tag) == "t")
        for item in root
        if _local_name(item.tag) == "si"
    ]


def _xlsx_relationships(archive: zipfile.ZipFile) -> dict[str, str]:
    root = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    return {
        _attribute_by_local_name(node, "Id") or "": _attribute_by_local_name(node, "Target")
        or ""
        for node in root
        if _local_name(node.tag) == "Relationship"
    }


def _xlsx_target_path(target: str) -> str:
    import posixpath

    normalized = target.lstrip("/")
    if normalized.startswith("xl/"):
        return normalized
    return posixpath.normpath(posixpath.join("xl", normalized))


def _xlsx_rows(root: ElementTree.Element, shared_strings: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in (node for node in root.iter() if _local_name(node.tag) == "row"):
        values: dict[int, str] = {}
        for fallback_index, cell in enumerate(
            node for node in row if _local_name(node.tag) == "c"
        ):
            reference = _attribute_by_local_name(cell, "r") or ""
            column_index = _xlsx_column_index(reference) if reference else fallback_index
            values[column_index] = _xlsx_cell_value(cell, shared_strings)
        if values:
            width = max(values) + 1
            rows.append([values.get(index, "") for index in range(width)])
    return rows


def _xlsx_cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = _attribute_by_local_name(cell, "t") or ""
    inline = "".join(
        node.text or "" for node in cell.iter() if _local_name(node.tag) == "t"
    )
    value = next(
        (node.text or "" for node in cell if _local_name(node.tag) == "v"),
        "",
    )
    formula = next(
        (node.text or "" for node in cell if _local_name(node.tag) == "f"),
        "",
    )
    if cell_type == "inlineStr":
        return inline
    if cell_type == "s" and value:
        return shared_strings[int(value)]
    if cell_type == "b":
        return "TRUE" if value == "1" else "FALSE"
    if value:
        return value
    return f"={formula}" if formula else inline


def _xlsx_column_index(reference: str) -> int:
    match = re.match(r"([A-Z]+)", reference.upper())
    if match is None:
        return 0
    result = 0
    for char in match.group(1):
        result = result * 26 + ord(char) - ord("A") + 1
    return result - 1


def _gfm_table(
    rows: list[list[str]],
    *,
    table_id: str,
) -> tuple[str, dict[str, Any]]:
    rows = [row for row in rows if any(str(value).strip() for value in row)]
    if not rows:
        return "", {}
    width = max(len(row) for row in rows)
    normalized = [[*map(str, row), *([""] * (width - len(row)))] for row in rows]
    header = [value or f"Column {index}" for index, value in enumerate(normalized[0], start=1)]
    body = normalized[1:]
    markdown = "\n".join(
        [
            "| " + " | ".join(_escape_gfm_cell(value) for value in header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
            *(
                "| " + " | ".join(_escape_gfm_cell(value) for value in row) + " |"
                for row in body
            ),
        ]
    )
    return markdown, {"table_id": table_id, "columns": header, "rows": body}


def _escape_gfm_cell(value: str) -> str:
    normalized = re.sub(r"\r\n?|\n", " / ", value)
    return normalized.replace("|", "\\|")


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _attribute_by_local_name(node: ElementTree.Element, name: str) -> str | None:
    return next(
        (value for key, value in node.attrib.items() if _local_name(key) == name),
        None,
    )


def _numeric_suffix(value: str) -> int:
    match = re.search(r"(\d+)(?=\.xml$)", value)
    return int(match.group(1)) if match else 0


def _docling_json(document: Any) -> dict[str, Any]:
    """Export Docling document JSON with API-version tolerance.

    Args:
        document: Any: .

    Returns:
        dict[str, Any]: .
    """
    for attr in ("export_to_dict", "model_dump"):
        method = getattr(document, attr, None)
        if callable(method):
            value = method()
            return value if isinstance(value, dict) else {"document": value}
    return {}


def _docling_tables(document: Any) -> tuple[dict[str, Any], ...]:
    """Extract table data from Docling document when exposed by the API.

    Args:
        document: Any: .

    Returns:
        tuple[dict[str, Any], ...]: .
    """
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
    """Return a file suffix Docling can use for input detection.

    Args:
        document_format: DocumentFormat: .

    Returns:
        str: .
    """
    if document_format == DocumentFormat.UNKNOWN:
        return ".bin"
    if document_format == DocumentFormat.MARKDOWN:
        return ".md"
    return f".{document_format.value}"
