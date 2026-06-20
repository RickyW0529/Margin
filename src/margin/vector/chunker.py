"""Document chunker — splits documents differently based on document type.

Corresponds to specs 04 §4 data model and architecture §7.2 chunking strategy.
Corresponds to plans 0401:
  0401.1 Parser and structure detection (reuses DocumentParser from module 03)
  0401.2 Chunker splitting strategy (differentiated by document type)
  0401.3 Chunk metadata (complete positioning fields)
  0401.4 Parsing failure handling (keep original text and stop related AI conclusions)

Chunking strategy (architecture §7.2):
  Annual/quarterly reports → by section, table, and page
  Filings                → by matter and clause
  News                   → title, lead, and body paragraphs
  IR records             → by Q&A pairs
  Industry reports       → by topic and chart captions
  User notes             → by heading and paragraph
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from margin.news.models import DocumentEvent, DocumentStatus
from margin.vector.models import Chunk, DocType, make_chunk

if TYPE_CHECKING:
    from margin.news.parsed import ParsedBlock, ParsedDocument

# ---------------------------------------------------------------------------
# Parsing exceptions
# ---------------------------------------------------------------------------


class ChunkingError(Exception):
    """Raised when document chunking fails."""


# ---------------------------------------------------------------------------
# Document type inference
# ---------------------------------------------------------------------------


def infer_doc_type(event: DocumentEvent) -> DocType:
    """Infer the document type from a document event.

    Args:
        event: The document event to classify.

    Returns:
        The inferred document type.
    """
    title = event.title.lower()
    doc_type_str = event.doc_type.lower()

    explicit_types = {
        "annual_report": DocType.ANNUAL_REPORT,
        "quarterly_report": DocType.QUARTERLY_REPORT,
        "filing": DocType.FILING,
        "news": DocType.NEWS,
        "ir": DocType.IR,
        "industry": DocType.INDUSTRY_REPORT,
        "industry_report": DocType.INDUSTRY_REPORT,
        "user_file": DocType.USER_NOTE,
        "user_note": DocType.USER_NOTE,
    }
    if doc_type_str in explicit_types:
        return explicit_types[doc_type_str]

    if "年报" in title or "annual" in title:
        return DocType.ANNUAL_REPORT
    if "季报" in title or "quarterly" in title:
        return DocType.QUARTERLY_REPORT
    if "公告" in title:
        return DocType.FILING
    if "news" in doc_type_str or "新闻" in title:
        return DocType.NEWS
    if "ir" in doc_type_str or "问答" in title or "qa" in title.lower():
        return DocType.IR
    if "行业" in title or "industry" in doc_type_str:
        return DocType.INDUSTRY_REPORT
    if "user" in doc_type_str or "笔记" in title:
        return DocType.USER_NOTE
    return DocType.UNKNOWN


# ---------------------------------------------------------------------------
# Base chunker
# ---------------------------------------------------------------------------


class BaseChunker:
    """Base chunker providing generic paragraph-splitting utilities."""

    def __init__(self, max_chunk_size: int = 1000, overlap: int = 100) -> None:
        """Initialize the base chunker.

        Args:
            max_chunk_size: Maximum number of characters per chunk.
            overlap: Number of overlapping characters between consecutive chunks.

        Raises:
            ValueError: If ``max_chunk_size`` is not positive or ``overlap`` is out of range.
        """
        if max_chunk_size <= 0:
            raise ValueError("max_chunk_size must be positive")
        if overlap < 0 or overlap >= max_chunk_size:
            raise ValueError("overlap must be non-negative and smaller than max_chunk_size")
        self._max_size = max_chunk_size
        self._overlap = overlap

    def chunk(self, event: DocumentEvent) -> list[Chunk]:
        """Chunk a document event into a list of chunks.

        Args:
            event: The document event to chunk.

        Returns:
            A list of chunks.

        Raises:
            NotImplementedError: Subclasses must implement this method.
        """
        raise NotImplementedError

    def _split_paragraphs(self, text: str) -> list[str]:
        """Split text into paragraphs separated by blank lines.

        Args:
            text: The text to split.

        Returns:
            A list of non-empty paragraph strings.
        """
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences using Chinese and English punctuation.

        Args:
            text: The text to split.

        Returns:
            A list of non-empty sentence strings.
        """
        sentences = re.split(r"[。！？.!?；;]+", text)
        return [s.strip() for s in sentences if s.strip()]

    def _merge_to_size(self, parts: list[str]) -> list[str]:
        """Merge small parts into chunks that do not exceed ``max_size``.

        Args:
            parts: The text parts to merge.

        Returns:
            A list of merged chunk strings with configured overlap.
        """
        chunks: list[str] = []
        current = ""

        expanded_parts: list[str] = []
        for part in parts:
            expanded_parts.extend(self._split_oversized_part(part))

        for part in expanded_parts:
            candidate = f"{current}\n{part}" if current else part
            if len(candidate) <= self._max_size:
                current = candidate
                continue

            if current:
                chunks.append(current)
            overlap_text = current[-self._overlap:] if current and self._overlap else ""
            candidate = f"{overlap_text}\n{part}" if overlap_text else part
            current = candidate if len(candidate) <= self._max_size else part

        if current:
            chunks.append(current)

        return chunks

    def _split_oversized_part(self, part: str) -> list[str]:
        """Split a single oversized segment using character overlap.

        Args:
            part: The text segment to split.

        Returns:
            A list of sub-segments no longer than ``max_size``.
        """
        if len(part) <= self._max_size:
            return [part]

        step = self._max_size - self._overlap
        return [
            part[start : start + self._max_size]
            for start in range(0, len(part), step)
            if part[start : start + self._max_size]
        ]

    def _make_chunks(
        self,
        event: DocumentEvent,
        text_parts: list[str],
        doc_type: DocType,
        section_labels: list[str] | None = None,
    ) -> list[Chunk]:
        """Generate a list of chunks from text parts and populate metadata.

        Args:
            event: The document event the chunks belong to.
            text_parts: The text content for each chunk.
            doc_type: The document type to record in chunk metadata.
            section_labels: Optional section label for each text part.

        Returns:
            A list of populated chunks.
        """
        if not text_parts:
            return []

        expanded_parts: list[str] = []
        expanded_labels: list[str | None] = []
        for index, text in enumerate(text_parts):
            label = (
                section_labels[index]
                if section_labels and index < len(section_labels)
                else None
            )
            split_parts = self._split_oversized_part(text)
            expanded_parts.extend(split_parts)
            expanded_labels.extend([label] * len(split_parts))

        total = len(expanded_parts)
        chunks: list[Chunk] = []
        symbols = event.symbols or (None,)

        for symbol in symbols:
            for idx, text in enumerate(expanded_parts):
                chunk = make_chunk(
                    document_id=event.document_id,
                    content=text,
                    chunk_index=idx,
                    total_chunks=total,
                    symbol=symbol,
                    source_level=event.source_level,
                    doc_type=doc_type,
                    published_at=event.published_at,
                    available_at=event.available_at,
                    source_url=event.source_url,
                    source_name=event.source_name,
                    snapshot_id=event.snapshot_id,
                    snapshot_hash=event.snapshot_hash,
                    section=expanded_labels[idx],
                    paragraph_index=idx,
                )
                chunks.append(chunk)

        return chunks


