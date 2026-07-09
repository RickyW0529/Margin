"""Article extraction, writing-review, and briefing workflow."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from margin.news.agentic_models import NewsArticleFinding, NewsSecurityBrief
from margin.news.agentic_prompts import (
    ARTICLE_PROMPT_VERSION,
    BRIEF_PROMPT_VERSION,
    article_writer_schema,
    brief_schema,
    build_article_writer_prompt,
    build_brief_prompt,
    build_writing_review_prompt,
    writing_review_schema,
)
from margin.news.models import DocumentEvent, NewsTarget


class ArticleWorkflow:
    """Extract reviewed findings and derived briefs from persisted events.."""

    def __init__(self, *, llm_service: Any, max_review_rounds: int = 2) -> None:
        """Initialize the workflow.

        Args:
            llm_service: Any: .
            max_review_rounds: int: .

        Returns:
            None: .
        """
        self._llm = llm_service
        self._max_review_rounds = max(1, max_review_rounds)

    def extract_findings(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        events: tuple[DocumentEvent, ...],
    ) -> tuple[NewsArticleFinding, ...]:
        """Extract approved article findings for the target.

        Args:
            run_id: str: .
            target: NewsTarget: .
            events: tuple[DocumentEvent, ...]: .

        Returns:
            tuple[NewsArticleFinding, ...]: .
        """
        findings: list[NewsArticleFinding] = []
        for event in events:
            finding = self._extract_one(run_id=run_id, target=target, event=event)
            if finding is not None:
                findings.append(finding)
        return tuple(findings)

    def build_brief(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        findings: tuple[NewsArticleFinding, ...],
    ) -> NewsSecurityBrief | None:
        """Build a derived security brief from approved findings.

        Args:
            run_id: str: .
            target: NewsTarget: .
            findings: tuple[NewsArticleFinding, ...]: .

        Returns:
            NewsSecurityBrief | None: .
        """
        approved = tuple(finding for finding in findings if finding.review_status == "approved")
        if not approved:
            return None
        prompt = build_brief_prompt(target, approved)
        response = self._llm.complete_structured(
            prompt=prompt,
            output_schema=brief_schema(),
            task_type="summary",
            node_name=prompt.node_name,
            graph_run_id=run_id,
        )
        if not getattr(response, "success", False):
            return None
        output = dict(getattr(response, "output", {}) or {})
        summary = str(output.get("summary") or "").strip()
        if not summary:
            return None
        return NewsSecurityBrief(
            brief_id=_brief_id(run_id, target.security_id),
            run_id=run_id,
            security_id=target.security_id,
            summary=summary,
            finding_ids=tuple(finding.finding_id for finding in approved),
            source_event_ids=tuple(finding.event_id for finding in approved),
            is_derived=True,
            trust_level="derived_low_trust",
            prompt_version=BRIEF_PROMPT_VERSION,
            prompt_hash=prompt.prompt_hash,
            response_hash=_hash_json(output),
        )

    def _extract_one(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        event: DocumentEvent,
    ) -> NewsArticleFinding | None:
        """Extract and review one event.

        Args:
            run_id: str: .
            target: NewsTarget: .
            event: DocumentEvent: .

        Returns:
            NewsArticleFinding | None: .
        """
        revision_notes: tuple[str, ...] = ()
        draft: dict[str, Any] = {}
        writer_prompt_hash = ""
        writer_response_hash: str | None = None
        for _ in range(self._max_review_rounds):
            writer_prompt = build_article_writer_prompt(target, event, revision_notes)
            writer_response = self._llm.complete_structured(
                prompt=writer_prompt,
                output_schema=article_writer_schema(),
                task_type="extraction",
                node_name=writer_prompt.node_name,
                graph_run_id=run_id,
            )
            writer_prompt_hash = writer_prompt.prompt_hash
            if not getattr(writer_response, "success", False):
                return None
            draft = dict(getattr(writer_response, "output", {}) or {})
            writer_response_hash = _hash_json(draft)
            if not _key_points(draft):
                return None
            review_prompt = build_writing_review_prompt(target, event, draft)
            review_response = self._llm.complete_structured(
                prompt=review_prompt,
                output_schema=writing_review_schema(),
                task_type="validation",
                node_name=review_prompt.node_name,
                graph_run_id=run_id,
            )
            if not getattr(review_response, "success", False):
                return None
            review_output = dict(getattr(review_response, "output", {}) or {})
            local_notes = _local_review_notes(event, draft)
            if bool(review_output.get("approved")) and not local_notes:
                return NewsArticleFinding(
                    finding_id=_finding_id(run_id, target.security_id, event.event_id),
                    run_id=run_id,
                    security_id=target.security_id,
                    event_id=event.event_id,
                    title=event.title,
                    source_url=event.source_url,
                    key_points=_key_points(draft),
                    materiality=_optional_str(draft.get("materiality")),
                    sentiment=_optional_str(draft.get("sentiment")),
                    risk_flags=_string_tuple(draft.get("risk_flags", ())),
                    cited_spans=tuple(
                        item for item in draft.get("cited_spans", ()) if isinstance(item, dict)
                    ),
                    review_status="approved",
                    confidence=float(draft.get("confidence") or 0.0),
                    prompt_version=ARTICLE_PROMPT_VERSION,
                    prompt_hash=writer_prompt_hash,
                    response_hash=writer_response_hash,
                )
            revision_notes = (
                *_string_tuple(review_output.get("revision_notes", ())),
                *local_notes,
            )
        return None


def _finding_id(run_id: str, security_id: str, event_id: str) -> str:
    """Return a stable article finding id.

    Args:
        run_id: str: .
        security_id: str: .
        event_id: str: .

    Returns:
        str: .
    """
    digest = hashlib.sha256(f"{run_id}|{security_id}|{event_id}".encode()).hexdigest()
    return f"naf_{digest[:24]}"


def _brief_id(run_id: str, security_id: str) -> str:
    """Return a stable security brief id.

    Args:
        run_id: str: .
        security_id: str: .

    Returns:
        str: .
    """
    digest = hashlib.sha256(f"{run_id}|{security_id}|brief".encode()).hexdigest()
    return f"nsb_{digest[:24]}"


def _key_points(output: dict[str, Any]) -> tuple[str, ...]:
    """Return cleaned key points from model output.

    Args:
        output: dict[str, Any]: .

    Returns:
        tuple[str, ...]: .
    """
    return _string_tuple(output.get("key_points", ()))


def _local_review_notes(
    event: DocumentEvent,
    draft: dict[str, Any],
) -> tuple[str, ...]:
    """Return deterministic article-review issues independent of LLM judgment.

    Args:
        event: DocumentEvent: .
        draft: dict[str, Any]: .

    Returns:
        tuple[str, ...]: .
    """
    notes: list[str] = []
    cited_spans = tuple(item for item in draft.get("cited_spans", ()) if isinstance(item, dict))
    if not cited_spans:
        notes.append("missing cited_spans")
        return tuple(notes)
    content = event.content or ""
    for span in cited_spans:
        issue = _citation_span_issue(content, span)
        if issue:
            notes.append(issue)
    return tuple(notes)


def _citation_span_issue(content: str, span: dict[str, Any]) -> str:
    """Return a stable issue for an invalid citation span, or empty string.

    Args:
        content: str: .
        span: dict[str, Any]: .

    Returns:
        str: .
    """
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return "citation span missing integer start/end"
    if start < 0 or end <= start or end > len(content):
        return "citation span outside source content"
    quoted = span.get("text") or span.get("quote")
    if quoted is not None and str(quoted) != content[start:end]:
        return "citation span text mismatch"
    return ""


def _string_tuple(value: Any) -> tuple[str, ...]:
    """Normalize iterable output into strings.

    Args:
        value: Any: .

    Returns:
        tuple[str, ...]: .
    """
    return tuple(str(item).strip() for item in value or () if str(item).strip())


def _optional_str(value: Any) -> str | None:
    """Return a stripped string or None.

    Args:
        value: Any: .

    Returns:
        str | None: .
    """
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _hash_json(value: Any) -> str:
    """Hash a JSON-serializable value.

    Args:
        value: Any: .

    Returns:
        str: .
    """
    encoded = json.dumps(
        value,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
