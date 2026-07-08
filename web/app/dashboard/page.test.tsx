/**
 * @fileoverview Tests for the user-facing recommendation dashboard.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchResearchItemDetailV2,
  fetchResearchRunDetailV2,
  fetchResearchCandidates,
  fetchValuationDiscoveryRuns,
  startValuationDiscoveryRefresh,
} from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n";

import RecommendationDashboardPage from "./page";

vi.mock("@/lib/api", () => ({
  fetchResearchItemDetailV2: vi.fn(),
  fetchResearchRunDetailV2: vi.fn(),
  fetchResearchCandidates: vi.fn(),
  fetchValuationDiscoveryRuns: vi.fn(),
  startValuationDiscoveryRefresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

describe("RecommendationDashboardPage", () => {
  beforeEach(() => {
    vi.mocked(fetchResearchRunDetailV2).mockResolvedValue({
      completed_count: 0,
      failed_count: 0,
      pending_count: 12,
      retry_after_seconds: null,
      run_id: "run-dashboard",
      status: "running",
      steps: [],
      supported_wait_states: ["waiting_provider", "waiting_rate_limit", "waiting_retry"],
      target_count: 12,
      trace_id: "run-dashboard",
      wait_state: null,
    });
    vi.mocked(fetchValuationDiscoveryRuns).mockResolvedValue({
      items: [],
      next_cursor: null,
      page_size: 1,
    });
    vi.mocked(startValuationDiscoveryRefresh).mockResolvedValue({
      http_status: 202,
      run_id: "run-dashboard",
      status: "pending",
    });
    vi.mocked(fetchResearchItemDetailV2).mockResolvedValue({
      current_review: {
        outcome: "update_assessment",
        reason: null,
      },
      effective_assessment: {
        assessment_id: "assess-1",
        freshness: "fresh",
        stale_reason: null,
      },
      evidence: [
        {
          evidence_id: "ev-1",
          locator: "年报 第 2 页",
          snapshot_id: "snap-1",
          source_level: "official",
          source_url: null,
          title: "年报",
        },
      ],
      factors: { final_score: 86, quality: 82 },
      item: {
        assessment_freshness: "fresh",
        confidence: 0.82,
        current_review_outcome: "update_assessment",
        data_status: "complete",
        discount_rate: 0.18,
        effective_assessment_id: "assess-1",
        final_score: 86,
        item_id: "item-1",
        last_checked_at: "2026-07-01T00:00:00Z",
        name: "平安银行",
        research_guardrail: "allow_research",
        review_required: true,
        risk_flags: ["财务杠杆偏高"],
        scope_version_id: "scope-current",
        screening_status: "pass",
        security_id: "000001.SZ",
        stale_reason: null,
        symbol: "000001",
      },
      thesis: {
        statement: "估值折价仍然存在",
      },
      versions: {
        snapshot_id: "ctx-1",
      },
    });
    vi.mocked(fetchResearchCandidates).mockResolvedValue({
      as_of: "2026-07-01T00:00:00Z",
      facets: {},
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
          last_checked_at: "2026-07-01T00:00:00Z",
          name: "平安银行",
          research_guardrail: "allow_research",
          review_required: true,
          risk_flags: ["财务杠杆偏高"],
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
        page_size: 20,
      },
      scope_version_id: "scope-current",
    });
  });

  it("renders today's recommendations without exposing backend plumbing", async () => {
    render(
      <LanguageProvider>{await RecommendationDashboardPage()}</LanguageProvider>,
    );

    expect(fetchResearchCandidates).toHaveBeenCalledWith(
      {
        limit: 20,
        scope_version_id: "scope-current",
        universe: "ALL_A",
      },
    );
    expect(screen.getByRole("heading", { name: "今日推荐" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "启动今日研究" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "平安银行" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "平安银行" })).toHaveAttribute(
      "href",
      "/dashboard/items/item-1",
    );
    expect(screen.getAllByText(/82.0%/).length).toBeGreaterThan(0);
    expect(screen.getByText("量化评分")).toBeInTheDocument();
    expect(screen.getByText("86")).toBeInTheDocument();
    expect(screen.getByText("估值折价")).toBeInTheDocument();
    expect(screen.getByText("18.0%")).toBeInTheDocument();
    expect(screen.getAllByText(/需复核/).length).toBeGreaterThan(0);
    expect(screen.queryByText("评分分布")).not.toBeInTheDocument();
    expect(screen.queryByText("风险提示")).not.toBeInTheDocument();
    expect(fetchResearchItemDetailV2).not.toHaveBeenCalled();
    expect(screen.queryByText(/Provider|Scope|BFF|run id/i)).not.toBeInTheDocument();
  });

  it("loads the latest refresh run without filtering by the scope-current alias", async () => {
    render(
      <LanguageProvider>{await RecommendationDashboardPage()}</LanguageProvider>,
    );

    await waitFor(() =>
      expect(fetchValuationDiscoveryRuns).toHaveBeenCalledWith({ limit: 1 }),
    );
    expect(fetchValuationDiscoveryRuns).not.toHaveBeenCalledWith(
      expect.objectContaining({ scope_version_id: "scope-current" }),
    );
  });

  it("keeps detail content out of the dashboard list page", async () => {
    render(
      <LanguageProvider>{await RecommendationDashboardPage()}</LanguageProvider>,
    );

    expect(fetchResearchItemDetailV2).not.toHaveBeenCalled();
    expect(screen.queryByText("推荐详情")).not.toBeInTheDocument();
    expect(screen.queryByText("量化视图")).not.toBeInTheDocument();
    expect(screen.queryByText("年报 第 2 页")).not.toBeInTheDocument();
  });
});
