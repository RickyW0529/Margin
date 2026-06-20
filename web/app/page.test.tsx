/**
 * @fileoverview Tests for the home page.
 */

import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchPortfolioDashboard,
  fetchProviderStatus,
  fetchResearchHome,
  fetchResearchRuns,
} from "@/lib/api";

import HomePage from "./page";

vi.mock("@/lib/api", () => ({
  fetchPortfolioDashboard: vi.fn(),
  fetchProviderStatus: vi.fn(),
  fetchResearchHome: vi.fn(),
  fetchResearchRuns: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  redirect: vi.fn((path: string) => {
    throw new Error(`unexpected redirect to ${path}`);
  }),
}));

const dashboard = {
  portfolio: {
    portfolio_id: "demo",
    user_id: "user_demo",
    name: "Demo 组合",
    cash: 1000000,
    created_at: "2026-06-19T00:00:00Z",
  },
  overview: {
    portfolio_id: "demo",
    portfolio_name: "Demo 组合",
    total_assets: 1200000,
    cash: 1000000,
    market_value: 200000,
    today_pnl: 1200,
    cumulative_pnl: 10000,
    portfolio_volatility: null,
    max_drawdown: null,
    industry_exposure: {},
    style_exposure: {},
    high_risk_count: 1,
    upcoming_events: [],
    position_count: 2,
    updated_at: "2026-06-19T00:00:00Z",
  },
};

describe("HomePage", () => {
  beforeEach(() => {
    vi.mocked(fetchPortfolioDashboard).mockResolvedValue(dashboard);
    vi.mocked(fetchProviderStatus).mockResolvedValue([
      { provider: "postgres", status: "ready", message: "connected" },
    ]);
    vi.mocked(fetchResearchHome).mockResolvedValue({
      decision_at: "2026-06-19T00:00:00Z",
      run_id: "run_1",
      strategy_id: "default",
      version_id: "v0.1",
      run_status: "completed",
      today_candidates: [],
      position_reviews: [],
      high_priority_risks: [],
      rejections: [],
      run_stats: { completed: 1 },
    });
    vi.mocked(fetchResearchRuns).mockResolvedValue([
      {
        run_id: "run_1",
        decision_at: "2026-06-19T00:00:00Z",
        strategy_id: "default",
        version_id: "v0.1",
        portfolio_id: "demo",
        universe: ["000001.SZ"],
        status: "completed",
        summary: "已生成研究候选",
        item_count: 1,
        published_count: 1,
        abstained_count: 0,
        aborted_count: 0,
        created_at: "2026-06-19T00:00:00Z",
      },
    ]);
  });

  it("renders a real API-backed product home instead of hard-redirecting to demo", async () => {
    render(await HomePage());

    expect(fetchPortfolioDashboard).toHaveBeenCalledWith("demo");
    expect(fetchResearchHome).toHaveBeenCalled();
    expect(fetchProviderStatus).toHaveBeenCalled();
    expect(screen.getByRole("heading", { name: "Margin 工作台" })).toBeInTheDocument();
    expect(screen.getByText("Demo 组合")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "打开组合看板" })).toHaveAttribute(
      "href",
      "/portfolios/demo",
    );
    expect(screen.getByRole("link", { name: "进入研究面板" })).toHaveAttribute(
      "href",
      "/research",
    );
  });
});
