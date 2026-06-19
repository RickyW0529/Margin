import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HomeSummary } from "./home-summary";
import type { ResearchHomeSummary } from "@/lib/api";

const summary: ResearchHomeSummary = {
  decision_at: "2026-06-19T00:00:00Z",
  run_id: "dr_1",
  strategy_id: "st_demo",
  version_id: "sv_demo",
  run_status: "published",
  today_candidates: [],
  position_reviews: [],
  high_priority_risks: [],
  rejections: [],
  run_stats: {
    item_count: 3,
    published_count: 2,
    abstained_count: 1,
    aborted_count: 0,
  },
};

describe("HomeSummary", () => {
  it("renders the six dashboard blocks and run stats", () => {
    render(<HomeSummary summary={summary} />);

    expect(screen.getByText("市场状态摘要")).toBeInTheDocument();
    expect(screen.getByText("今日候选")).toBeInTheDocument();
    expect(screen.getByText("现有持仓复核")).toBeInTheDocument();
    expect(screen.getByText("高优先级风险")).toBeInTheDocument();
    expect(screen.getByText("拒绝判断")).toBeInTheDocument();
    expect(screen.getByText("策略运行状态")).toBeInTheDocument();
    expect(screen.getByText("3 个研究项")).toBeInTheDocument();
  });
});
