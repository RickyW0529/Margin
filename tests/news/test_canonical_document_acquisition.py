"""Offline acquisition tests for the shared canonical normalization pipeline."""

from __future__ import annotations

from margin.documents.markdown import DoclingMarkdownConverter
from margin.documents.pipeline import DocumentNormalizationPipeline
from margin.news.acquirer import BaseConnector, FilingAcquirer, SnapshotStore, SourceRegistry
from margin.news.models import DocumentStatus, SourceDescriptor, SourceLevel
from margin.news.websearch import OriginalContentVerifier, SearchResult


class StaticConnector(BaseConnector):
    """Connector returning one fixed payload without network access."""

    def __init__(self, content: bytes, content_type: str) -> None:
        self.content = content
        self.content_type = content_type

    @property
    def source_name(self) -> str:
        return "static"

    def fetch(self, url: str, **kwargs):  # noqa: ANN003, ANN201
        del url, kwargs
        return self.content, self.content_type, 200


def _fallback_pipeline(monkeypatch) -> DocumentNormalizationPipeline:  # noqa: ANN001
    monkeypatch.setattr(
        DoclingMarkdownConverter,
        "_load_docling_backend",
        staticmethod(lambda **_kwargs: None),
    )
    return DocumentNormalizationPipeline(converter=DoclingMarkdownConverter())


def test_filing_acquirer_persists_complete_normalized_markdown(monkeypatch, tmp_path) -> None:
    body = "000001.SZ 需求增长。" * 5_000
    registry = SourceRegistry()
    registry.register(
        SourceDescriptor(name="sse", source_type="exchange", default_level=SourceLevel.L1),
        StaticConnector(
            f"<html><head><title>完整财报</title></head><body><p>{body}</p></body></html>".encode(),
            "text/html",
        ),
    )
    acquirer = FilingAcquirer(
        registry,
        SnapshotStore(base_dir=tmp_path),
        normalization_pipeline=_fallback_pipeline(monkeypatch),
    )

    event = acquirer.acquire("sse", "https://example.com/report.html")

    assert event.processing_status == DocumentStatus.READY
    assert event.title == "完整财报"
    assert event.content is not None
    assert len(event.content) > 50_000
    assert event.content.endswith(body)
    assert event.document_id == f"doc_{event.snapshot_id}"


def test_filing_binary_without_docling_is_explicitly_parse_failed(monkeypatch, tmp_path) -> None:
    registry = SourceRegistry()
    registry.register(
        SourceDescriptor(name="sse", source_type="exchange", default_level=SourceLevel.L1),
        StaticConnector(
            b"PK\x03\x04\x00\xffbinary",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    )
    acquirer = FilingAcquirer(
        registry,
        SnapshotStore(base_dir=tmp_path),
        normalization_pipeline=_fallback_pipeline(monkeypatch),
    )

    event = acquirer.acquire("sse", "https://example.com/report.docx")

    assert event.processing_status == DocumentStatus.PARSE_FAILED
    assert event.content is None
    assert "docx_parse_failed" in (event.processing_error or "")


def test_websearch_verifier_preserves_complete_normalized_markdown(monkeypatch, tmp_path) -> None:
    body = "供需缺口扩大。" * 8_000
    registry = SourceRegistry()
    registry.register(
        SourceDescriptor(name="websearch", source_type="websearch", default_level=SourceLevel.L4),
        StaticConnector(f"<html><body><p>{body}</p></body></html>".encode(), "text/html"),
    )
    verifier = OriginalContentVerifier(
        registry,
        SnapshotStore(base_dir=tmp_path),
        normalization_pipeline=_fallback_pipeline(monkeypatch),
    )

    verified = verifier.verify_and_snapshot(
        SearchResult(url="https://example.com/article.html", title="产业新闻", snippet="供需")
    )

    assert verified is not None
    assert verified.content == body
    assert len(verified.content) > 50_000
    assert verified.document_id == f"doc_{verified.snapshot.snapshot_id}"