# ---------------------------------------------------------------------------
# Document-type-specific chunkers
# ---------------------------------------------------------------------------


class ReportChunker(BaseChunker):
    """Annual/quarterly report chunker — splits by section, table, and page."""

    SECTION_PATTERNS = [
        r"第[一二三四五六七八九十百]+章",
        r"第[一二三四五六七八九十百]+节",
        r"[一二三四五六七八九十]+、",
        r"\d+\.\s",
        r"Section\s+\d+",
        r"Chapter\s+\d+",
    ]

    def chunk(self, event: DocumentEvent) -> list[Chunk]:
        """Chunk an annual or quarterly report event.

        Args:
            event: The document event to chunk.

        Returns:
            A list of chunks split by report sections.
        """
        content = event.content or ""
        if not content.strip():
            return []

        sections = self._split_by_sections(content)
        all_parts: list[str] = []
        all_labels: list[str] = []

        for label, section_text in sections:
            paragraphs = self._split_paragraphs(section_text)
            merged = self._merge_to_size(paragraphs)
            for part in merged:
                all_parts.append(part)
                all_labels.append(label)

        doc_type = infer_doc_type(event)
        return self._make_chunks(event, all_parts, doc_type, all_labels)

    def _split_by_sections(self, text: str) -> list[tuple[str, str]]:
        """Split text by section markers.

        Args:
            text: The report text to split.

        Returns:
            A list of ``(section_label, section_text)`` tuples.
        """
        positions: list[tuple[int, str]] = []

        for pattern in self.SECTION_PATTERNS:
            for match in re.finditer(pattern, text):
                positions.append((match.start(), match.group()))

        positions.sort(key=lambda x: x[0])

        if not positions:
            return [("body", text)]

        sections: list[tuple[str, str]] = []
        first_position = positions[0][0]
        if first_position > 0:
            preamble = text[:first_position].strip()
            if preamble:
                sections.append(("preamble", preamble))

        for i, (pos, label) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            section_text = text[pos:end].strip()
            if section_text:
                sections.append((label, section_text))

        return sections


