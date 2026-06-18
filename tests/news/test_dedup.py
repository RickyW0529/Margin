"""Deduplication and quality grading tests — 0303 acceptance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from margin.news.dedup import (
    Deduplicator,
    NewsProcessor,
    QualityScorer,
    compute_simhash,
    hamming_distance,
    simhash_similarity,
)
from margin.news.models import SourceLevel, make_document_event


def _make_event(
    url="https://example.com/1",
    title="测试公告",
    content=None,
    source_level=SourceLevel.L1,
    published_at=None,
    content_hash=None,
):
    """Build a document event for tests.

    Args:
        url: Source URL for the event.
        title: Title used for the event and fallback content.
        content: Body text; defaults to a string derived from the title.
        source_level: Authority/source level for the event.
        published_at: Publication timestamp; defaults to 2026-06-17.
        content_hash: Optional explicit content hash.

    Returns:
        A populated document event.
    """
    if content is None:
        content = f"{title}的正文内容"
    if content_hash is None:
        from margin.news.models import compute_content_hash
        content_hash = compute_content_hash(f"{url}:{title}:{content}")
    return make_document_event(
        source_url=url,
        source_name="test",
        source_level=source_level,
        title=title,
        content=content,
        content_hash=content_hash,
        published_at=published_at or datetime(2026, 6, 17),
    )


class TestSimHash:
    """Tests for SimHash fingerprint utilities."""

    def test_identical_text_same_hash(self):
        """Identical text must produce identical SimHash values."""
        assert compute_simhash("公司经营现金流改善") == compute_simhash("公司经营现金流改善")

    def test_different_text_different_hash(self):
        """Different text must produce different SimHash values."""
        assert compute_simhash("公司经营现金流改善") != compute_simhash("公司净利润下降")

    def test_hamming_distance_zero(self):
        """Hamming distance of a hash with itself must be zero."""
        h = compute_simhash("test")
        assert hamming_distance(h, h) == 0

    def test_hamming_distance_positive(self):
        """Different hashes must have a positive Hamming distance."""
        h1 = compute_simhash("hello world")
        h2 = compute_simhash("goodbye world")
        assert hamming_distance(h1, h2) > 0

    def test_similarity_identical(self):
        """Similarity of a hash with itself must be 1.0."""
        h = compute_simhash("test")
        assert simhash_similarity(h, h) == 1.0

    def test_similarity_different(self):
        """Different hashes must have similarity below 1.0."""
        h1 = compute_simhash("完全不同的文本A")
        h2 = compute_simhash("完全不同的文本B")
        assert simhash_similarity(h1, h2) < 1.0

    def test_empty_text(self):
        """Empty text must produce a SimHash value of zero."""
        assert compute_simhash("") == 0


class TestDeduplicator:
    """Tests for event deduplication logic."""

    def test_unique_events_pass(self):
        """Unique events must all be retained."""
        events = [
            _make_event(url="https://a.com", title="A"),
            _make_event(url="https://b.com", title="B"),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(events)
        assert len(result.unique_events) == 2
        assert result.duplicate_count == 0

    def test_duplicate_url(self):
        """Events sharing a URL must be flagged as duplicates."""
        events = [
            _make_event(url="https://a.com", title="A"),
            _make_event(url="https://a.com", title="A copy"),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(events)
        assert len(result.unique_events) == 1
        assert result.duplicate_count == 1
        assert result.duplicates[0]["reason"] == "duplicate_url"

    def test_duplicate_content_hash(self):
        """Events sharing a content hash must be deduplicated."""
        events = [
            _make_event(url="https://a.com", title="A", content_hash="sha256:same"),
            _make_event(url="https://b.com", title="B", content_hash="sha256:same"),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(events)
        assert len(result.unique_events) == 1
        assert result.duplicate_count == 1

    def test_duplicate_title_date(self):
        """Events with matching title and date must be deduplicated."""
        date = datetime(2026, 6, 17)
        events = [
            _make_event(url="https://a.com", title="相同标题", published_at=date),
            _make_event(url="https://b.com", title="相同标题", published_at=date),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(events)
        assert len(result.unique_events) == 1
        assert result.duplicate_count == 1

    def test_simhash_duplicate(self):
        """Near-duplicate content must be detected via SimHash."""
        content = "公司经营现金流显著改善，净利润同比增长30%"
        events = [
            _make_event(url="https://a.com", title="A", content=content),
            _make_event(url="https://b.com", title="B", content=content + "。"),
        ]
        dedup = Deduplicator(simhash_threshold=5)
        result = dedup.deduplicate(events)
        assert result.duplicate_count >= 1

    def test_repost_keeps_earlier_lower_level(self):
        """Reposts must keep the earlier, more authoritative source."""
        early = _make_event(
            url="https://exchange.com",
            title="公告",
            source_level=SourceLevel.L1,
            published_at=datetime(2026, 6, 17),
        )
        late = _make_event(
            url="https://media.com",
            title="公告",
            source_level=SourceLevel.L4,
            published_at=datetime(2026, 6, 18),
            content_hash=early.content_hash,
        )
        dedup = Deduplicator()
        result = dedup.deduplicate([early, late])
        assert len(result.unique_events) == 1
        assert result.unique_events[0].source_url == "https://exchange.com"

    def test_more_authoritative_source_replaces_earlier_rumor(self):
        """A later L1 filing must be canonical over an earlier L5 repost."""
        shared_hash = "sha256:same"
        rumor = _make_event(
            url="https://social.example/rumor",
            title="市场传闻",
            source_level=SourceLevel.L5,
            published_at=datetime(2026, 6, 17),
            content_hash=shared_hash,
        )
        filing = _make_event(
            url="https://exchange.example/filing",
            title="交易所公告",
            source_level=SourceLevel.L1,
            published_at=datetime(2026, 6, 18),
            content_hash=shared_hash,
        )

        result = Deduplicator().deduplicate([rumor, filing])

        assert result.unique_events == [filing]
        assert result.duplicates[0]["duplicate_of"] == filing.event_id

    def test_deduplication_does_not_mutate_input_events(self):
        """Deduplication must preserve the immutable input event values."""
        original = _make_event(url="https://a.com", title="A")
        duplicate = _make_event(url="https://a.com", title="B")

        Deduplicator().deduplicate([original, duplicate])

        assert original.is_original is True
        assert duplicate.is_original is True
        assert duplicate.duplicate_of is None

    def test_empty_input(self):
        """Empty input must produce an empty deduplication result."""
        dedup = Deduplicator()
        result = dedup.deduplicate([])
        assert len(result.unique_events) == 0
        assert result.duplicate_count == 0

    def test_total_count(self):
        """Total event count must include both unique and duplicate events."""
        events = [
            _make_event(url="https://a.com", title="A"),
            _make_event(url="https://a.com", title="A dup"),
        ]
        dedup = Deduplicator()
        result = dedup.deduplicate(events)
        assert result.total_count == 2


class TestQualityScorer:
    """Tests for quality scoring of document events."""

    def test_l1_highest_authority(self):
        """L1 sources must receive the highest authority score."""
        event = _make_event(source_level=SourceLevel.L1, content="x" * 200)
        scorer = QualityScorer()
        score = scorer.score(event)
        assert score.authority == 1.0
        assert score.total_score > 0.5

    def test_l5_lowest_authority(self):
        """L5 sources must receive the lowest authority score."""
        event = _make_event(source_level=SourceLevel.L5, content="x" * 200)
        scorer = QualityScorer()
        score = scorer.score(event)
        assert score.authority == 0.2

    def test_completeness_full_content(self):
        """Long content must receive full completeness score."""
        event = _make_event(content="x" * 200)
        scorer = QualityScorer()
        score = scorer.score(event)
        assert score.completeness == 1.0

    def test_completeness_partial_content(self):
        """Partial content must receive a reduced completeness score."""
        event = _make_event(content="x" * 50)
        scorer = QualityScorer()
        score = scorer.score(event)
        assert score.completeness == 0.5

    def test_completeness_no_content(self):
        """Empty content must receive the minimum completeness score."""
        event = make_document_event(
            source_url="u", source_name="s",
            source_level=SourceLevel.L1, title="t", content="",
        )
        scorer = QualityScorer()
        score = scorer.score(event)
        assert score.completeness == 0.1

    def test_timeliness_recent(self):
        """Recent events must have high timeliness score."""
        event = _make_event(published_at=datetime.now())
        scorer = QualityScorer()
        score = scorer.score(event)
        assert score.timeliness > 0.9

    def test_timeliness_old(self):
        """Events older than the decay window must have zero timeliness."""
        event = _make_event(published_at=datetime.now() - timedelta(days=60))
        scorer = QualityScorer(timeliness_decay_days=30)
        score = scorer.score(event)
        assert score.timeliness == 0.0

    def test_timeliness_supports_timezone_aware_publication_time(self):
        """Quality scoring must accept the timezone-aware timestamps used by evidence."""
        event = _make_event(published_at=datetime.now(UTC))

        score = QualityScorer().score(event)

        assert score.timeliness > 0.9

    def test_score_frozen(self):
        """Score objects must be immutable after creation."""
        event = _make_event()
        scorer = QualityScorer()
        score = scorer.score(event)
        with pytest.raises(Exception):
            score.total_score = 1.0

    def test_batch_scoring(self):
        """Batch scoring must return one score per input event."""
        events = [
            _make_event(url="https://a.com", title="A"),
            _make_event(url="https://b.com", title="B"),
        ]
        scorer = QualityScorer()
        scores = scorer.score_batch(events)
        assert len(scores) == 2


class TestNewsProcessor:
    """Tests for the combined news processing pipeline."""

    def test_process_and_score(self):
        """Processing must deduplicate events and produce quality scores."""
        events = [
            _make_event(url="https://a.com", title="A", source_level=SourceLevel.L1),
            _make_event(url="https://b.com", title="B", source_level=SourceLevel.L4),
        ]
        processor = NewsProcessor()
        result, scores = processor.process_and_score(events)

        assert len(result.unique_events) == 2
        assert len(scores) == 2
        assert scores[0].authority > scores[1].authority

    def test_filter_by_level(self):
        """Filtering by level must keep only events in the requested range."""
        events = [
            _make_event(url="https://a.com", title="A", source_level=SourceLevel.L1),
            _make_event(url="https://b.com", title="B", source_level=SourceLevel.L4),
            _make_event(url="https://c.com", title="C", source_level=SourceLevel.L5),
        ]
        filtered = NewsProcessor.filter_by_level(
            events, min_level=SourceLevel.L1, max_level=SourceLevel.L3
        )
        assert len(filtered) == 1
        assert filtered[0].source_level == SourceLevel.L1

    def test_l5_cannot_change_state(self):
        """L5 events must not be allowed to change research state."""
        event = _make_event(source_level=SourceLevel.L5)
        assert event.can_change_research_state is False

    def test_l3_can_change_state(self):
        """L3 events must be allowed to change research state."""
        event = _make_event(source_level=SourceLevel.L3)
        assert event.can_change_research_state is True

    def test_dedup_then_score_only_unique(self):
        """Scoring must run only on unique events after deduplication."""
        events = [
            _make_event(url="https://a.com", title="A"),
            _make_event(url="https://a.com", title="A dup"),
        ]
        processor = NewsProcessor()
        result, scores = processor.process_and_score(events)
        assert len(scores) == 1
