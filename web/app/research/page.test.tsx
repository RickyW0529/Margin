/**
 * @fileoverview Tests for the research dashboard page.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  askReadOnlyCopilot,
  fetchProviderStatus,
  fetchResearchCandidates,
  startValuationDiscoveryRefresh,
} from "@/lib/api";

import ResearchDashboardPage from "./page";

vi.mock("@/lib/api", () => ({
  askReadOnlyCopilot: vi.fn(),
  fetchProviderStatus: vi.fn(),
  fetchResearchCandidates: vi.fn(),
  startValuationDiscoveryRefresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

describe("ResearchDashboardPage", () => {
  beforeEach(() => {
    vi.mocked(askReadOnlyCopilot).mockResolvedValue({
      answer: "",
      references: [],
    });
    vi.mocked(startValuationDiscoveryRefresh).mockResolvedValue({
      http_status: 202,
      run_id: "vdr-1",
      status: "accepted",
    });
    vi.mocked(fetchResearchCandidates).mockResolvedValue({
      items: [
        {
          assessment_freshness: "fresh",
          confidence: 0.72,
          current_review_outcome: "update_assessment",
          data_status: "complete",
          discount_rate: 0.22,
          effective_assessment_id: "assess-1",
          final_score: 81,
          item_id: "item-1",
          last_checked_at: "2026-06-22T00:00:00Z",
          name: "平安银行",
          research_guardrail: "allow_research",
          review_required: false,
          risk_flags: [],
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
        page_size: 50,
      },
      facets: {},
      as_of: "2026-06-22T00:00:00Z",
      scope_version_id: "scope-current",
    });
    vi.mocked(fetchProviderStatus).mockResolvedValue([
      {
        provider: "deepseek",
        status: "ready",
        message: "LLM 已配置",
      },
    ]);
  });

  it("renders v0.2 candidates, refresh control, and provider status from the backend", async () => {
    render(await ResearchDashboardPage());

    expect(fetchResearchCandidates).toHaveBeenCalledWith(
      expect.objectContaining({
        scope_version_id: "scope-current",
        universe: "ALL_A",
      }),
    );
    expect(fetchProviderStatus).toHaveBeenCalled();
    expect(screen.getByText("全量底座上的用户可见研究候选")).toBeInTheDocument();
    expect(screen.getByText("000001")).toBeInTheDocument();
    expect(screen.getByText("有效：assess-1")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "启动估值发现" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("研究作用域版本")).toHaveValue("scope-current");
    expect(screen.queryByLabelText("策略 ID")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("标的代码")).not.toBeInTheDocument();
    expect(screen.getByText("deepseek")).toBeInTheDocument();
    expect(screen.getByText("LLM 已配置")).toBeInTheDocument();
  });
});