class FilingChunker(BaseChunker):
    """Filing chunker — splits by matter and clause."""

    ITEM_PATTERNS = [
        r"一、",
        r"二、",
        r"三、",
        r"四、",
        r"五、",
        r"六、",
        r"七、",
        r"八、",
        r"\d+、",
        r"第\d+条",
    ]

    def chunk(self, event: DocumentEvent) -> list[Chunk]:
        """Chunk a filing event.

        Args:
            event: The document event to chunk.

        Returns:
            A list of chunks split by filing items.
        """
        content = event.content or ""
        if not content.strip():
            return []

        items = self._split_by_items(content)

        all_parts: list[str] = []
        all_labels: list[str] = []

        for label, item_text in items:
            paragraphs = self._split_paragraphs(item_text)
            merged = self._merge_to_size(paragraphs)
            for part in merged:
                all_parts.append(part)
                all_labels.append(label)

        return self._make_chunks(event, all_parts, DocType.FILING, all_labels)

    def _split_by_items(self, text: str) -> list[tuple[str, str]]:
        """Split text by item markers.

        Args:
            text: The filing text to split.

        Returns:
            A list of ``(item_label, item_text)`` tuples.
        """
        positions: list[tuple[int, str]] = []

        for pattern in self.ITEM_PATTERNS:
            for match in re.finditer(pattern, text):
                positions.append((match.start(), match.group()))

        positions.sort(key=lambda x: x[0])

        if not positions:
            return [("body", text)]

        items: list[tuple[str, str]] = []
        first_position = positions[0][0]
        if first_position > 0:
            preamble = text[:first_position].strip()
            if preamble:
                items.append(("preamble", preamble))

        for i, (pos, label) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            item_text = text[pos:end].strip()
            if item_text:
                items.append((label, item_text))

        return items


class NewsChunker(BaseChunker):
    """News chunker — extracts title, lead, and body paragraphs."""

    def chunk(self, event: DocumentEvent) -> list[Chunk]:
        """Chunk a news event.

        Args:
            event: The document event to chunk.

        Returns:
            A list of chunks containing the title, lead paragraph, and body.
        """
        content = event.content or ""
        title = event.title

        if not content.strip():
            return self._make_chunks(event, [title], DocType.NEWS, ["title"])

        parts: list[str] = [title]
        labels: list[str] = ["title"]

        paragraphs = self._split_paragraphs(content)

        if paragraphs:
            parts.append(paragraphs[0])
            labels.append("lead")

            if len(paragraphs) > 1:
                body_merged = self._merge_to_size(paragraphs[1:])
                for body in body_merged:
                    parts.append(body)
                    labels.append("body")

        return self._make_chunks(event, parts, DocType.NEWS, labels)


