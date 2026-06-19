"""Immutable research snapshot builder."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from margin.news.models import utc_now
from margin.research.models import (
    AgentTrace,
    ResearchSignal,
    ResearchSnapshot,
    VersionRef,
    WorkflowState,
)


class ResearchSnapshotBuilder:
    """Build an immutable research audit snapshot."""

    def __init__(self) -> None:
        self._run_id: str = ""
        self._state: WorkflowState = WorkflowState.INITIALIZED
        self._decision_at: datetime = utc_now()
        self._symbols: list[str] = []
        self._strategy_version: str = ""
        self._prompt_version: str = ""
        self._tool_versions: dict[str, str] = {}
        self._model_versions: dict[str, str] = {}
        self._evidence_ids: list[str] = []
        self._claim_ids: list[str] = []
        self._signals: list[ResearchSignal] = []
        self._traces: list[AgentTrace] = []
        self._prior_outputs: dict[str, Any] = {}
        self._tool_calls: list[dict[str, Any]] = []
        self._tool_call_ids: list[str] = []
        self._error: str | None = None

    def for_run(self, run_id: str) -> ResearchSnapshotBuilder:
        self._run_id = run_id
        return self

    def with_state(self, state: WorkflowState) -> ResearchSnapshotBuilder:
        self._state = state
        return self

    def with_decision_at(self, decision_at: datetime) -> ResearchSnapshotBuilder:
        self._decision_at = decision_at
        return self

    def with_symbols(self, symbols: list[str]) -> ResearchSnapshotBuilder:
        self._symbols = symbols
        return self

    def with_strategy_version(self, version: str) -> ResearchSnapshotBuilder:
        self._strategy_version = version
        return self

    def with_prompt_version(self, version: str) -> ResearchSnapshotBuilder:
        self._prompt_version = version
        return self

    def with_tool_versions(self, versions: dict[str, str]) -> ResearchSnapshotBuilder:
        self._tool_versions = versions
        return self

    def with_model_versions(self, versions: dict[str, str]) -> ResearchSnapshotBuilder:
        self._model_versions = versions
        return self

    def with_evidence_ids(self, ids: list[str]) -> ResearchSnapshotBuilder:
        self._evidence_ids = ids
        return self

    def with_claim_ids(self, ids: list[str]) -> ResearchSnapshotBuilder:
        self._claim_ids = ids
        return self

    def with_signals(self, signals: list[ResearchSignal]) -> ResearchSnapshotBuilder:
        self._signals = signals
        return self

    def with_traces(self, traces: list[AgentTrace]) -> ResearchSnapshotBuilder:
        self._traces = traces
        return self

    def with_prior_outputs(self, outputs: dict[str, Any]) -> ResearchSnapshotBuilder:
        self._prior_outputs = outputs
        return self

    def with_tool_call_ids(self, call_ids: list[str]) -> ResearchSnapshotBuilder:
        self._tool_call_ids = call_ids
        return self

    def with_tool_calls(
        self,
        tool_calls: list[dict[str, Any]],
    ) -> ResearchSnapshotBuilder:
        self._tool_calls = tool_calls
        return self

    def with_error(self, error: str | None) -> ResearchSnapshotBuilder:
        self._error = error
        return self

    @staticmethod
    def _hash(data: Any) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def build(self) -> ResearchSnapshot:
        input_payload = {
            "run_id": self._run_id,
            "symbols": self._symbols,
            "decision_at": self._decision_at,
            "strategy_version": self._strategy_version,
            "prompt_version": self._prompt_version,
            "tool_versions": self._tool_versions,
            "model_versions": self._model_versions,
        }
        output_payload = {
            "state": self._state,
            "prior_outputs": self._prior_outputs,
            "signals": [s.model_dump() for s in self._signals],
            "evidence_ids": self._evidence_ids,
            "claim_ids": self._claim_ids,
            "traces": [t.model_dump() for t in self._traces],
            "tool_call_ids": self._tool_call_ids,
            "tool_calls": self._tool_calls,
            "error": self._error,
        }
        agent_outputs_json = json.dumps(
            self._prior_outputs,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        tool_calls_json = json.dumps(
            self._tool_calls,
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        return ResearchSnapshot(
            run_id=self._run_id,
            workflow_state=self._state,
            decision_at=self._decision_at,
            symbols=tuple(self._symbols),
            strategy_version=self._strategy_version,
            prompt_version=self._prompt_version,
            tool_versions=tuple(
                VersionRef(name=name, version=version)
                for name, version in sorted(self._tool_versions.items())
            ),
            model_versions=tuple(
                VersionRef(name=name, version=version)
                for name, version in sorted(self._model_versions.items())
            ),
            evidence_ids=tuple(self._evidence_ids),
            claim_ids=tuple(self._claim_ids),
            signals=tuple(self._signals),
            input_hash=self._hash(input_payload),
            output_hash=self._hash(output_payload),
            traces=tuple(self._traces),
            tool_call_ids=tuple(self._tool_call_ids),
            agent_outputs_json=agent_outputs_json,
            tool_calls_json=tool_calls_json,
            error=self._error,
        )
