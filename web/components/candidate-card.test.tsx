/**
 * @fileoverview Unit tests for the CandidateCard component.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CandidateCard } from "./candidate-card";
import type { ResearchCandidateCard } from "@/lib/api";

/** Mock research candidate used in CandidateCard tests. */
const card: ResearchCandidateCard = {
  item_id: "di_1",
  run_id: "dr_1",
  symbol: "000001.SZ",
  signal_type: "research_candidate",
  confidence: 0.84,
  statement: "经营现金流改善，估值仍有安全边际",
  current_price: null,
  quantitative_rank: null,
  research_status: "published",
  position_review_status: null,
  valuation_range: [10.8, 13.2],
  margin_of_safety: null,
  value_trap_score: 0.28,
  event_window: null,
  catalysts: [],
  counter_arguments: ["行业需求恢复不及预期"],
  evidence_summary: { count: 1, levels: { unknown: 1 } },
  watch_conditions: ["证据和估值继续满足策略约束"],
  invalidation_conditions: [],
  strategy_version: "sv_demo",
  disclaimer: "本系统输出研究分析，不构成买卖指令。",
};

/** Tests for CandidateCard rendering behavior. */
describe("CandidateCard", () => {
  it("renders candidate signal, evidence, valuation, counter argument and disclaimer", () => {
    render(<CandidateCard card={card} />);

    expect(screen.getByRole("link", { name: "000001.SZ" })).toHaveAttribute(
      "href",
      "/research/items/di_1",
    );
    expect(screen.getByText("经营现金流改善，估值仍有安全边际")).toBeInTheDocument();
    expect(screen.getByText("证据 1")).toBeInTheDocument();
    expect(screen.getByText("¥10.80 – ¥13.20")).toBeInTheDocument();
    expect(screen.getByText("行业需求恢复不及预期")).toBeInTheDocument();
    expect(screen.getByText(/不构成买卖指令/)).toBeInTheDocument();
  });
});