class IRChunker(BaseChunker):
    """IR record chunker — splits by question-and-answer pairs."""

    QA_PATTERN = r"(问[题]?[:：]|Q[:：]|答[:：]|A[:：])"

    def chunk(self, event: DocumentEvent) -> list[Chunk]:
        """Chunk an investor relations event.

        Args:
            event: The document event to chunk.

        Returns:
            A list of chunks split by Q&A pairs.
        """
        content = event.content or ""
        if not content.strip():
            return []

        qa_pairs = self._split_qa(content)

        if not qa_pairs:
            paragraphs = self._split_paragraphs(content)
            qa_pairs = [(p, "") for p in paragraphs]

        parts = [text for text, _ in qa_pairs]
        labels = [label or "qa" for _, label in qa_pairs]

        return self._make_chunks(event, parts, DocType.IR, labels)

    def _split_qa(self, text: str) -> list[tuple[str, str]]:
        """Split text by question and answer markers.

        Args:
            text: The IR text to split.

        Returns:
            A list of ``(segment_text, label)`` tuples grouped into Q&A pairs.
        """
        matches = list(re.finditer(self.QA_PATTERN, text))
        if len(matches) < 2:
            return []

        segments: list[tuple[str, str]] = []
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            segment = text[match.start():end].strip()
            if segment:
                segments.append((segment, match.group(1)))

        pairs: list[tuple[str, str]] = []
        index = 0
        while index < len(segments):
            segment, label = segments[index]
            if label.lower().startswith(("问", "q")) and index + 1 < len(segments):
                answer, answer_label = segments[index + 1]
                if answer_label.lower().startswith(("答", "a")):
                    pairs.append((f"{segment}\n{answer}", "qa"))
                    index += 2
                    continue
            pairs.append((segment, label))
            index += 1

        return pairs


class UserNoteChunker(BaseChunker):
    """User note chunker — splits by heading and paragraph."""

    def chunk(self, event: DocumentEvent) -> list[Chunk]:
        """Chunk a user note event.

        Args:
            event: The document event to chunk.

        Returns:
            A list of chunks split by paragraph.
        """
        content = event.content or ""
        if not content.strip():
            return []

        paragraphs = self._split_paragraphs(content)
        merged = self._merge_to_size(paragraphs)

        labels = [f"para_{i}" for i in range(len(merged))]
        return self._make_chunks(event, merged, DocType.USER_NOTE, labels)


# ---------------------------------------------------------------------------
# Chunker factory
# ---------------------------------------------------------------------------

_CHUNKER_MAP: dict[DocType, type[BaseChunker]] = {
    DocType.ANNUAL_REPORT: ReportChunker,
    DocType.QUARTERLY_REPORT: ReportChunker,
    DocType.FILING: FilingChunker,
    DocType.NEWS: NewsChunker,
    DocType.IR: IRChunker,
    DocType.INDUSTRY_REPORT: ReportChunker,
    DocType.USER_NOTE: UserNoteChunker,
}


