/**
 * @fileoverview Tests for metric trend charts on recommendation details.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricTrendChart } from "./metric-trend-chart";

describe("MetricTrendChart", () => {
  it("renders a line chart with first and last values", () => {
    const { container } = render(
      <MetricTrendChart
        trend={{
          metric: "adj_close",
          label: "复权收盘价",
          unit: "CNY",
          points: [
            { date: "2026-06-01", value: 10.2 },
            { date: "2026-07-01", value: 12.4 },
          ],
        }}
      />,
    );

    expect(screen.getByText("复权收盘价")).toBeInTheDocument();
    expect(screen.getByText(/10.2/)).toBeInTheDocument();
    expect(screen.getAllByText(/12.4/).length).toBeGreaterThan(0);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelector("polyline")).not.toBeNull();
  });

  it("shows an empty state when fewer than two points are available", () => {
    render(
      <MetricTrendChart
        trend={{
          metric: "roe_ttm",
          label: "ROE TTM",
          unit: "%",
          points: [{ date: "2026-07-01", value: 9.2 }],
        }}
      />,
    );

    expect(screen.getByText("趋势数据不足")).toBeInTheDocument();
  });
});
