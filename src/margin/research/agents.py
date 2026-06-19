"""Agent framework and the 12 research agent roles."""

from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from margin.evidence.models import (
    Claim,
    ClaimType,
    Evidence,
    FactOrInference,
    make_claim,
)
from margin.evidence.validator import CitationValidator, ValidationStatus
from margin.research.llm import (
    LLMProvider,
    LLMResult,
    ModelRouter,
    StructuredOutputGuardrail,
    TaskType,
)
from margin.research.tools import ToolRegistry, ToolResult
from margin.vector.models import Chunk


@dataclass
class AgentContext:
    """Shared context passed to every agent."""

    symbol: str
    decision_at: datetime
    tool_registry: ToolRegistry
    llm_provider: LLMProvider | None = None
    model_router: ModelRouter | None = None
    portfolio_id: str | None = None
    strategy_config: dict[str, Any] = field(default_factory=dict)
    prior_outputs: dict[str, Any] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)
    evidences: dict[str, Evidence] = field(default_factory=dict)
    snapshot_resolver: Any | None = None
    trace_id: str = ""


@dataclass(frozen=True)
class AgentOutput:
    """Structured result from a single agent."""

    agent_node: str
    success: bool
    data: dict[str, Any]
    error: str | None = None
    trace_id: str = ""
    model_version: str = ""
    latency_ms: float = 0.0
    tool_calls: list[ToolResult] = field(default_factory=list)
    input_hash: str = ""
    output_hash: str = ""
    tool_call_ids: tuple[str, ...] = ()


class Agent(ABC):
    """Base class for a research agent role."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self._llm = llm_provider

    @property
    @abstractmethod
    def node_name(self) -> str:
        """Return the agent node name."""

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}

    def _hash(self, data: Any) -> str:
        return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()

    def _call_llm(
        self,
        context: AgentContext,
        prompt: str,
        task: TaskType,
        provider: LLMProvider | None = None,
        schema: dict[str, Any] | None = None,
    ) -> LLMResult:
        schema = schema or self.output_schema
        if context.model_router is not None:
            result = context.model_router.complete(
                task,
                prompt,
                response_schema=schema,
                trace_id=context.trace_id,
            )
        else:
            llm = provider or self._llm or context.llm_provider
            if llm is None:
                return LLMResult(
                    output={},
                    model="none",
                    success=False,
                    latency_ms=0.0,
                    error="no LLM provider configured",
                )
            result = llm.complete(prompt, response_schema=schema)
        if result.success and schema:
            guardrail = StructuredOutputGuardrail(schema)
            ok, msg = guardrail.validate(result.output)
            if not ok:
                return LLMResult(
                    output=result.output,
                    model=result.model,
                    success=False,
                    latency_ms=result.latency_ms,
                    error=f"guardrail: {msg}",
                    raw_response=result.raw_response,
                )
        return result

    def _call_tool(self, context: AgentContext, name: str, params: dict[str, Any]) -> ToolResult:
        return context.tool_registry.call(name, params, trace_id=context.trace_id)

    @abstractmethod
    def run(self, context: AgentContext) -> AgentOutput:
        """Run the agent against the given context."""

    def _make_output(
        self,
        context: AgentContext,
        success: bool,
        data: dict[str, Any],
        error: str | None = None,
        llm_result: LLMResult | None = None,
        tool_calls: list[ToolResult] | None = None,
    ) -> AgentOutput:
        input_payload = {
            "symbol": context.symbol,
            "decision_at": context.decision_at,
            "strategy_config": context.strategy_config,
            "prior_outputs": context.prior_outputs,
            "claim_ids": [claim.claim_id for claim in context.claims],
            "evidence_ids": sorted(context.evidences),
        }
        call_ids = tuple(
            record.call_id
            for record in context.tool_registry.audit_records
            if record.trace_id == context.trace_id
        )
        return AgentOutput(
            agent_node=self.node_name,
            success=success,
            data=data,
            error=error,
            trace_id=context.trace_id or f"trc_{uuid.uuid4().hex[:12]}",
            model_version=(llm_result.model if llm_result else "rule"),
            latency_ms=(llm_result.latency_ms if llm_result else 0.0),
            tool_calls=tool_calls or [],
            input_hash=self._hash(input_payload),
            output_hash=self._hash(data),
            tool_call_ids=call_ids,
        )


class RuleAgent(Agent):
    """Agent that uses only rules/tools without LLM."""

    def run(self, context: AgentContext) -> AgentOutput:
        try:
            data = self._run_rule(context)
            return self._make_output(context, True, data)
        except Exception as exc:
            return self._make_output(context, False, {}, error=f"{type(exc).__name__}: {exc}")

    @abstractmethod
    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        """Implement the rule-based logic."""


class UniverseFilterAgent(RuleAgent):
    """Agent #1: filter universe by configured symbols and basic rules."""

    @property
    def node_name(self) -> str:
        return "universe_filter"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        symbols = context.strategy_config.get("universe", [context.symbol])
        result = {"symbols": symbols, "filtered": [], "degraded": []}
        for symbol in symbols:
            md = self._call_tool(context, "market_data", {"symbol": symbol})
            if md.success:
                result["filtered"].append(symbol)
                if isinstance(md.data, dict) and md.data.get("degraded"):
                    result["degraded"].append(symbol)
            else:
                raise RuntimeError(md.error or "market data lookup failed")
        if not result["filtered"]:
            raise RuntimeError("universe filter produced no verified symbols")
        return result