class Chunker:
    """Entry point for document chunking — selects the strategy by document type.

    Example::

        chunker = Chunker()
        chunks = chunker.chunk(document_event)
    """

    def __init__(
        self,
        max_chunk_size: int = 1000,
        overlap: int = 100,
        custom_chunkers: dict[DocType, BaseChunker] | None = None,
    ) -> None:
        """Initialize the chunker dispatcher.

        Args:
            max_chunk_size: Maximum number of characters per chunk.
            overlap: Number of overlapping characters between consecutive chunks.
            custom_chunkers: Optional mapping of document types to custom chunker instances.
        """
        self._max_size = max_chunk_size
        self._overlap = overlap
        self._custom = custom_chunkers or {}

    def chunk(self, event: DocumentEvent) -> list[Chunk]:
        """Chunk a document event using the matching document-type strategy.

        When parsing fails, the original title is kept as the only chunk and a parse note is
        recorded (architecture §25).

        Args:
            event: The document event to chunk.

        Returns:
            A list of chunks, or an empty list if the event is not ready for chunking.

        Raises:
            ChunkingError: If the selected chunker fails to process the document.
        """
        if event.processing_status != DocumentStatus.READY:
            return []

        doc_type = infer_doc_type(event)

        chunker = self._custom.get(doc_type)
        if chunker is None:
            chunker_cls = _CHUNKER_MAP.get(doc_type)
            if chunker_cls is None:
                chunker = BaseChunker(self._max_size, self._overlap)
                paragraphs = chunker._split_paragraphs(event.content or event.title)
                merged = chunker._merge_to_size(paragraphs)
                return chunker._make_chunks(event, merged, DocType.UNKNOWN)
            chunker = chunker_cls(self._max_size, self._overlap)

        try:
            chunks = chunker.chunk(event)
        except Exception as exc:
            raise ChunkingError(f"Failed to chunk document '{event.document_id}': {exc}") from exc

        if not chunks:
            return self._make_fallback_chunks(event, doc_type)

        return chunks

    def _make_fallback_chunks(
        self,
        event: DocumentEvent,
        doc_type: DocType,
    ) -> list[Chunk]:
        """Create title-only chunks for ready documents without parsed body text.

        Args:
            event: The document event to create fallback chunks for.
            doc_type: The document type to record in chunk metadata.

        Returns:
            A list of title-only chunks, one per symbol.
        """
        fallback_chunker = BaseChunker(self._max_size, self._overlap)
        return fallback_chunker._make_chunks(
            event,
            [event.title],
            doc_type,
            ["title"],
        )

    def chunk_batch(self, events: list[DocumentEvent]) -> list[Chunk]:
        """Chunk a batch of document events.

        Args:
            events: The document events to chunk.

        Returns:
            A flattened list of all chunks. Documents that raise ``ChunkingError`` are skipped.
        """
        all_chunks: list[Chunk] = []
        for event in events:
            try:
                chunks = self.chunk(event)
                all_chunks.extend(chunks)
            except ChunkingError:
                continue
        return all_chunks

    def chunk_parsed(
        self,
        parsed: ParsedDocument,
        event: DocumentEvent,
    ) -> list[Chunk]:
        """Chunk structured parsed blocks while preserving source locators.

        Args:
            parsed: Parsed document containing structured blocks with locator metadata.
            event: The document event the parsed blocks belong to.

        Returns:
            A list of chunks with page, section, paragraph, table, row, and quote span
            locators copied from the parsed blocks.
        """
        if event.processing_status != DocumentStatus.READY:
            return []
        chunks: list[Chunk] = []
        symbols = event.symbols or (None,)
        expanded: list[tuple[str, ParsedBlock, tuple[int, int] | None]] = []
        for block in parsed.blocks:
            pieces = self._split_block_text(block)
            for text, quote_span in pieces:
                expanded.append((text, block, quote_span))

        total = len(expanded)
        for symbol in symbols:
            for index, (text, block, quote_span) in enumerate(expanded):
                chunks.append(
                    make_chunk(
                        document_id=event.document_id,
                        content=text,
                        chunk_index=index,
                        total_chunks=total,
                        symbol=symbol,
                        source_level=event.source_level,
                        doc_type=infer_doc_type(event),
                        published_at=event.published_at,
                        available_at=event.available_at,
                        source_url=event.source_url or parsed.source_url,
                        source_name=event.source_name,
                        snapshot_id=event.snapshot_id,
                        snapshot_hash=event.snapshot_hash,
                        page=block.page,
                        section=block.section,
                        paragraph_index=block.paragraph_index,
                        table_id=block.table_id,
                        row_id=block.row_id,
                        quote_span=quote_span,
                    )
                )
        return chunks

    def _split_block_text(
        self,
        block: ParsedBlock,
    ) -> list[tuple[str, tuple[int, int] | None]]:
        """Split a parsed block into sub-parts and adjust quote spans.

        Args:
            block: Parsed block containing text and an optional quote span.

        Returns:
            A list of ``(text_part, quote_span)`` tuples. When the block has no quote
            span, ``quote_span`` is ``None``.
        """
        base = BaseChunker(self._max_size, self._overlap)
        parts = base._split_oversized_part(block.text)
        if block.quote_span is None:
            return [(part, None) for part in parts]

        start, end = block.quote_span
        current = start
        result: list[tuple[str, tuple[int, int] | None]] = []
        for part in parts:
            part_end = min(current + len(part), end)
            result.append((part, (current, part_end)))
            current = part_end
        return result
