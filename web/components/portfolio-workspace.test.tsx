/**
 * @fileoverview Unit tests for the PortfolioWorkspace component.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PortfolioWorkspace } from "./portfolio-workspace";

/** Mock portfolio dashboard used in PortfolioWorkspace tests. */
const dashboard = {
  portfolio: {
    portfolio_id: "pf_demo",
    user_id: "user_demo",
    name: "核心组合",
    cash: 120000,
    created_at: "2026-06-18T00:00:00Z",
  },
  overview: {
    portfolio_id: "pf_demo",
    portfolio_name: "核心组合",
    total_assets: 320000,
    cash: 120000,
    market_value: 200000,
    today_pnl: 1800,
    cumulative_pnl: 22000,
    portfolio_volatility: 0.18,
    max_drawdown: 0.09,
    industry_exposure: { 银行: 0.42, 消费: 0.28 },
    style_exposure: { value: 0.62, growth: 0.38 },
    high_risk_count: 1,
    upcoming_events: [
      { symbol: "000001.SZ", date: "2026-06-25T00:00:00Z", days_until: 7 },
    ],
    position_count: 2,
    updated_at: "2026-06-18T00:00:00Z",
  },
};

/** Mock positions used in PortfolioWorkspace tests. */
const positions = [
  {
    position_id: "pos_1",
    portfolio_id: "pf_demo",
    symbol: "000001.SZ",
    quantity: 10000,
    cost_price: 10,
    cost_amount: 100000,
    current_price: 11.2,
    market_value: 112000,
    unrealized_pnl: 12000,
    unrealized_pnl_pct: 0.12,
    industry: "银行",
    health_status: "watch",
    thesis: null,
    updated_at: "2026-06-18T00:00:00Z",
  },
];

/** Tests for PortfolioWorkspace rendering behavior. */
describe("PortfolioWorkspace", () => {
  it("renders portfolio metrics, positions, exposures, and events", () => {
    render(
      <PortfolioWorkspace
        dashboard={dashboard}
        positions={positions}
        error={null}
      />,
    );

    expect(screen.getByRole("heading", { name: "核心组合" })).toBeInTheDocument();
    expect(screen.getByText("总资产")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "000001.SZ" })).toHaveAttribute(
      "href",
      "/positions/pos_1?portfolioId=pf_demo",
    );
    expect(screen.getByText("行业暴露")).toBeInTheDocument();
    expect(screen.getByText("即将发生")).toBeInTheDocument();
  });

  it("renders a clear empty state", () => {
    render(
      <PortfolioWorkspace dashboard={dashboard} positions={[]} error={null} />,
    );

    expect(screen.getByText("暂无持仓")).toBeInTheDocument();
  });

  it("renders an API error state", () => {
    render(
      <PortfolioWorkspace
        dashboard={null}
        positions={[]}
        error="组合数据暂时不可用"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("组合数据暂时不可用");
  });
});
