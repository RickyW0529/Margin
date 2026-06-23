/**
 * @fileoverview Tests for the home page.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchProviderConfigs,
  fetchProviderStatus,
  fetchResearchCandidates,
} from "@/lib/api";

import HomePage from "./page";

vi.mock("@/lib/api", () => ({
  configureLocalAdminSession: vi.fn(),
  fetchProviderConfigs: vi.fn(),
  fetchProviderStatus: vi.fn(),
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
    vi.mocked(fetchProviderStatus).mockResolvedValue([
      { provider: "postgres", status: "ready", message: "connected" },
    ]);
    vi.mocked(fetchProviderConfigs).mockResolvedValue([]);
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

  it("renders a real API-backed product home instead of hard-redirecting to demo", async () => {
    render(await HomePage());

    expect(fetchResearchCandidates).toHaveBeenCalledWith(
      expect.objectContaining({
        limit: 8,
        scope_version_id: "scope-current",
        universe: "ALL_A",
      }),
    );
    expect(fetchProviderStatus).toHaveBeenCalled();
    expect(fetchProviderConfigs).toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Margin 工作台" })).toBeInTheDocument();
    expect(screen.queryByText(/组合|持仓/)).not.toBeInTheDocument();
    expect(screen.getByText("今日候选")).toBeInTheDocument();
    expect(screen.getByText("v0.2 candidate BFF")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "进入研究面板" })).toHaveAttribute(
      "href",
      "/research",
    );
  });
});
