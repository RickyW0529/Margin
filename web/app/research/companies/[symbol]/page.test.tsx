/**
 * @fileoverview Tests for the company quant + analysis profile page.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanup();
});

import {
  fetchCompanyAnalysisProfile,
  fetchCompanyQuantProfile,
} from "@/lib/api";

import CompanyPage from "./page";

vi.mock("@/lib/api", () => ({
  fetchCompanyQuantProfile: vi.fn(),
  fetchCompanyAnalysisProfile: vi.fn(),
}));

const quantProfile = {
  security_id: "sec_001",
  quant_run_id: "qr_001",
  result_id: "qres_001",
  decision_at: "2026-06-24T08:00:00Z",
  final_score: 82.5,
  factor_scores: [
    { factor_key: "quality_score", label: "质量", score: 75.0, weight: 0.35 },
    { factor_key: "value_score", label: "价值", score: 88.0, weight: 0.25 },
    { factor_key: "growth_score", label: "成长", score: 60.0, weight: 0.15 },
    { factor_key: "momentum_score", label: "动量", score: 70.0, weight: 0.15 },
    { factor_key: "risk_score", label: "风险", score: 65.0, weight: 0.1 },
  ],
  rank_overall: 12,
  rank_in_industry: 3,
  screening_status: "pass",
  data_status: "ok",
  risk_flags: ["overheat"],
  review_required: false,
  review_reasons: [],
  research_guardrail: "research_allowed",
  reason_summary: "All factor groups above threshold.",
  factor_details: {},
};

const analysisProfile = {
  security_id: "sec_001",
  snapshot: {
    analysis_snapshot_id: "ans_001",
    decision_at: "2026-06-24T08:00:00Z",
    trading_date: "2026-06-24",
    analysis_version: "v1",
    analysis_kind: "quant_screen",
    quant_run_id: "qr_001",
    quant_result_id: "qres_001",
    input_hash: "sha256:input",
    result_hash: "sha256:result",
  },
  metrics: [
    {
      metric_id: "am_001",
      metric_code: "pe_ttm",
      metric_name: "市盈率 TTM",
      metric_group: "value",
      numeric_value: 12.3,
      unit: "x",
      direction: "lower",
      percentile_market: 85.2,
      percentile_industry: 72.1,
      rank_market: 120,
      rank_industry: 8,
    },
  ],
  findings: [
    {
      finding_id: "af_001",
      finding_type: "value",
      severity: "info",
      title: "估值偏低",
      description: "PE 低于行业中位数。",
      confidence: 0.82,
      evidence_ids: ["ev_001"],
    },
  ],
  evidence_link_count: 1,
};

describe("CompanyPage", () => {
  beforeEach(() => {
    vi.mocked(fetchCompanyQuantProfile).mockResolvedValue(quantProfile);
    vi.mocked(fetchCompanyAnalysisProfile).mockResolvedValue(analysisProfile);
  });

  it("renders company header with symbol and pass status badge", async () => {
    render(
      await CompanyPage({ params: Promise.resolve({ symbol: "sec_001" }) }),
    );

    expect(fetchCompanyQuantProfile).toHaveBeenCalledWith("sec_001");
    expect(screen.getByRole("heading", { name: "sec_001" })).toBeInTheDocument();
    expect(screen.getAllByText("通过").length).toBeGreaterThan(0);
  });

  it("renders quant overview with final score and rankings", async () => {
    render(
      await CompanyPage({ params: Promise.resolve({ symbol: "sec_001" }) }),
    );

    expect(screen.getAllByText("82.5").length).toBeGreaterThan(0);
    expect(screen.getAllByText("#12").length).toBeGreaterThan(0);
    expect(screen.getAllByText("#3").length).toBeGreaterThan(0);
  });

  it("renders all four tab triggers", async () => {
    render(
      await CompanyPage({ params: Promise.resolve({ symbol: "sec_001" }) }),
    );

    expect(screen.getAllByRole("tab", { name: "因子雷达" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("tab", { name: "分析指标" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("tab", { name: "关键发现" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("tab", { name: "筛选原因" }).length).toBeGreaterThan(0);
  });

  it("renders error alert when both fetches fail", async () => {
    vi.mocked(fetchCompanyQuantProfile).mockRejectedValue(new Error("network"));
    vi.mocked(fetchCompanyAnalysisProfile).mockRejectedValue(new Error("network"));

    render(
      await CompanyPage({ params: Promise.resolve({ symbol: "sec_001" }) }),
    );

    expect(
      screen.getByText("无法加载该公司量化与分析数据，请稍后重试。"),
    ).toBeInTheDocument();
  });
});
