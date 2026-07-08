/**
 * @fileoverview Tests for the dashboard recommendation detail route.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchResearchItemDetailV2 } from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n";

import RecommendationDetailPage from "./page";

vi.mock("@/lib/api", () => ({
  fetchResearchItemDetailV2: vi.fn(),
}));

describe("RecommendationDetailPage", () => {
  beforeEach(() => {
    vi.mocked(fetchResearchItemDetailV2).mockResolvedValue({
      current_review: {
        outcome: "review_deferred",
        reason: "证据包为空，AI 未形成可引用结论。",
        conclusion: "证据不足，等待补证。",
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
          snippet: "证券代码：000001 证券简称：平安银行",
          linked_to_security: true,
        },
      ],
      factors: {
        final_score: 86,
        quality: 82,
        valuation: {
          discount_rate: null,
          status: "missing_assessment",
          message: "AI 估值未形成：没有可引用证据支持 valuation assessment。",
        },
        trends: [
          {
            metric: "adj_close",
            label: "复权收盘价",
            unit: "CNY",
            points: [
              { date: "2026-06-01", value: 10.2 },
              { date: "2026-07-01", value: 12.4 },
            ],
          },
        ],
      },
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
        statement: "证据不足，等待补证。",
        ai_status: "review_deferred",
      },
      versions: {
        snapshot_id: "ctx-1",
      },
    });
  });

  it("renders detail visuals and evidence on a dedicated route", async () => {
    render(
      <LanguageProvider>
        {await RecommendationDetailPage({
          params: Promise.resolve({ itemId: "item-1" }),
        })}
      </LanguageProvider>,
    );

    expect(fetchResearchItemDetailV2).toHaveBeenCalledWith("item-1");
    expect(screen.getByRole("link", { name: "返回今日推荐" })).toHaveAttribute(
      "href",
      "/dashboard",
    );
    expect(screen.getByRole("heading", { name: "平安银行" })).toBeInTheDocument();
    expect(screen.getByText("证据不足，等待补证。")).toBeInTheDocument();
    expect(screen.getAllByText("证据包为空，AI 未形成可引用结论。").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("暂未形成估值结论")).toBeInTheDocument();
    expect(screen.getByText("复权收盘价")).toBeInTheDocument();
    expect(screen.getByText("量化视图")).toBeInTheDocument();
    expect(screen.getByText("风险与复核")).toBeInTheDocument();
    expect(screen.getByText("年报")).toBeInTheDocument();
    expect(screen.getByText("已关联本股票")).toBeInTheDocument();
  });
});
