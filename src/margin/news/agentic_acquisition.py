"""High-level orchestration for agentic news acquisition."""

from __future__ import annotations

import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Protocol

from margin.news.agentic_models import (
    NewsAgentRun,
    NewsAgentRunStatus,
    NewsAgentTask,
    NewsAgentTaskStatus,
    NewsArticleFinding,
    NewsSearchPlan,
    NewsSecurityBrief,
)
from margin.news.models import DocumentEvent, NewsTarget, utc_now
from margin.news.refresh_service import ProviderRateLimited
from margin.news.repository import NewsRepository


class QuantTargetRepositoryLike(Protocol):
    """Protocol for scoped quant-to-news target readers."""

    def list_targets(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
        include_near_threshold: bool = False,
    ) -> tuple[NewsTarget, ...]:
        """Return news targets for a quant run.

        Args:
            scope_version_id: Identifier of the scope version that produced the quant run.
            quant_run_id: Identifier of the quant run whose candidates are being loaded.
            decision_at: Decision timestamp used to scope the quant run.
            include_near_threshold: Whether to include near-threshold securities in addition
                to PASS targets.

        Returns:
            Tuple of ``NewsTarget`` objects sorted by priority and security id.
        """


class KeywordWorkflowLike(Protocol):
    """Protocol for keyword plan builders."""

    def build_plan(self, *, run_id: str, target: NewsTarget) -> NewsSearchPlan:
        """Build a reviewed search plan.

        Args:
            run_id: Identifier of the agentic news acquisition run.
            target: News target to build queries for.

        Returns:
            A reviewed ``NewsSearchPlan`` (approved or deterministic fallback).
        """


class WebSearchServiceLike(Protocol):
    """Protocol for controlled WebSearch acquisition."""

    def search_and_acquire(
        self,
        query: str,
        max_results: int = 10,
    ) -> tuple[object, list[object]]:
        """Search, download, snapshot, parse, persist, and return events.

        Args:
            query: Search query string.
            max_results: Maximum number of results to acquire.

        Returns:
            Tuple of (search query record, list of acquired document events).
        """


class ArticleWorkflowLike(Protocol):
    """Protocol for article extraction and briefing."""

    def extract_findings(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        events: tuple[DocumentEvent, ...],
    ) -> tuple[NewsArticleFinding, ...]:
        """Extract reviewed findings.

        Args:
            run_id: Identifier of the agentic news acquisition run.
            target: News target the events belong to.
            events: Tuple of persisted document events to extract findings from.

        Returns:
            Tuple of reviewed ``NewsArticleFinding`` objects.
        """

    def build_brief(
        self,
        *,
        run_id: str,
        target: NewsTarget,
        findings: tuple[NewsArticleFinding, ...],
    ) -> NewsSecurityBrief | None:
        """Build a derived security brief.

        Args:
            run_id: Identifier of the agentic news acquisition run.
            target: News target the findings belong to.
            findings: Tuple of approved article findings to summarize.

        Returns:
            A ``NewsSecurityBrief`` if approved findings exist, otherwise None.
        """


