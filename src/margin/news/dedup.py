"""Deduplication and compliance grading for news events.

Implements multi-layer deduplication, repost-chain detection, L1-L5 compliance grading,
and quality scoring as defined in the project specification.

Corresponds to specs 03 sections 3 and 4, architecture section 6.4 deduplication rules,
and section 6.1 source priority.

Plan 0303 coverage:
  0303.1 URL / content-hash / title-date deduplication.
  0303.2 SimHash and vector-similarity deduplication.
  0303.3 Repost-chain detection and earliest-source retention.
  0303.4 L1-L5 compliance grading and quality scoring.

Deduplication rules (architecture section 6.4):
  1. URL uniqueness.
  2. Content hash.
  3. Title and publication date.
  4. Body SimHash.
  5. Vector similarity.
  6. Repost-chain detection.
  7. Keep the earliest reliable source.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from margin.news.models import DocumentEvent, SourceLevel, utc_now

if TYPE_CHECKING:
    from margin.news.repository import NewsRepository

# ---------------------------------------------------------------------------
# Deduplication result
# ---------------------------------------------------------------------------


class DedupResult(BaseModel):
    """Result container produced by the deduplication pipeline.."""

    unique_events: list[DocumentEvent] = Field(default_factory=list)
    duplicate_count: int = 0
    duplicates: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def total_count(self) -> int:
        """Total number of events processed, both unique and duplicate.

        Returns:
            int: .
        """
        return len(self.unique_events) + self.duplicate_count


# ---------------------------------------------------------------------------
# SimHash implementation (0303.2)
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Tokenize text for SimHash processing.

    Args:
        text: str: .

    Returns:
        list[str]: .
    """
    text = text.lower().strip()
    tokens: list[str] = []

    english_words = re.findall(r"[a-z]+", text)
    tokens.extend(english_words)

    chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
    tokens.extend(chinese_chars)

    return tokens


def _hash64(token: str) -> int:
    """Hash a token to a 64-bit integer.

    Args:
        token: str: .

    Returns:
        int: .
    """
    h = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def compute_simhash(text: str) -> int:
    """Compute the SimHash fingerprint of a text.

    Args:
        text: str: .

    Returns:
        int: .
    """
    tokens = _tokenize(text)
    if not tokens:
        return 0

    vector = [0] * 64

    for token in tokens:
        h = _hash64(token)
        for i in range(64):
            bit = (h >> i) & 1
            vector[i] += 1 if bit else -1

    fingerprint = 0
    for i in range(64):
        if vector[i] > 0:
            fingerprint |= 1 << i

    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """Calculate the Hamming distance between two SimHash fingerprints.

    Args:
        a: int: .
        b: int: .

    Returns:
        int: .
    """
    return bin(a ^ b).count("1")


def simhash_similarity(a: int, b: int) -> float:
    """Compute the similarity between two SimHash fingerprints in the range [0, 1].

    Args:
        a: int: .
        b: int: .

    Returns:
        float: .
    """
    distance = hamming_distance(a, b)
    return 1.0 - distance / 64.0


# ---------------------------------------------------------------------------
# 0303.1 / 0303.2 / 0303.3 Deduplicator
# ---------------------------------------------------------------------------


