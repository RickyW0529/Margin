"""Shared Context Store repositories for agent runtime artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from margin.agent_runtime.db_models import (
    AgentRuntimeArtifactRow,
    AgentRuntimeGuardrailDecisionRow,
    AgentRuntimeRunRow,
    AgentRuntimeStepRow,
)
from margin.agent_runtime.models import (
    AgentRun,
    AgentStep,
    ContextArtifact,
    GuardrailDecision,
)


def stable_json_hash(payload: Any) -> str:
    """Return a stable sha256 hash for JSON-compatible payloads.

    Args:
        payload: Any: .

    Returns:
        str: .
    """
    raw = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def make_context_artifact(
    *,
    artifact_id: str,
    run_id: str,
    artifact_type: str,
    producer_agent: str,
    payload_json: dict[str, Any],
    source_refs: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = (),
) -> ContextArtifact:
    """Build a context artifact with a stable payload hash.

    Args:
        artifact_id: str: .
        run_id: str: .
        artifact_type: str: .
        producer_agent: str: .
        payload_json: dict[str, Any]: .
        source_refs: tuple[str, ...]: .
        evidence_refs: tuple[str, ...]: .

    Returns:
        ContextArtifact: .
    """
    return ContextArtifact(
        artifact_id=artifact_id,
        run_id=run_id,
        artifact_type=artifact_type,
        producer_agent=producer_agent,
        payload_json=payload_json,
        payload_hash=stable_json_hash(payload_json),
        source_refs=source_refs,
        evidence_refs=evidence_refs,
    )


class AgentContextStore(Protocol):
    """Persistence contract for MainAgent and expert-agent context exchange.."""

    def add_run(self, run: AgentRun) -> None:
        """Persist an agent run idempotently.

        Args:
            run: AgentRun: .

        Returns:
            None: .
        """

    def get_run(self, run_id: str) -> AgentRun | None:
        """Return an agent run by identifier.

        Args:
            run_id: str: .

        Returns:
            AgentRun | None: .
        """

    def add_step(self, step: AgentStep) -> None:
        """Persist an agent step idempotently.

        Args:
            step: AgentStep: .

        Returns:
            None: .
        """

    def list_steps(self, run_id: str) -> list[AgentStep]:
        """List steps for a run in insertion order.

        Args:
            run_id: str: .

        Returns:
            list[AgentStep]: .
        """

    def add_artifact(self, artifact: ContextArtifact) -> None:
        """Persist an immutable context artifact.

        Args:
            artifact: ContextArtifact: .

        Returns:
            None: .
        """

    def get_artifact(self, artifact_id: str) -> ContextArtifact | None:
        """Return an artifact by identifier.

        Args:
            artifact_id: str: .

        Returns:
            ContextArtifact | None: .
        """

    def list_artifacts(
        self,
        run_id: str,
        *,
        artifact_type: str | None = None,
    ) -> list[ContextArtifact]:
        """List artifacts for a run, optionally filtered by artifact type.

        Args:
            run_id: str: .
            artifact_type: str | None: .

        Returns:
            list[ContextArtifact]: .
        """

    def add_guardrail_decision(self, decision: GuardrailDecision) -> None:
        """Persist a guardrail decision idempotently.

        Args:
            decision: GuardrailDecision: .

        Returns:
            None: .
        """

    def list_guardrail_decisions(self, run_id: str) -> list[GuardrailDecision]:
        """List guardrail decisions for a run in insertion order.

        Args:
            run_id: str: .

        Returns:
            list[GuardrailDecision]: .
        """


class MemoryAgentContextStore:
    """Process-local Shared Context Store for tests and local runtime wiring.."""

    def __init__(self) -> None:
        """Process __init__.

        Returns:
            None: .
        """
        self._runs: dict[str, AgentRun] = {}
        self._steps: dict[tuple[str, str], AgentStep] = {}
        self._step_order: list[tuple[str, str]] = []
        self._artifacts: dict[str, ContextArtifact] = {}
        self._artifact_order: list[str] = []
        self._guardrail_decisions: dict[str, GuardrailDecision] = {}
        self._guardrail_order: list[str] = []

    def add_run(self, run: AgentRun) -> None:
        """Process add_run.

        Args:
            run: AgentRun: .

        Returns:
            None: .
        """
        current = self._runs.get(run.run_id)
        if current is not None and current != run:
            raise ValueError(f"agent run '{run.run_id}' is immutable")
        self._runs[run.run_id] = run

    def get_run(self, run_id: str) -> AgentRun | None:
        """Process get_run.

        Args:
            run_id: str: .

        Returns:
            AgentRun | None: .
        """
        return self._runs.get(run_id)

    def add_step(self, step: AgentStep) -> None:
        """Process add_step.

        Args:
            step: AgentStep: .

        Returns:
            None: .
        """
        key = (step.run_id, step.step_id)
        current = self._steps.get(key)
        if current is not None and current != step:
            raise ValueError(f"agent step '{step.run_id}:{step.step_id}' is immutable")
        if current is None:
            self._step_order.append(key)
        self._steps[key] = step

    def list_steps(self, run_id: str) -> list[AgentStep]:
        """Process list_steps.

        Args:
            run_id: str: .

        Returns:
            list[AgentStep]: .
        """
        return [self._steps[key] for key in self._step_order if key[0] == run_id]

    def add_artifact(self, artifact: ContextArtifact) -> None:
        """Process add_artifact.

        Args:
            artifact: ContextArtifact: .

        Returns:
            None: .
        """
        self._validate_artifact_hash(artifact)
        current = self._artifacts.get(artifact.artifact_id)
        if current is not None and current != artifact:
            raise ValueError(f"context artifact '{artifact.artifact_id}' is immutable")
        if current is None:
            self._artifact_order.append(artifact.artifact_id)
        self._artifacts[artifact.artifact_id] = artifact

    def get_artifact(self, artifact_id: str) -> ContextArtifact | None:
        """Process get_artifact.

        Args:
            artifact_id: str: .

        Returns:
            ContextArtifact | None: .
        """
        return self._artifacts.get(artifact_id)

    def list_artifacts(
        self,
        run_id: str,
        *,
        artifact_type: str | None = None,
    ) -> list[ContextArtifact]:
        """Process list_artifacts.

        Args:
            run_id: str: .
            artifact_type: str | None: .

        Returns:
            list[ContextArtifact]: .
        """
        artifacts = [
            self._artifacts[artifact_id]
            for artifact_id in self._artifact_order
            if self._artifacts[artifact_id].run_id == run_id
        ]
        if artifact_type is None:
            return artifacts
        return [artifact for artifact in artifacts if artifact.artifact_type == artifact_type]

    def add_guardrail_decision(self, decision: GuardrailDecision) -> None:
        """Process add_guardrail_decision.

        Args:
            decision: GuardrailDecision: .

        Returns:
            None: .
        """
        current = self._guardrail_decisions.get(decision.decision_id)
        if current is not None and current != decision:
            raise ValueError(f"guardrail decision '{decision.decision_id}' is immutable")
        if current is None:
            self._guardrail_order.append(decision.decision_id)
        self._guardrail_decisions[decision.decision_id] = decision

    def list_guardrail_decisions(self, run_id: str) -> list[GuardrailDecision]:
        """Process list_guardrail_decisions.

        Args:
            run_id: str: .

        Returns:
            list[GuardrailDecision]: .
        """
        return [
            self._guardrail_decisions[decision_id]
            for decision_id in self._guardrail_order
            if self._guardrail_decisions[decision_id].run_id == run_id
        ]

    @staticmethod
    def _validate_artifact_hash(artifact: ContextArtifact) -> None:
        """Process _validate_artifact_hash.

        Args:
            artifact: ContextArtifact: .

        Returns:
            None: .
        """
        expected = stable_json_hash(artifact.payload_json)
        if artifact.payload_hash != expected:
            raise ValueError(f"context artifact '{artifact.artifact_id}' payload hash mismatch")


class SQLAlchemyAgentContextStore:
    """SQLAlchemy-backed Shared Context Store.."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        """Process __init__.

        Args:
            session_factory: Callable[[], Session]: .

        Returns:
            None: .
        """
        self._session_factory = session_factory

    def add_run(self, run: AgentRun) -> None:
        """Process add_run.

        Args:
            run: AgentRun: .

        Returns:
            None: .
        """
        payload = run.model_dump(mode="json")
        with self._session_factory.begin() as session:
            current = session.get(AgentRuntimeRunRow, run.run_id)
            if current is None:
                session.add(
                    AgentRuntimeRunRow(
                        run_id=run.run_id,
                        run_type=run.run_type.value,
                        status=run.status.value,
                        permission_mode=run.permission_mode.value,
                        trigger_source=run.trigger_source,
                        payload=payload,
                        started_at=run.started_at,
                        finished_at=run.finished_at,
                        created_at=datetime.now(UTC),
                    )
                )
                return
            if current.payload != payload:
                raise ValueError(f"agent run '{run.run_id}' is immutable")

    def get_run(self, run_id: str) -> AgentRun | None:
        """Process get_run.

        Args:
            run_id: str: .

        Returns:
            AgentRun | None: .
        """
        with self._session_factory() as session:
            row = session.get(AgentRuntimeRunRow, run_id)
            return AgentRun.model_validate(row.payload) if row else None

    def add_step(self, step: AgentStep) -> None:
        """Process add_step.

        Args:
            step: AgentStep: .

        Returns:
            None: .
        """
        payload = step.model_dump(mode="json")
        key = {"run_id": step.run_id, "step_id": step.step_id}
        with self._session_factory.begin() as session:
            current = session.get(AgentRuntimeStepRow, key)
            if current is None:
                session.add(
                    AgentRuntimeStepRow(
                        run_id=step.run_id,
                        step_id=step.step_id,
                        expert_agent_name=step.expert_agent_name,
                        skill_id=step.skill_id,
                        status=step.status.value,
                        payload=payload,
                        created_at=datetime.now(UTC),
                    )
                )
                return
            if current.payload != payload:
                raise ValueError(f"agent step '{step.run_id}:{step.step_id}' is immutable")

    def list_steps(self, run_id: str) -> list[AgentStep]:
        """Process list_steps.

        Args:
            run_id: str: .

        Returns:
            list[AgentStep]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                select(AgentRuntimeStepRow)
                .where(AgentRuntimeStepRow.run_id == run_id)
                .order_by(AgentRuntimeStepRow.created_at.asc())
            ).all()
            return [AgentStep.model_validate(row.payload) for row in rows]

    def add_artifact(self, artifact: ContextArtifact) -> None:
        """Process add_artifact.

        Args:
            artifact: ContextArtifact: .

        Returns:
            None: .
        """
        MemoryAgentContextStore._validate_artifact_hash(artifact)
        payload = artifact.model_dump(mode="json")
        with self._session_factory.begin() as session:
            current = session.get(AgentRuntimeArtifactRow, artifact.artifact_id)
            if current is None:
                session.add(
                    AgentRuntimeArtifactRow(
                        artifact_id=artifact.artifact_id,
                        run_id=artifact.run_id,
                        artifact_type=artifact.artifact_type,
                        producer_agent=artifact.producer_agent,
                        payload_json=artifact.payload_json,
                        payload_hash=artifact.payload_hash,
                        source_refs=list(artifact.source_refs),
                        evidence_refs=list(artifact.evidence_refs),
                        payload=payload,
                        created_at=artifact.created_at,
                    )
                )
                return
            if current.payload != payload:
                raise ValueError(f"context artifact '{artifact.artifact_id}' is immutable")

    def get_artifact(self, artifact_id: str) -> ContextArtifact | None:
        """Process get_artifact.

        Args:
            artifact_id: str: .

        Returns:
            ContextArtifact | None: .
        """
        with self._session_factory() as session:
            row = session.get(AgentRuntimeArtifactRow, artifact_id)
            return ContextArtifact.model_validate(row.payload) if row else None

    def list_artifacts(
        self,
        run_id: str,
        *,
        artifact_type: str | None = None,
    ) -> list[ContextArtifact]:
        """Process list_artifacts.

        Args:
            run_id: str: .
            artifact_type: str | None: .

        Returns:
            list[ContextArtifact]: .
        """
        statement = select(AgentRuntimeArtifactRow).where(AgentRuntimeArtifactRow.run_id == run_id)
        if artifact_type is not None:
            statement = statement.where(AgentRuntimeArtifactRow.artifact_type == artifact_type)
        statement = statement.order_by(AgentRuntimeArtifactRow.created_at.asc())
        with self._session_factory() as session:
            rows = session.scalars(statement).all()
            return [ContextArtifact.model_validate(row.payload) for row in rows]

    def add_guardrail_decision(self, decision: GuardrailDecision) -> None:
        """Process add_guardrail_decision.

        Args:
            decision: GuardrailDecision: .

        Returns:
            None: .
        """
        payload = decision.model_dump(mode="json")
        with self._session_factory.begin() as session:
            current = session.get(
                AgentRuntimeGuardrailDecisionRow,
                decision.decision_id,
            )
            if current is None:
                session.add(
                    AgentRuntimeGuardrailDecisionRow(
                        decision_id=decision.decision_id,
                        run_id=decision.run_id,
                        stage=decision.stage.value,
                        allowed=decision.allowed,
                        evaluation_summary=decision.evaluation_summary,
                        payload=payload,
                        created_at=decision.created_at,
                    )
                )
                return
            if current.payload != payload:
                raise ValueError(f"guardrail decision '{decision.decision_id}' is immutable")

    def list_guardrail_decisions(self, run_id: str) -> list[GuardrailDecision]:
        """Process list_guardrail_decisions.

        Args:
            run_id: str: .

        Returns:
            list[GuardrailDecision]: .
        """
        with self._session_factory() as session:
            rows = session.scalars(
                select(AgentRuntimeGuardrailDecisionRow)
                .where(AgentRuntimeGuardrailDecisionRow.run_id == run_id)
                .order_by(AgentRuntimeGuardrailDecisionRow.created_at.asc())
            ).all()
            return [GuardrailDecision.model_validate(row.payload) for row in rows]
