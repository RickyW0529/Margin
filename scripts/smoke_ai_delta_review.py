#!/usr/bin/env python3
"""Token-safe smoke for the v0.2 AI delta-review graph."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from typing import Any

from margin.research.llm import LLMProvider
from margin.research.service import (
    MemoryResearchContextRepository,
    ResearchContextSnapshot,
    ResearchService,
)


def _build_real_llm_decision_prompt(state: Any, evidence_ids: list[str]) -> str:
    """Render a deterministic decision-contract prompt for the real-LLM smoke.

    The prompt must echo the change set verbatim so the LLM cannot drift from
    the recorded delta and must call ``update_assessment`` when any change is
    flagged. Evidence IDs are pinned as the only admissible references.
    """
    change_set = getattr(state, "change_set", {}) or {}
    change_lines = "\n".join(
        f"{key}={value}" for key, value in change_set.items()
    )
    evidence_lines = "\n".join(f"- {eid}" for eid in evidence_ids)
    return (
        "Return JSON only.\n"
        "This is a token-safe smoke contract, not an investment conclusion.\n"
        "Do not output BUY, SELL, target price, position size, or trading "
        "instructions.\n"
        "Deterministic decision contract for v0.2 delta review.\n"
        f"Security: {getattr(state, 'security_id', 'unknown')}\n"
        f"Decision at: {getattr(state, 'decision_at', 'unknown')}\n"
        f"Review mode: {getattr(state, 'review_mode', 'delta_review')}\n"
        "Changes:\n"
        f"{change_lines}\n"
        "Admissible evidence:\n"
        f"{evidence_lines}\n"
        "Rule: when any change set flag is True, the outcome must be "
        "update_assessment; otherwise the outcome must be abstain.\n"
        "The evidence_ids field must exactly match the admissible evidence "
        "list, with no additions."
    )


def main() -> int:
    """Run one smoke mode and return a process exit code."""
    args = _parse_args()
    if args.require_real_llm and args.mode != "carry" and not _llm_configured():
        _print_result(
            mode=args.mode,
            status="blocked",
            graph_run_id="none",
            outcome="none",
            llm_calls=0,
            tool_calls=0,
            evidence_packages=0,
            external_blocker="missing_llm_config",
        )
        return 2

    repository = MemoryResearchContextRepository()
    context = _context_for_mode(args.mode)
    repository.add(context)
    real_decision = (
        _RealLLMDecisionHandler()
        if args.require_real_llm and args.mode != "carry"
        else None
    )
    service = ResearchService(
        context_repository=repository,
        v02_decision_handler=real_decision,
    )
    try:
        result = service.run_delta_review(context.context_snapshot_id)
    except Exception:  # noqa: BLE001 - token-safe smoke omits internal details
        _print_result(
            mode=args.mode,
            status="failed",
            graph_run_id="none",
            outcome="none",
            llm_calls=0,
            tool_calls=0,
            evidence_packages=0,
        )
        return 3

    status = "ok"
    exit_code = 0
    if real_decision is not None and (
        not real_decision.success
        or result.current_review_outcome.value == "abstain"
    ):
        status = "failed"
        exit_code = 3

    _print_result(
        mode=args.mode,
        status=status,
        graph_run_id=result.graph_run_id,
        outcome=result.current_review_outcome.value,
        llm_calls=result.llm_call_count,
        tool_calls=result.tool_call_count,
        evidence_packages=len(result.evidence_package_ids),
    )
    return exit_code


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the AI delta-review smoke."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("carry", "delta", "full"),
        required=True,
    )
    parser.add_argument(
        "--require-real-llm",
        action="store_true",
        help="Use the configured real LLM provider for the decision node.",
    )
    return parser.parse_args()


def _context_for_mode(mode: str) -> ResearchContextSnapshot:
    """Build a deterministic research context snapshot for the given smoke mode."""
    decision_at = datetime(2026, 6, 23, tzinfo=UTC)
    base_payload = {
        "quant_input_valid": True,
        "pit_valid": True,
        "news_target_complete": True,
        "provider_budget_available": True,
        "review_due": False,
        "material_quant_change": False,
        "material_valuation_change": False,
        "material_news_change": False,
        "assumption_change": False,
        "ambiguous_change": False,
        "evidence_package_id": f"pkg-smoke-{mode}",
        "evidence_ids": [f"ev-smoke-{mode}"],
    }
    if mode == "carry":
        payload = {
            **base_payload,
            "previous_effective_assessment_id": "assess-smoke-old",
        }
    elif mode == "delta":
        payload = {
            **base_payload,
            "previous_effective_assessment_id": "assess-smoke-old",
            "material_news_change": True,
        }
    else:
        payload = base_payload

    return ResearchContextSnapshot(
        context_snapshot_id=f"ctx-smoke-{mode}",
        security_id="000001.SZ",
        scope_version_id="scope-smoke",
        decision_at=decision_at,
        payload_hash=f"sha256:ctx-smoke-{mode}",
        payload=payload,
        created_at=decision_at,
    )


class _RealLLMDecisionHandler:
    """Use a configured OpenAI-compatible LLM for the decision node."""

    def __init__(self) -> None:
        """Initialize the real-LLM decision handler with a fresh provider."""
        self._provider = LLMProvider(name="smoke_llm", timeout=30.0)
        self.success = False
        self.call_count = 0

    def __call__(self, state) -> dict[str, Any]:
        """Invoke the real LLM and return a structured decision output.

        Args:
            state: Current research graph state carrying the change set and
                evidence package IDs.

        Returns:
            dict[str, Any]: Decision output with outcome, confidence,
                evidence IDs and changed assumptions.

        Raises:
            RuntimeError: When the LLM provider returns a failed response.
        """
        self.call_count += 1
        evidence_ids = _evidence_ids_from_state(state)
        prompt = _build_real_llm_decision_prompt(state, evidence_ids)
        response = self._provider.complete(
            prompt,
            response_schema=_DECISION_SCHEMA,
            temperature=0.0,
        )
        if not response.success:
            raise RuntimeError("real_llm_decision_failed")
        output = dict(response.output)
        output["llm_call_ids"] = [f"llm-real-decision-{self.call_count}"]
        self.success = True
        return output


def _evidence_ids_from_state(state) -> list[str]:
    """Extract evidence IDs from the state's evidence packages or IDs."""
    evidence_ids: list[str] = []
    for package in state.node_outputs.get("evidence_packages", {}).values():
        summary = package.get("summary", {}) if isinstance(package, dict) else {}
        evidence_ids.extend(str(value) for value in summary.get("evidence_ids", ()))
    return evidence_ids or [str(value) for value in state.evidence_package_ids]


