"""Offline coverage for canonical multi-format document normalization."""

from __future__ import annotations

import io
import zipfile

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, StreamObject

from margin.documents.markdown import DoclingMarkdownConverter, DocumentFormat
from margin.documents.pipeline import DocumentNormalizationPipeline, DocumentPipelineRequest


def _without_docling(monkeypatch: pytest.MonkeyPatch) -> DoclingMarkdownConverter:
    monkeypatch.setattr(
        DoclingMarkdownConverter,
        "_load_docling_backend",
        staticmethod(lambda **_kwargs: None),
    )
    return DoclingMarkdownConverter()


@pytest.mark.parametrize(
    ("filename", "content_type", "content", "expected_format", "expected_text"),
    [
        ("report.html", "text/html", b"<h1>Title</h1><p>Body</p>", DocumentFormat.HTML, "Body"),
        ("table.csv", "text/csv", b"name,value\nroe,12.5\n", DocumentFormat.CSV, "| roe | 12.5 |"),
        ("data.json", "application/json", b'{"roe": 12.5}', DocumentFormat.JSON, '"roe": 12.5'),
        ("note.txt", "text/plain", b"plain text", DocumentFormat.TEXT, "plain text"),
        ("note.md", "text/markdown", b"# Heading\n\nBody", DocumentFormat.MARKDOWN, "# Heading"),
    ],
)
def test_textual_formats_normalize_to_markdown_without_docling(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    content_type: str,
    content: bytes,
    expected_format: DocumentFormat,
    expected_text: str,
) -> None:
    converter = _without_docling(monkeypatch)

    result = converter.convert(
        document_id="doc_format",
        content=content,
        content_type=content_type,
        filename=filename,
    )

    assert result.document_format == expected_format
    assert result.parse_status == "ready"
    assert expected_text in result.markdown
    assert "�" not in result.markdown


@pytest.mark.parametrize(
    ("filename", "content_type", "payload_factory", "expected_text"),
    [
        (
            "report.pdf",
            "application/pdf",
            lambda: _pdf_bytes(),
            "ROE improved to 12.5 percent",
        ),
        (
            "report.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            lambda: _docx_bytes(),
            "| 指标 | 数值 |",
        ),
        (
            "table.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            lambda: _xlsx_bytes(),
            "| ROE | 12.5 |",
        ),
        (
            "deck.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            lambda: _pptx_bytes(),
            "需求快速增长",
        ),
    ],
)
def test_valid_binary_formats_use_safe_local_markdown_parsers(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    content_type: str,
    payload_factory,
    expected_text: str,
) -> None:
    converter = _without_docling(monkeypatch)

    result = converter.convert(
        document_id="doc_binary",
        content=payload_factory(),
        content_type=content_type,
        filename=filename,
    )

    assert result.parse_status == "ready"
    assert expected_text in result.markdown
    assert "�" not in result.markdown


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("broken.pdf", "application/pdf"),
        (
            "broken.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            "broken.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (
            "broken.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ],
)
def test_damaged_binary_formats_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    content_type: str,
) -> None:
    result = _without_docling(monkeypatch).convert(
        document_id="doc_broken",
        content=b"\x00\xffnot-a-valid-container",
        content_type=content_type,
        filename=filename,
    )

    assert result.parse_status == "parse_failed"
    assert result.markdown == ""
    assert result.warnings[0].startswith(f"{filename.rsplit('.', 1)[-1]}_parse_failed")