class QuantResearchAgent(RuleAgent):
    """Agent #2: compute factor scores and basic ranking."""

    @property
    def node_name(self) -> str:
        return "quant_research"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        symbols = context.prior_outputs.get("universe_filter", {}).get(
            "filtered", [context.symbol]
        )
        factor_result = self._call_tool(context, "factor", {"symbols": symbols})
        if not factor_result.success:
            raise RuntimeError(factor_result.error or "factor computation failed")
        scores = factor_result.data if isinstance(factor_result.data, dict) else {}
        if not scores:
            raise RuntimeError("factor computation returned no scores")
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return {
            "scores": scores,
            "ranked": [s for s, _ in ranked],
            "top_symbol": ranked[0][0] if ranked else context.symbol,
        }


class WebSearchAgent(Agent):
    """Agent #3: discover news/announcement/web sources."""

    @property
    def node_name(self) -> str:
        return "websearch"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}},
                "results": {"type": "array"},
            },
            "required": ["queries"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        symbol = context.symbol
        prompt = (
            f"Generate 1-3 web search queries in Chinese for recent news and announcements "
            f"about stock {symbol} as of {context.decision_at.date()}. "
            f"Respond with JSON: {{\"queries\": [\"...\"]}}."
        )
        result = self._call_llm(context, prompt, TaskType.WEBSEARCH)
        if not result.success:
            return self._make_output(context, False, {"queries": []}, error=result.error)

        queries = result.output.get("queries", [f"{symbol} 公告"])
        tool_results: list[ToolResult] = []
        all_results: list[dict[str, Any]] = []
        for query in queries[:3]:
            tr = self._call_tool(context, "websearch", {"query": query})
            tool_results.append(tr)
            if tr.success and isinstance(tr.data, dict):
                all_results.extend(tr.data.get("results", []))

        return self._make_output(
            context,
            True,
            {"queries": queries, "results": all_results},
            llm_result=result,
            tool_calls=tool_results,
        )


class DocumentCollectorAgent(RuleAgent):
    """Agent #4: collect/snapshot source documents and record hashes."""

    @property
    def node_name(self) -> str:
        return "document_collector"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        results = context.prior_outputs.get("websearch", {}).get("results", [])
        collected: list[dict[str, Any]] = []
        for item in results:
            result = self._call_tool(context, "document_collector", {"source": item})
            if not result.success:
                raise RuntimeError(result.error or "document collection failed")
            if isinstance(result.data, dict):
                required = {"url", "content_hash", "snapshot_id", "snapshot_hash"}
                missing = sorted(required - result.data.keys())
                if missing:
                    raise RuntimeError(
                        "document collector missing fields: " + ", ".join(missing)
                    )
                collected.append(result.data)
        return {"collected": collected, "count": len(collected)}


class TextSummaryAgent(Agent):
    """Agent #5: structured summary of documents."""

    @property
    def node_name(self) -> str:
        return "text_summary"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "summaries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_url": {"type": "string"},
                            "summary": {"type": "string"},
                            "key_points": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["source_url", "summary"],
                    },
                }
            },
            "required": ["summaries"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        collected = context.prior_outputs.get("document_collector", {}).get("collected", [])
        if not collected:
            return self._make_output(context, True, {"summaries": []})

        prompt = (
            f"Summarize the following sources for {context.symbol}. "
            f"Respond with JSON matching the schema with 'summaries'. "
            f"Sources: {json.dumps(collected)}"
        )
        result = self._call_llm(context, prompt, TaskType.SUMMARY)
        if not result.success:
            return self._make_output(context, False, {"summaries": []}, error=result.error)
        return self._make_output(context, True, result.output, llm_result=result)


class EvidenceResearchAgent(Agent):
    """Agent #6: retrieve and organize evidence claims."""

    @property
    def node_name(self) -> str:
        return "evidence_research"

    def run(self, context: AgentContext) -> AgentOutput:
        tr = self._call_tool(
            context,
            "retrieval",
            {
                "query": f"{context.symbol} 经营",
                "symbol": context.symbol,
                "decision_at": context.decision_at,
            },
        )
        if not tr.success:
            return self._make_output(
                context, False, {"claims": []}, error=tr.error, tool_calls=[tr]
            )

        data = tr.data or []
        claims: list[Claim] = []
        evidences: dict[str, Evidence] = {}
        for item in data:
            chunk_value = item.chunk if hasattr(item, "chunk") else item.get("chunk")
            try:
                chunk = (
                    chunk_value
                    if isinstance(chunk_value, Chunk)
                    else Chunk.model_validate(chunk_value)
                )
            except Exception:
                continue
            evidence = Evidence.from_chunk(chunk)
            claim = make_claim(
                statement=chunk.content[:500],
                claim_type=ClaimType.CUSTOM,
                fact_or_inference=FactOrInference.FACT,
                evidence_ids=[evidence.evidence_id],
                confidence=0.5,
                symbol=context.symbol,
                effective_at=context.decision_at,
            )
            evidences[evidence.evidence_id] = evidence
            claims.append(claim)

        if context.evidences:
            evidences.update(context.evidences)
        if context.claims:
            claims.extend(context.claims)
        context.evidences.update(evidences)
        context.claims.extend(
            claim for claim in claims if claim.claim_id not in {c.claim_id for c in context.claims}
        )
        if not evidences or not claims:
            return self._make_output(
                context,
                False,
                {"retrieval_results": data, "evidence_ids": [], "claim_ids": []},
                error="retrieval returned no valid Evidence/Claim records",
                tool_calls=[tr],
            )
        return self._make_output(
            context,
            True,
            {
                "retrieval_results": data,
                "count": len(data),
                "evidence_ids": sorted(evidences),
                "claim_ids": [claim.claim_id for claim in claims],
            },
            tool_calls=[tr],
        )


class ValuationToolAgent(RuleAgent):
    """Agent #7: numeric valuation using the valuation tool."""

    @property
    def node_name(self) -> str:
        return "valuation_tool"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        eps = context.strategy_config.get("eps", 1.0)
        pe = context.strategy_config.get("pe", 10.0)
        tr = self._call_tool(context, "valuation", {"method": "pe", "eps": eps, "pe": pe})
        if not tr.success:
            return {"value": None, "error": tr.error}
        return {"value": tr.data.get("value") if isinstance(tr.data, dict) else None}


class RiskReviewAgent(Agent):
    """Agent #8: output risk score, not calibrated probability."""

    @property
    def node_name(self) -> str:
        return "risk_review"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "risk_score": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "risk_factors": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["risk_score", "risk_factors"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        prompt = (
            f"Review risks for {context.symbol} based on current evidence. "
            f"Output JSON with 'risk_score' (0-1) and 'risk_factors' (list of strings). "
            f"Do not output probability of gain/loss."
        )
        result = self._call_llm(context, prompt, TaskType.RISK)
        if not result.success:
            return self._make_output(
                context,
                False,
                {"risk_score": 0.5, "risk_factors": []},
                error=result.error,
            )
        return self._make_output(context, True, result.output, llm_result=result)


class ReflectCounterArgumentAgent(Agent):
    """Agent #9: review counter-evidence, conflicts, and unknowns."""

    @property
    def node_name(self) -> str:
        return "reflect_counter_argument"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "counter_arguments": {"type": "array", "items": {"type": "string"}},
                "unknowns": {"type": "array", "items": {"type": "string"}},
                "conflict_flags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["counter_arguments", "unknowns"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        prompt = (
            f"Provide counter-arguments and unknowns for {context.symbol}. "
            f"Output JSON with 'counter_arguments', 'unknowns', and optional 'conflict_flags'."
        )
        result = self._call_llm(context, prompt, TaskType.REFLECT)
        if not result.success:
            return self._make_output(
                context,
                False,
                {"counter_arguments": [], "unknowns": []},
                error=result.error,
            )
        return self._make_output(context, True, result.output, llm_result=result)


class PortfolioConstraintAgent(RuleAgent):
    """Agent #10: check portfolio exposure constraints."""

    @property
    def node_name(self) -> str:
        return "portfolio_constraint"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        max_weight = context.strategy_config.get("max_position_weight", 0.1)
        current_weight = context.strategy_config.get("current_weight", 0.0)
        tr = self._call_tool(
            context,
            "portfolio",
            {
                "symbol": context.symbol,
                "max_weight": max_weight,
                "current_weight": current_weight,
            },
        )
        if not tr.success:
            return {"violations": [tr.error or "portfolio check failed"], "passed": False}
        data = tr.data or {}
        violations = data.get("violations", [])
        return {"violations": violations, "passed": len(violations) == 0}


class ResearchSignalComposer(Agent):
    """Agent #11: compose final research signal."""

    @property
    def node_name(self) -> str:
        return "signal_composer"

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "signal_type": {
                    "type": "string",
                    "enum": ["research_candidate", "watch", "abstained"],
                },
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "statement": {"type": "string"},
                "evidence_refs": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["signal_type", "confidence", "statement"],
        }

    def run(self, context: AgentContext) -> AgentOutput:
        risk = context.prior_outputs.get("risk_review", {}).get("risk_score", 0.5)
        reflect = context.prior_outputs.get("reflect_counter_argument", {})
        constraints = context.prior_outputs.get("portfolio_constraint", {})
        evidence_ids = context.prior_outputs.get("evidence_research", {}).get(
            "evidence_ids", []
        )
        degraded_market = context.prior_outputs.get("universe_filter", {}).get(
            "degraded",
            [],
        )

        if degraded_market:
            return self._make_output(
                context,
                True,
                {
                    "signal_type": "abstained",
                    "confidence": 0.0,
                    "statement": "Market data degraded; high-confidence signal withheld",
                    "evidence_refs": evidence_ids,
                },
            )

        if not constraints.get("passed", True):
            return self._make_output(
                context,
                True,
                {
                    "signal_type": "abstained",
                    "confidence": 0.0,
                    "statement": "Portfolio constraint violation",
                    "evidence_refs": [],
                },
            )

        if risk > 0.7 or reflect.get("conflict_flags"):
            return self._make_output(
                context,
                True,
                {
                    "signal_type": "watch",
                    "confidence": round(1 - risk, 2),
                    "statement": "High risk or conflicts flagged; watch only",
                    "evidence_refs": evidence_ids,
                },
            )

        return self._make_output(
            context,
            True,
            {
                "signal_type": "research_candidate",
                "confidence": round(max(0.0, 0.8 - risk), 2),
                "statement": f"{context.symbol} passes initial research screen",
                "evidence_refs": evidence_ids,
            },
        )