def _llm_configured() -> bool:
    """Return True when the required LLM env vars are set."""
    return bool(os.getenv("MARGIN_LLM_API_KEY") and os.getenv("MARGIN_LLM_BASE_URL"))


def _print_result(
    *,
    mode: str,
    status: str,
    graph_run_id: str,
    outcome: str,
    llm_calls: int,
    tool_calls: int,
    evidence_packages: int,
    external_blocker: str | None = None,
) -> None:
    """Print the smoke result as a single key=value line."""
    parts = [
        f"mode={mode}",
        f"status={status}",
        f"graph_run_id={graph_run_id}",
        f"outcome={outcome}",
        f"llm_calls={llm_calls}",
        f"tool_calls={tool_calls}",
        f"evidence_packages={evidence_packages}",
    ]
    if external_blocker is not None:
        parts.append(f"external_blocker={external_blocker}")
    print(" ".join(parts))


_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {
            "type": "string",
            "enum": [
                "update_assessment",
                "downgrade_confidence",
                "invalidate",
                "abstain",
            ],
        },
        "confidence": {"type": "number"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "changed_assumptions": {
            "type": "array",
            "items": {"type": "object"},
        },
    },
    "required": ["outcome", "confidence", "evidence_ids", "changed_assumptions"],
}


if __name__ == "__main__":
    raise SystemExit(main())
