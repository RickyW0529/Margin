import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fetchPortfolioDashboard,
  fetchPortfolioPositions,
} from "@/lib/api";

import PortfolioPage from "./page";

vi.mock("@/lib/api", () => ({
  fetchPortfolioDashboard: vi.fn(),
  fetchPortfolioPositions: vi.fn(),
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
    total_assets: 1000000,
    cash: 1000000,
    market_value: 0,
    today_pnl: null,
    cumulative_pnl: 0,
    portfolio_volatility: null,
    max_drawdown: null,
    industry_exposure: {},
    style_exposure: {},
    high_risk_count: 0,
    upcoming_events: [],
    position_count: 0,
    updated_at: "2026-06-19T00:00:00Z",
  },
};

describe("PortfolioPage", () => {
  beforeEach(() => {
    vi.mocked(fetchPortfolioDashboard).mockResolvedValue(dashboard);
    vi.mocked(fetchPortfolioPositions).mockResolvedValue([]);
  });

  it("resolves route params and data before rendering the workspace", async () => {
    const page = await PortfolioPage({
      params: Promise.resolve({ portfolioId: "demo" }),
    });

    expect(fetchPortfolioDashboard).toHaveBeenCalledWith("demo");
    expect(fetchPortfolioPositions).toHaveBeenCalledWith("demo");

    render(page);
    expect(
      screen.getByRole("heading", { name: "Demo 组合" }),
    ).toBeInTheDocument();
  });
});
