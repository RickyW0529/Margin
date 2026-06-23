/**
 * @fileoverview Tests for the v0.2 research results table.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ResearchResultsTable } from "./research-results-table";

afterEach(() => {
  cleanup();
});

describe("ResearchResultsTable", () => {
  it("shows current outcome and effective assessment separately", () => {
    render(
      <ResearchResultsTable
        items={[
          {
            item_id: "item-1",
            security_id: "sec-1",
            symbol: "000001",
            name: "平安银行",
            scope_version_id: "scope-1",
            screening_status: "pass",
            data_status: "complete",
            risk_flags: ["goodwill_risk"],
            review_required: false,
            research_guardrail: "allow_research",
            current_review_outcome: "review_deferred",
            effective_assessment_id: "assess-old",
            assessment_freshness: "stale",
            stale_reason: "news_target_incomplete",
            final_score: 82.3,
            discount_rate: 0.28,
            confidence: 0.64,
            last_checked_at: "2026-06-22T00:00:00Z",
          },
        ]}
        pageInfo={{ has_next_page: true, next_cursor: "cursor-2", page_size: 50 }}
        scopeVersionId="scope-1"
        universe="ALL_A"
      />,
    );

    const row = screen.getByRole("row", { name: /000001/ });

    expect(within(row).getByText("本轮：review_deferred")).toBeInTheDocument();
    expect(within(row).getByText("有效：assess-old")).toBeInTheDocument();
    expect(within(row).getByText("stale")).toBeInTheDocument();
    expect(within(row).getByText("28%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "下一页" })).toHaveAttribute(
      "href",
      expect.stringContaining("cursor=cursor-2"),
    );
  });

  it("renders an empty state instead of an empty table", () => {
    render(
      <ResearchResultsTable
        items={[]}
        pageInfo={{ has_next_page: false, next_cursor: null, page_size: 50 }}
        scopeVersionId="scope-1"
        universe="ALL_A"
      />,
    );

    expect(screen.getByText("暂无符合当前筛选条件的研究候选")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