class Deduplicator:
    """Multi-layer deduplicator implementing architecture section 6.4.."""

    def __init__(
        self,
        simhash_threshold: int = 3,
        title_similarity_threshold: float = 0.85,
        vector_similarity_func: Callable[[DocumentEvent, DocumentEvent], float] | None = None,
        vector_similarity_threshold: float = 0.92,
    ) -> None:
        """Initialize the deduplicator with configurable thresholds.

        Args:
            simhash_threshold: int: .
            title_similarity_threshold: float: .
            vector_similarity_func: Callable[[DocumentEvent, DocumentEvent], float] | None: .
            vector_similarity_threshold: float: .

        Returns:
            None: .
        """
        self._simhash_threshold = simhash_threshold
        self._title_threshold = title_similarity_threshold
        self._vector_similarity_func = vector_similarity_func
        self._vector_similarity_threshold = vector_similarity_threshold
        self._seen_urls: dict[str, DocumentEvent] = {}
        self._seen_hashes: dict[str, DocumentEvent] = {}
        self._seen_title_dates: dict[str, DocumentEvent] = {}
        self._seen_simhashes: list[tuple[int, DocumentEvent]] = []
        self._seen_events: list[DocumentEvent] = []

    def seed(self, events: list[DocumentEvent]) -> None:
        """Seed the deduplicator with already-known canonical events.

        Args:
            events: list[DocumentEvent]: .

        Returns:
            None: .
        """
        for event in events:
            self._record_seen(event)

    def find_duplicate(
        self,
        event: DocumentEvent,
    ) -> tuple[str, DocumentEvent] | None:
        """Public duplicate probe used by persistent processors.

        Args:
            event: DocumentEvent: .

        Returns:
            tuple[str, DocumentEvent] | None: .
        """
        return self._check_duplicate(event)

    def record_event(self, event: DocumentEvent) -> None:
        """Record a canonical event after it is persisted.

        Args:
            event: DocumentEvent: .

        Returns:
            None: .
        """
        self._record_seen(event)

    def deduplicate(
        self,
        events: list[DocumentEvent],
    ) -> DedupResult:
        """Run multi-layer deduplication on a batch of document events.

        Args:
            events: list[DocumentEvent]: .

        Returns:
            DedupResult: .
        """
        sorted_events = sorted(events, key=lambda e: (e.source_level, e.published_at))

        unique: list[DocumentEvent] = []
        duplicates: list[dict[str, Any]] = []

        for event in sorted_events:
            duplicate_match = self._check_duplicate(event)
            if duplicate_match is not None:
                dup_reason, canonical = duplicate_match
                duplicates.append(
                    {
                        "event_id": event.event_id,
                        "source_url": event.source_url,
                        "reason": dup_reason,
                        "duplicate_of": canonical.event_id,
                    }
                )
            else:
                unique.append(event)
                self._record_seen(event)

        return DedupResult(
            unique_events=unique,
            duplicate_count=len(duplicates),
            duplicates=duplicates,
        )

    def _check_duplicate(
        self,
        event: DocumentEvent,
    ) -> tuple[str, DocumentEvent] | None:
        """Check whether a single event is a duplicate of one already seen.

        Args:
            event: DocumentEvent: .

        Returns:
            tuple[str, DocumentEvent] | None: .
        """
        canonical = self._seen_urls.get(event.source_url)
        if canonical is not None:
            return "duplicate_url", canonical

        canonical = self._seen_hashes.get(event.content_hash)
        if canonical is not None:
            return "duplicate_content_hash", canonical

        title_date_key = f"{event.title.lower().strip()}|{event.published_at.date()}"
        canonical = self._seen_title_dates.get(title_date_key)
        if canonical is not None:
            return "duplicate_title_date", canonical

        content_text = event.content or event.title
        event_simhash = compute_simhash(content_text)
        for existing_hash, existing_event in self._seen_simhashes:
            distance = hamming_distance(event_simhash, existing_hash)
            if distance <= self._simhash_threshold:
                if event.source_level > existing_event.source_level:
                    return f"repost_of:{existing_event.event_id}", existing_event
                return "simhash_duplicate", existing_event

        if self._vector_similarity_func is not None:
            for existing_event in self._seen_events:
                similarity = self._vector_similarity_func(event, existing_event)
                if similarity >= self._vector_similarity_threshold:
                    return "vector_similarity", existing_event

        return None

    def _record_seen(self, event: DocumentEvent) -> None:
        """Record a unique event so it can be used for future duplicate checks.

        Args:
            event: DocumentEvent: .

        Returns:
            None: .
        """
        self._seen_urls[event.source_url] = event
        self._seen_hashes[event.content_hash] = event
        title_date_key = f"{event.title.lower().strip()}|{event.published_at.date()}"
        self._seen_title_dates[title_date_key] = event

        content_text = event.content or event.title
        event_simhash = compute_simhash(content_text)
        self._seen_simhashes.append((event_simhash, event))
        if event.event_id not in {seen.event_id for seen in self._seen_events}:
            self._seen_events.append(event)