class AgenticNewsAcquisitionService:
    """Run agentic news acquisition for one quant run."""

    def __init__(
        self,
        *,
        repository: NewsRepository,
        target_repository: QuantTargetRepositoryLike,
        keyword_workflow: KeywordWorkflowLike,
        websearch_service: WebSearchServiceLike,
        article_workflow: ArticleWorkflowLike,
    ) -> None:
        """Initialize the service with its collaborators.

        Args:
            repository: Repository used to persist runs, plans, findings, and briefs.
            target_repository: Reader that loads quant-selected news targets.
            keyword_workflow: Workflow that builds reviewed search plans.
            websearch_service: Service that performs controlled WebSearch acquisition.
            article_workflow: Workflow that extracts findings and builds briefs.
        """
        self._repository = repository
        self._targets = target_repository
        self._keywords = keyword_workflow
        self._websearch = websearch_service
        self._articles = article_workflow

    def run_for_quant_run(
        self,
        *,
        scope_version_id: str,
        quant_run_id: str,
        decision_at: datetime,
        include_near_threshold: bool = False,
        max_workers: int = 4,
        idempotency_key: str | None = None,
    ) -> NewsAgentRun:
        """Run acquisition for all eligible quant targets.

        Args:
            scope_version_id: Identifier of the scope version that produced the quant run.
            quant_run_id: Identifier of the quant run to acquire news for.
            decision_at: Decision timestamp used to scope the quant run.
            include_near_threshold: Whether to include near-threshold securities.
            max_workers: Maximum number of targets to process concurrently.
            idempotency_key: Optional mutation idempotency key.

        Returns:
            A ``NewsAgentRun`` describing the final run status and target counts.
        """
        run_id = _run_id(
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            decision_at=decision_at,
            include_near_threshold=include_near_threshold,
            idempotency_key=idempotency_key,
        )
        if idempotency_key:
            existing = self._repository.get_news_agent_run(run_id)
            if existing is not None:
                return existing
        targets = self._targets.list_targets(
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            decision_at=decision_at,
            include_near_threshold=include_near_threshold,
        )
        run = NewsAgentRun(
            run_id=run_id,
            scope_version_id=scope_version_id,
            quant_run_id=quant_run_id,
            decision_at=decision_at,
            status=NewsAgentRunStatus.RUNNING,
            target_count=len(targets),
            include_near_threshold=include_near_threshold,
            config_hash=_hash_json(
                {
                    "scope_version_id": scope_version_id,
                    "quant_run_id": quant_run_id,
                    "include_near_threshold": include_near_threshold,
                }
            ),
            started_at=utc_now(),
        )
        self._repository.add_news_agent_run(run)
        if not targets:
            completed = run.model_copy(
                update={
                    "status": NewsAgentRunStatus.COMPLETED_EMPTY,
                    "finished_at": utc_now(),
                }
            )
            self._repository.add_news_agent_run(completed)
            return completed

        failed_targets = 0
        try:
            failed_targets = self._process_targets(
                run_id=run_id,
                targets=targets,
                max_workers=max_workers,
            )
        except ProviderRateLimited as exc:
            waiting = run.model_copy(
                update={
                    "status": NewsAgentRunStatus.WAITING_RATE_LIMIT,
                    "error_summary": {
                        "provider": exc.provider_name,
                        "retry_after_seconds": exc.retry_after_seconds,
                    },
                }
            )
            self._repository.add_news_agent_run(waiting)
            return waiting
        except Exception as exc:
            if _is_provider_waiting_error(exc):
                waiting = run.model_copy(
                    update={
                        "status": NewsAgentRunStatus.WAITING_PROVIDER,
                        "error_summary": _provider_error_summary(exc),
                    }
                )
                self._repository.add_news_agent_run(waiting)
                return waiting
            raise
        status = (
            NewsAgentRunStatus.PARTIAL if failed_targets else NewsAgentRunStatus.COMPLETED
        )
        completed = run.model_copy(
            update={
                "status": status,
                "finished_at": utc_now(),
                "error_summary": {"failed_targets": failed_targets}
                if failed_targets
                else {},
            }
        )
        self._repository.add_news_agent_run(completed)
        return completed

    def _process_targets(
        self,
        *,
        run_id: str,
        targets: tuple[NewsTarget, ...],
        max_workers: int,
    ) -> int:
        """Process targets, using bounded parallelism when requested."""
        worker_count = min(max(1, max_workers), len(targets))
        if worker_count <= 1:
            return sum(
                1
                for target in targets
                if not self._process_target(run_id=run_id, target=target)
            )
        failed_targets = 0
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(self._process_target, run_id=run_id, target=target)
                for target in targets
            ]
            for future in as_completed(futures):
                if not future.result():
                    failed_targets += 1
        return failed_targets

    def _process_target(self, *, run_id: str, target: NewsTarget) -> bool:
        """Process one target and return whether it completed."""
        self._repository.add_news_agent_task(
            _target_task(
                run_id=run_id,
                target=target,
                status=NewsAgentTaskStatus.RUNNING,
            )
        )
        try:
            plan = self._keywords.build_plan(run_id=run_id, target=target)
            self._repository.add_news_search_plan(plan)
            events: list[DocumentEvent] = []
            for query in plan.queries:
                _, acquired = self._websearch.search_and_acquire(query, max_results=5)
                events.extend(
                    event for event in acquired if isinstance(event, DocumentEvent)
                )
            findings = self._articles.extract_findings(
                run_id=run_id,
                target=target,
                events=tuple(events),
            )
            for finding in findings:
                self._repository.add_news_article_finding(finding)
            brief = self._articles.build_brief(
                run_id=run_id,
                target=target,
                findings=findings,
            )
            if brief is not None:
                self._repository.add_news_security_brief(brief)
        except ProviderRateLimited:
            raise
        except Exception as exc:
            if _is_provider_waiting_error(exc):
                raise
            self._repository.add_news_agent_task(
                _target_task(
                    run_id=run_id,
                    target=target,
                    status=NewsAgentTaskStatus.FAILED_FINAL,
                    error_code=exc.__class__.__name__,
                    error_message=str(exc),
                )
            )
            return False
        self._repository.add_news_agent_task(
            _target_task(
                run_id=run_id,
                target=target,
                status=NewsAgentTaskStatus.APPROVED,
            )
        )
        return True