def test_blank_pdf_without_extractable_text_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank or scan-only PDF is not complete evidence without Docling/OCR."""
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(buffer)

    result = _without_docling(monkeypatch).convert(
        document_id="doc_blank_pdf",
        content=buffer.getvalue(),
        content_type="application/pdf",
        filename="blank.pdf",
    )

    assert result.parse_status == "parse_failed"
    assert result.markdown == ""
    assert result.warnings == ("pdf_parse_failed:empty_document",)


def test_csv_multiline_cells_do_not_require_raw_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _without_docling(monkeypatch).convert(
        document_id="doc_csv_multiline",
        content=b'name,note\nroe,"first line\nsecond line"\n',
        content_type="text/csv",
        filename="multiline.csv",
    )

    assert "first line / second line" in result.markdown
    assert "<br>" not in result.markdown


def test_pipeline_preserves_complete_markdown_and_global_chunk_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = "业绩增长" * 20_000
    pipeline = DocumentNormalizationPipeline(
        converter=_without_docling(monkeypatch),
        max_chunk_chars=700,
    )

    result = pipeline.normalize(
        DocumentPipelineRequest(
            document_id="doc_full",
            content=f"<html><body><p>{body}</p></body></html>".encode(),
            content_type="text/html",
            filename="full.html",
        )
    )

    assert result.final_markdown == body
    assert len(result.final_markdown) > 50_000
    assert len(result.rag_chunks) > 1
    for chunk in result.rag_chunks:
        start, end = chunk.metadata["quote_span"]
        assert result.final_markdown[start:end] == chunk.content


def test_html_fallback_preserves_headings_lists_links_and_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = b"""
    <html><body>
      <h1>Industry Update</h1>
      <h3>Demand</h3>
      <ul><li>Orders <strong>surged</strong></li><li><a href="https://x.test">Source</a></li></ul>
      <table><tr><th>Metric</th><th>Value</th></tr><tr><td>ROE</td><td>12.5</td></tr></table>
    </body></html>
    """

    result = _without_docling(monkeypatch).convert(
        document_id="doc_html_semantics",
        content=html,
        content_type="text/html",
    )

    assert "# Industry Update" in result.markdown
    assert "### Demand" in result.markdown
    assert "- Orders **surged**" in result.markdown
    assert "[Source](https://x.test)" in result.markdown
    assert "| ROE | 12.5 |" in result.markdown


def _pdf_bytes() -> bytes:
    buffer = io.BytesIO()
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)  # noqa: SLF001 - build a minimal real PDF fixture
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
    )
    content_stream = StreamObject()
    content_stream.set_data(
        b"BT /F1 12 Tf 72 220 Td (ROE improved to 12.5 percent) Tj ET"
    )
    page[NameObject("/Contents")] = writer._add_object(  # noqa: SLF001
        content_stream
    )
    writer.write(buffer)
    return buffer.getvalue()


def _docx_bytes() -> bytes:
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>年度报告</w:t></w:r></w:p>
        <w:p><w:r><w:t>年度报告正文</w:t></w:r></w:p>
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>指标</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>数值</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>ROE</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>12.5</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>
      </w:body>
    </w:document>"""
    return _zip_bytes(
        {
            "[Content_Types].xml": "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>",
            "word/document.xml": document_xml,
        }
    )


def _xlsx_bytes() -> bytes:
    workbook = """<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>"""
    relationships = """<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
      <Relationship Id="rId1" Target="worksheets/sheet1.xml"
       Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>
    </Relationships>"""
    worksheet = """<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
      <sheetData>
        <row r="1">
          <c r="A1" t="inlineStr"><is><t>指标</t></is></c>
          <c r="B1" t="inlineStr"><is><t>数值</t></is></c>
        </row>
        <row r="2"><c r="A2" t="inlineStr"><is><t>ROE</t></is></c><c r="B2"><v>12.5</v></c></row>
      </sheetData></worksheet>"""
    return _zip_bytes(
        {
            "[Content_Types].xml": "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>",
            "xl/workbook.xml": workbook,
            "xl/_rels/workbook.xml.rels": relationships,
            "xl/worksheets/sheet1.xml": worksheet,
        }
    )


def _pptx_bytes() -> bytes:
    slide = """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>需求快速增长</a:t></a:r></a:p>
      </p:txBody></p:sp></p:spTree></p:cSld></p:sld>"""
    return _zip_bytes(
        {
            "[Content_Types].xml": "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"/>",
            "ppt/slides/slide1.xml": slide,
        }
    )


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value.encode())
    return buffer.getvalue()