# ---------------------------------------------------------------------------
# 0303.4 Quality scoring
# ---------------------------------------------------------------------------


class QualityScore(BaseModel):
    """Source quality score for a document event.."""

    event_id: str
    source_level: SourceLevel
    completeness: float = 0.0
    timeliness: float = 0.0
    uniqueness: float = 1.0
    authority: float = 0.0
    total_score: float = 0.0

    model_config = {"frozen": True}


class QualityScorer:
    """Quality scorer for document events (architecture section 6.2 Quality Scorer).."""

    AUTHORITY_SCORES = {
        SourceLevel.L1: 1.0,
        SourceLevel.L2: 0.8,
        SourceLevel.L3: 0.6,
        SourceLevel.L4: 0.4,
        SourceLevel.L5: 0.2,
    }

    def __init__(
        self,
        timeliness_decay_days: float = 30.0,
    ) -> None:
        """Initialize the quality scorer.

        Args:
            timeliness_decay_days: float: .

        Returns:
            None: .
        """
        self._decay_days = timeliness_decay_days

    def score(self, event: DocumentEvent) -> QualityScore:
        """Compute a QualityScore for a single document event.

        Args:
            event: DocumentEvent: .

        Returns:
            QualityScore: .
        """
        authority = self.AUTHORITY_SCORES.get(event.source_level, 0.0)

        if event.content and len(event.content) > 100:
            completeness = 1.0
        elif event.content and len(event.content) > 0:
            completeness = 0.5
        else:
            completeness = 0.1

        now = utc_now()
        age_days = (now - event.published_at).total_seconds() / 86400
        if age_days < 0:
            age_days = 0
        timeliness = max(0.0, 1.0 - age_days / self._decay_days)

        uniqueness = 1.0 if event.is_original else 0.3

        total = 0.40 * authority + 0.25 * completeness + 0.20 * timeliness + 0.15 * uniqueness

        return QualityScore(
            event_id=event.event_id,
            source_level=event.source_level,
            completeness=completeness,
            timeliness=timeliness,
            uniqueness=uniqueness,
            authority=authority,
            total_score=round(total, 4),
        )

    def score_batch(self, events: list[DocumentEvent]) -> list[QualityScore]:
        """Compute QualityScore objects for a batch of events.

        Args:
            events: list[DocumentEvent]: .

        Returns:
            list[QualityScore]: .
        """
        return [self.score(e) for e in events]


# ---------------------------------------------------------------------------
# 0303 Integration: deduplication and grading service
# ---------------------------------------------------------------------------