def _run_id(
    *,
    scope_version_id: str,
    quant_run_id: str,
    decision_at: datetime,
    include_near_threshold: bool,
    idempotency_key: str | None = None,
) -> str:
    """Return a compact run id."""
    unique_component = idempotency_key or uuid.uuid4().hex
    payload = (
        f"{scope_version_id}|{quant_run_id}|{decision_at.isoformat()}|"
        f"{include_near_threshold}|{unique_component}"
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return f"nar_{digest[:24]}"


def _target_task(
    *,
    run_id: str,
    target: NewsTarget,
    status: NewsAgentTaskStatus,
    error_code: str | None = None,
    error_message: str | None = None,
) -> NewsAgentTask:
    """Build a target-level pipeline audit task."""
    completed_at = utc_now() if status != NewsAgentTaskStatus.RUNNING else None
    return NewsAgentTask(
        task_id=_target_task_id(run_id, target.security_id),
        run_id=run_id,
        security_id=target.security_id,
        task_type="target_pipeline",
        status=status,
        request_hash=_hash_json(target.model_dump(mode="json")),
        error_code=error_code,
        error_message=error_message,
        payload={
            "symbol": target.symbol,
            "name": target.name,
            "trigger_type": target.trigger_type.value,
        },
        completed_at=completed_at,
    )


def _target_task_id(run_id: str, security_id: str) -> str:
    """Return a deterministic target-pipeline task id."""
    digest = hashlib.sha256(f"{run_id}|{security_id}|target_pipeline".encode()).hexdigest()
    return f"nat_{digest[:24]}"


def _hash_json(value: Any) -> str:
    """Hash a JSON-serializable value."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _is_provider_waiting_error(exc: Exception) -> bool:
    """Return whether an exception means the external provider is unavailable."""
    return str(getattr(exc, "code", "")) in {
        "provider_budget_exceeded",
        "provider_paygo_limit_exceeded",
        "provider_auth_failed",
    }


def _provider_error_summary(exc: Exception) -> dict[str, Any]:
    """Return token-safe provider error metadata."""
    return {
        "provider": str(getattr(exc, "provider_name", "unknown")),
        "error_code": str(getattr(exc, "code", "provider_unavailable")),
        "retryable": bool(getattr(exc, "retryable", False)),
    }