class CitationValidatorAgent(RuleAgent):
    """Agent #12: validate evidence references, source levels, and timing."""

    @property
    def node_name(self) -> str:
        return "citation_validator"

    def _run_rule(self, context: AgentContext) -> dict[str, Any]:
        signal = context.prior_outputs.get("signal_composer", {})
        refs = signal.get("evidence_refs", [])
        if not refs:
            return {"valid": False, "reason": "no evidence references", "failed_refs": []}
        missing = [ref for ref in refs if ref not in context.evidences]
        if missing:
            return {
                "valid": False,
                "reason": f"Evidence not found: {', '.join(missing)}",
                "failed_refs": missing,
            }
        if not context.claims:
            return {
                "valid": False,
                "reason": "no Claims available for citation validation",
                "failed_refs": list(refs),
            }
        claimed_refs = {
            evidence_id
            for claim in context.claims
            for evidence_id in claim.evidence_ids
        }
        unclaimed = [ref for ref in refs if ref not in claimed_refs]
        if unclaimed:
            return {
                "valid": False,
                "reason": f"Evidence not referenced by a Claim: {', '.join(unclaimed)}",
                "failed_refs": unclaimed,
            }

        report = CitationValidator(
            snapshot_resolver=context.snapshot_resolver
        ).validate_batch(
            context.claims,
            context.evidences,
            context.decision_at,
        )
        failed = [
            result.claim_id
            for result in report.results
            if result.status != ValidationStatus.PASS
        ]
        if failed:
            reasons = [
                result.reason
                for result in report.results
                if result.status != ValidationStatus.PASS
            ]
            return {
                "valid": False,
                "reason": "; ".join(reasons),
                "failed_refs": failed,
                "requires_counter_review": any(
                    result.requires_counter_review for result in report.results
                ),
            }
        return {
            "valid": True,
            "reason": "all Claims and Evidence passed citation validation",
            "failed_refs": [],
            "requires_counter_review": any(
                result.requires_counter_review for result in report.results
            ),
            "capped_confidence": min(
                (result.capped_confidence for result in report.results),
                default=0.0,
            ),
        }
