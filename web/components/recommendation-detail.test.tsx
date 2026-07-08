/**
 * @fileoverview Tests for the recommendation detail page.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { RecommendationDetail } from "./recommendation-detail";
import type { ResearchItemDetailV2 } from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n";

afterEach(cleanup);

describe("RecommendationDetail", () => {
  it("explains when value estimation is not available yet", () => {
    render(
      <LanguageProvider>
        <RecommendationDetail detail={makeDetail()} />
      </LanguageProvider>,
    );

    expect(screen.getByText("价值估算")).toBeInTheDocument();
    expect(screen.getByText("暂未形成估值结论")).toBeInTheDocument();
    expect(screen.getByText("需要股票分析师完成估值复核后才会展示安全边际。")).toBeInTheDocument();
  });

  it("renders available value estimate with margin of safety", () => {
    render(
      <LanguageProvider>
        <RecommendationDetail
          detail={makeDetail({
            factors: {
              valuation: {
                status: "available",
                intrinsic_value: 18.5,
                margin_of_safety: 0.24,
                discount_rate: 0.24,
                message: "基于当前分析快照形成估值区间。",
              },
            },
          })}
        />
      </LanguageProvider>,
    );

    expect(screen.getByText("价值估算")).toBeInTheDocument();
    expect(screen.getByText("安全边际")).toBeInTheDocument();
    expect(screen.getByText("24.0%")).toBeInTheDocument();
    expect(screen.getByText("¥18.50")).toBeInTheDocument();
  });
});

function makeDetail(overrides: Partial<ResearchItemDetailV2> = {}): ResearchItemDetailV2 {
  return {
    item: {
      item_id: "item-1",
      security_id: "002416.SZ",
      symbol: "002416",
      name: "爱施德",
      scope_version_id: "scope-1",
      screening_status: "pass",
      data_status: "complete",
      risk_flags: [],
      review_required: false,
      research_guardrail: "allow",
      current_review_outcome: "update_assessment",
      effective_assessment_id: "assess-1",
      assessment_freshness: "fresh",
      stale_reason: null,
      final_score: 92.5,
      discount_rate: null,
      confidence: 0.92,
      last_checked_at: "2026-07-07T00:00:00Z",
    },
    current_review: { outcome: "update_assessment", confidence: 0.92 },
    effective_assessment: {},
    factors: overrides.factors ?? {},
    thesis: { statement: "经营质量改善。" },
    evidence: [],
    versions: { snapshot_id: "snap-1", workflow_run_id: "wf-1" },
    ...overrides,
  };
}