class NewsProcessor:
    """News processor combining deduplication, grading, and quality scoring.."""

    def __init__(
        self,
        deduplicator: Deduplicator | None = None,
        quality_scorer: QualityScorer | None = None,
    ) -> None:
        """Initialize the news processor.

        Args:
            deduplicator: Deduplicator | None: .
            quality_scorer: QualityScorer | None: .

        Returns:
            None: .
        """
        self._deduplicator = deduplicator or Deduplicator()
        self._quality_scorer = quality_scorer or QualityScorer()

    def process(self, events: list[DocumentEvent]) -> DedupResult:
        """Deduplicate a batch of document events.

        Args:
            events: list[DocumentEvent]: .

        Returns:
            DedupResult: .
        """
        return self._deduplicator.deduplicate(events)

    def score(self, event: DocumentEvent) -> QualityScore:
        """Compute a quality score for a single event.

        Args:
            event: DocumentEvent: .

        Returns:
            QualityScore: .
        """
        return self._quality_scorer.score(event)

    def score_batch(self, events: list[DocumentEvent]) -> list[QualityScore]:
        """Compute quality scores for a batch of events.

        Args:
            events: list[DocumentEvent]: .

        Returns:
            list[QualityScore]: .
        """
        return self._quality_scorer.score_batch(events)

    def process_and_score(
        self,
        events: list[DocumentEvent],
    ) -> tuple[DedupResult, list[QualityScore]]:
        """Run deduplication and scoring in one call.

        Args:
            events: list[DocumentEvent]: .

        Returns:
            tuple[DedupResult, list[QualityScore]]: .
        """
        result = self.process(events)
        scores = self.score_batch(result.unique_events)
        return result, scores

    @staticmethod
    def filter_by_level(
        events: list[DocumentEvent],
        min_level: SourceLevel = SourceLevel.L1,
        max_level: SourceLevel = SourceLevel.L3,
    ) -> list[DocumentEvent]:
        """Filter events by source level.

        Args:
            events: list[DocumentEvent]: .
            min_level: SourceLevel: .
            max_level: SourceLevel: .

        Returns:
            list[DocumentEvent]: .
        """
        return [e for e in events if min_level <= e.source_level <= max_level]


class PersistentNewsProcessor:
    """News processor that persists unique events, duplicate decisions, and repost chains.."""

    def __init__(
        self,
        repository: NewsRepository,
        *,
        simhash_threshold: int = 3,
        vector_similarity_func: Callable[[DocumentEvent, DocumentEvent], float] | None = None,
        vector_similarity_threshold: float = 0.92,
        quality_scorer: QualityScorer | None = None,
    ) -> None:
        """Initialize the persistent news processor.

        Args:
            repository: NewsRepository: .
            simhash_threshold: int: .
            vector_similarity_func: Callable[[DocumentEvent, DocumentEvent], float] | None: .
            vector_similarity_threshold: float: .
            quality_scorer: QualityScorer | None: .

        Returns:
            None: .
        """
        self._repository = repository
        self._simhash_threshold = simhash_threshold
        self._vector_similarity_func = vector_similarity_func
        self._vector_similarity_threshold = vector_similarity_threshold
        self._quality_scorer = quality_scorer or QualityScorer()

    def process(self, events: list[DocumentEvent]) -> DedupResult:
        """Deduplicate against persisted canonical events and record every decision.

        Args:
            events: list[DocumentEvent]: .

        Returns:
            DedupResult: .
        """
        deduplicator = Deduplicator(
            simhash_threshold=self._simhash_threshold,
            vector_similarity_func=self._vector_similarity_func,
            vector_similarity_threshold=self._vector_similarity_threshold,
        )
        deduplicator.seed(self._repository.list_unique_events())

        unique: list[DocumentEvent] = []
        duplicates: list[dict[str, Any]] = []
        for event in sorted(events, key=lambda item: (item.source_level, item.published_at)):
            match = deduplicator.find_duplicate(event)
            if match is None:
                self._repository.add_document_event(event, publishable=True)
                deduplicator.record_event(event)
                unique.append(event)
                continue

            reason, canonical = match
            self._repository.add_document_event(event, publishable=False)
            self._repository.add_dedup_record(
                duplicate_event_id=event.event_id,
                canonical_event_id=canonical.event_id,
                reason=reason,
                similarity_score=None,
            )
            self._repository.add_repost_edge(
                parent_event_id=canonical.event_id,
                child_event_id=event.event_id,
                reason=reason,
            )
            duplicates.append(
                {
                    "event_id": event.event_id,
                    "source_url": event.source_url,
                    "reason": reason,
                    "duplicate_of": canonical.event_id,
                }
            )

        return DedupResult(
            unique_events=unique,
            duplicate_count=len(duplicates),
            duplicates=duplicates,
        )

    def score(self, event: DocumentEvent) -> QualityScore:
        """Compute quality score for a persisted or incoming event.

        Args:
            event: DocumentEvent: .

        Returns:
            QualityScore: .
        """
        return self._quality_scorer.score(event)
