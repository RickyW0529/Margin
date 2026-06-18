import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PositionDetailView } from "./position-detail";

describe("PositionDetailView", () => {
  it("renders cost, thesis, invalidation conditions, and trade history", () => {
    render(
      <PositionDetailView
        portfolioId="pf_demo"
        detail={{
          position_id: "pos_1",
          symbol: "000001.SZ",
          quantity: 1000,
          cost_price: 10,
          cost_amount: 10000,
          current_price: 11,
          market_value: 11000,
          unrealized_pnl: 1000,
          unrealized_pnl_pct: 0.1,
          industry: "银行",
          health_status: "watch",
          thesis: {
            thesis_id: "th_1",
            position_id: "pos_1",
            thesis: "现金流改善与估值修复",
            entry_conditions: [],
            hold_conditions: ["经营现金流保持增长"],
            invalidation_conditions: ["经营现金流转负"],
            target_horizon: [60, 120],
            next_review_at: null,
            status: "thesis_valid",
            version: 1,
            created_at: "2026-06-18T00:00:00Z",
          },
          trade_history: [
            {
              trade_id: "trd_1",
              side: "buy",
              quantity: 1000,
              price: 10,
              amount: 10000,
              traded_at: "2026-06-01T00:00:00Z",
              source: "manual",
            },
          ],
          weight: 0.35,
          updated_at: "2026-06-18T00:00:00Z",
        }}
        error={null}
      />,
    );

    expect(screen.getByRole("heading", { name: "000001.SZ" })).toBeInTheDocument();
    expect(screen.getByText("现金流改善与估值修复")).toBeInTheDocument();
    expect(screen.getByText("经营现金流转负")).toBeInTheDocument();
    expect(screen.getByText("操作历史")).toBeInTheDocument();
  });
});
