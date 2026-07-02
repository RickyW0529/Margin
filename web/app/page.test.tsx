/**
 * @fileoverview Tests for the home page.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  askReadOnlyCopilot,
  fetchResearchCandidates,
} from "@/lib/api";

import HomePage from "./page";

vi.mock("@/lib/api", () => ({
  askReadOnlyCopilot: vi.fn(),
  fetchResearchCandidates: vi.fn(),
  saveProviderSecret: vi.fn(),
  testProviderConfig: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((path: string) => {
    throw new Error(`unexpected redirect to ${path}`);
  }),
}));

describe("HomePage", () => {
  beforeEach(() => {
    vi.mocked(askReadOnlyCopilot).mockResolvedValue({
      answer: "今日推荐关注 000001。",
      references: [{ api: "GET /api/v1/research", scope_version_id: "scope-current" }],
    });
    vi.mocked(fetchResearchCandidates).mockResolvedValue({
      as_of: "2026-06-23T08:30:00Z",
      facets: {
        current_review_outcome: { update_assessment: 1 },
        risk_flags: { high_debt: 1 },
      },
      items: [
        {
          assessment_freshness: "fresh",
          confidence: 0.82,
          current_review_outcome: "update_assessment",
          data_status: "complete",
          discount_rate: 0.18,
          effective_assessment_id: "assess-1",
          final_score: 86,
          item_id: "item-1",
          last_checked_at: "2026-06-23T08:30:00Z",
          name: "平安银行",
          research_guardrail: "allow_research",
          review_required: true,
          risk_flags: ["high_debt"],
          scope_version_id: "scope-current",
          screening_status: "pass",
          security_id: "sec-1",
          stale_reason: null,
          symbol: "000001",
        },
      ],
      page_info: {
        has_next_page: false,
        next_cursor: null,
        page_size: 8,
      },
      scope_version_id: "scope-current",
    });
  });

  it("renders a focused question-first home page", async () => {
    render(await HomePage());

    expect(fetchResearchCandidates).toHaveBeenCalledWith(
      {
        limit: 3,
        scope_version_id: "scope-current",
        universe: "ALL_A",
      },
    );
    expect(screen.getByRole("heading", { name: "今天想研究什么？" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "今日推荐股票是什么？" })).toBeInTheDocument();
    expect(screen.getByText("今日推荐预览")).toBeInTheDocument();
    expect(screen.getByText("平安银行")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /平安银行/ })).toHaveAttribute(
      "href",
      "/dashboard?item_id=item-1#recommendation-detail",
    );
    expect(screen.queryByText(/组合|持仓/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Provider|Scope|BFF|fail-closed/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开今日推荐" })).toHaveAttribute("href", "/dashboard");
  });
});
