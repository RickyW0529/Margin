"""v0.2 structured chunk and multi-company link tests."""

from __future__ import annotations

from margin.vector.chunker import StructuredChunker
from margin.vector.models import SourceLocator, TrustLevel
from margin.vector.parsers.base import ParsedBlock


def test_chunk_id_is_stable_and_symbol_independent() -> None:
    """chunk id is stable and symbol independent."""
    chunker = StructuredChunker(parser_version="html-v0.2.0", max_chars=200)
    blocks = [
        ParsedBlock(
            text="平安银行收入增长。",
            block_type="paragraph",
            locator=SourceLocator(paragraph_index=0),
        )
    ]

    first = chunker.chunk(
        document_id="doc-1",
        content_hash="sha256:abc",
        blocks=blocks,
        security_ids=("000001.SZ",),
        trust_level=TrustLevel.UNTRUSTED_SOURCE_CONTENT,
    )
    second = chunker.chunk(
        document_id="doc-1",
        content_hash="sha256:abc",
        blocks=blocks,
        security_ids=("000001.SZ", "000002.SZ"),
        trust_level=TrustLevel.UNTRUSTED_SOURCE_CONTENT,
    )

    assert first.chunks[0].chunk_id == second.chunks[0].chunk_id
    assert {link.security_id for link in second.links} == {"000001.SZ", "000002.SZ"}


def test_chunk_does_not_cross_table_boundary() -> None:
    """chunk does not cross table boundary."""
    chunker = StructuredChunker(parser_version="csv-v0.2.0", max_chars=1_000)
    blocks = [
        ParsedBlock(
            text="收入 100",
            block_type="table_row",
            locator=SourceLocator(table_id="t1"),
        ),
        ParsedBlock(
            text="正文段落",
            block_type="paragraph",
            locator=SourceLocator(paragraph_index=1),
        ),
    ]

    result = chunker.chunk(
        document_id="doc-1",
        content_hash="sha256:abc",
        blocks=blocks,
        security_ids=("000001.SZ",),
        trust_level=TrustLevel.TRUSTED_OFFICIAL_CONTENT,
    )

    assert len(result.chunks) == 2
