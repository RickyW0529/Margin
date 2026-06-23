/**
 * @fileoverview Tests for the v0.2 research item detail page.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchResearchItemDetailV2,
} from "@/lib/api";

import ResearchItemPage from "./page";

vi.mock("@/lib/api", () => ({
  createResearchItemFeedback: vi.fn(),
  fetchResearchItemDetailV2: vi.fn(),
}));

vi.mock("./actions", () => ({
  createResearchFeedbackAction: vi.fn(),
}));

describe("ResearchItemPage", () => {
  beforeEach(() => {
    vi.mocked(fetchResearchItemDetailV2).mockResolvedValue({
      current_review: {
        outcome: "update_assessment",
        reason: "new evidence supports thesis",
        workflow_run_id: "wf-1",
      },
      effective_assessment: {
        assessment_id: "assess-1",
        freshness: "fresh",
        stale_reason: null,
      },
      evidence: [
        {
          evidence_id: "ev-1",
          locator: "公告:第 2 页",
          pit_timestamp: "2026-06-23T08:30:00Z",
          snapshot_id: "snap-1",
          source_level: "official",
          source_url: "https://example.com/a.pdf",
          title: "年报",
        },
      ],
      factors: { final_score: 86 },
      item: {
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
        review_required: false,
        risk_flags: [],
        scope_version_id: "scope-current",
        screening_status: "pass",
        security_id: "sec-1",
        stale_reason: null,
        symbol: "000001",
      },
      thesis: {
        statement: "估值折价仍然存在",
      },
      versions: {
        run_id: "vdr-1",
        snapshot_id: "ctx-1",
        workflow_run_id: "wf-1",
      },
    });
  });

  it("renders v0.2 aggregate detail without querying legacy item endpoints", async () => {
    render(await ResearchItemPage({ params: Promise.resolve({ itemId: "item-1" }) }));

    expect(fetchResearchItemDetailV2).toHaveBeenCalledWith("item-1");
    expect(screen.getByRole("heading", { name: "000001" })).toBeInTheDocument();
    expect(screen.getByText("估值折价仍然存在")).toBeInTheDocument();
    expect(screen.getByText("当前有效结论：assess-1")).toBeInTheDocument();
    expect(screen.getByText("公告:第 2 页")).toBeInTheDocument();
  });
});
