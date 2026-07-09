"""Deterministic ContextFact extraction from safe artifact payloads."""

from __future__ import annotations

from margin.agent_runtime.models import ContextArtifact
from margin.agents.protocol.models import ContextFact


class ContextFactExtractor:
    """ContextFactExtractor.."""

    def extract(self, artifact: ContextArtifact) -> tuple[ContextFact, ...]:
        """Extract.

        Args:
            artifact: ContextArtifact: .

        Returns:
            tuple[ContextFact, ...]: .
        """
        if artifact.artifact_type == "quant_result":
            return (_quant_result_fact(artifact),)
        if artifact.artifact_type == "backtest_result":
            return (_backtest_result_fact(artifact),)
        if artifact.artifact_type == "evidence_package":
            return (_evidence_package_fact(artifact),)
        if artifact.artifact_type == "stock_analysis_result":
            return (_stock_analysis_fact(artifact),)
        if "data" in artifact.artifact_type:
            return (_data_status_fact(artifact),)
        return (_generic_fact(artifact),)


def chat_memory_fact(summary: str) -> ContextFact:
    """Chat memory fact.

    Args:
        summary: str: .

    Returns:
        ContextFact: .
    """
    return ContextFact(
        fact_id="fact_chat_memory_summary",
        statement=f"Chat memory summary for user intent only: {summary}",
        confidence=0.8,
        fact_type="user_constraint",
        subject_type="user",
        subject_id="local-user",
    )


def _quant_result_fact(artifact: ContextArtifact) -> ContextFact:
    """Quant result fact.

    Args:
        artifact: ContextArtifact: .

    Returns:
        ContextFact: .
    """
    payload = artifact.payload_json
    ts_code = payload.get("ts_code", "unknown")
    rank = payload.get("rank", "unknown")
    score = payload.get("composite_score", "unknown")
    return ContextFact(
        fact_id=f"fact_{artifact.artifact_id}",
        statement=f"Quant candidate {ts_code} has rank={rank}, composite_score={score}.",
        confidence=0.9,
        fact_type="quant_signal",
        subject_type="stock" if ts_code != "unknown" else "unknown",
        subject_id=str(ts_code) if ts_code != "unknown" else "",
        value_json={
            "rank": rank,
            "composite_score": score,
        },
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=artifact.evidence_refs,
        source_refs=artifact.source_refs,
        valid_at=artifact.created_at,
    )


def _backtest_result_fact(artifact: ContextArtifact) -> ContextFact:
    """Backtest result fact.

    Args:
        artifact: ContextArtifact: .

    Returns:
        ContextFact: .
    """
    payload = artifact.payload_json
    return ContextFact(
        fact_id=f"fact_{artifact.artifact_id}",
        statement=(
            "Backtest result: "
            f"annual_return={payload.get('annual_return', 'unknown')}, "
            f"max_drawdown={payload.get('max_drawdown', 'unknown')}."
        ),
        confidence=0.85,
        fact_type="metric",
        subject_type="run",
        subject_id=artifact.run_id,
        value_json={
            "annual_return": payload.get("annual_return"),
            "max_drawdown": payload.get("max_drawdown"),
        },
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=artifact.evidence_refs,
        source_refs=artifact.source_refs,
        valid_at=artifact.created_at,
    )


def _evidence_package_fact(artifact: ContextArtifact) -> ContextFact:
    """Evidence package fact.

    Args:
        artifact: ContextArtifact: .

    Returns:
        ContextFact: .
    """
    payload = artifact.payload_json
    return ContextFact(
        fact_id=f"fact_{artifact.artifact_id}",
        statement=(
            "Evidence package available: "
            f"claims={payload.get('claim_count', 'unknown')}, "
            f"status={payload.get('status', 'unknown')}."
        ),
        confidence=0.9,
        fact_type="evidence_claim",
        subject_type="run",
        subject_id=artifact.run_id,
        value_json={
            "claim_count": payload.get("claim_count"),
            "status": payload.get("status"),
        },
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=artifact.evidence_refs,
        source_refs=artifact.source_refs,
        valid_at=artifact.created_at,
    )


def _stock_analysis_fact(artifact: ContextArtifact) -> ContextFact:
    """Stock analysis fact.

    Args:
        artifact: ContextArtifact: .

    Returns:
        ContextFact: .
    """
    summary = str(artifact.payload_json.get("summary", "stock analysis artifact"))
    return ContextFact(
        fact_id=f"fact_{artifact.artifact_id}",
        statement=summary[:500],
        confidence=0.75 if artifact.evidence_refs else 0.45,
        fact_type="evidence_claim" if artifact.evidence_refs else "open_question",
        subject_type="stock" if artifact.payload_json.get("ts_code") else "unknown",
        subject_id=str(artifact.payload_json.get("ts_code") or ""),
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=artifact.evidence_refs,
        source_refs=artifact.source_refs,
        valid_at=artifact.created_at,
    )


def _data_status_fact(artifact: ContextArtifact) -> ContextFact:
    """Data status fact.

    Args:
        artifact: ContextArtifact: .

    Returns:
        ContextFact: .
    """
    status = artifact.payload_json.get("status", "unknown")
    return ContextFact(
        fact_id=f"fact_{artifact.artifact_id}",
        statement=f"Data readiness artifact status={status}.",
        confidence=0.9,
        fact_type="data_status",
        subject_type="dataset",
        subject_id=str(artifact.payload_json.get("dataset") or artifact.artifact_id),
        value_json={"status": status},
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=artifact.evidence_refs,
        source_refs=artifact.source_refs,
        valid_at=artifact.created_at,
    )


def _generic_fact(artifact: ContextArtifact) -> ContextFact:
    """Generic fact.

    Args:
        artifact: ContextArtifact: .

    Returns:
        ContextFact: .
    """
    return ContextFact(
        fact_id=f"fact_{artifact.artifact_id}",
        statement=(
            f"{artifact.artifact_type} produced by {artifact.producer_agent}; "
            f"payload_hash={artifact.payload_hash}"
        ),
        confidence=0.6,
        fact_type="metric",
        subject_type="run",
        subject_id=artifact.run_id,
        artifact_refs=(artifact.artifact_id,),
        evidence_refs=artifact.evidence_refs,
        source_refs=artifact.source_refs,
        valid_at=artifact.created_at,
    )
