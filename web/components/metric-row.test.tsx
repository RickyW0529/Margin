/**
 * @fileoverview Tests for the metric row component.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { MetricRow } from "@/components/metric-row";
import type { AnalysisMetric } from "@/lib/api";

afterEach(() => {
  cleanup();
});

const metric: AnalysisMetric = {
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
};

describe("MetricRow", () => {
  it("renders metric name, value, and percentile labels", () => {
    render(<MetricRow metric={metric} />);
    expect(screen.getByText("市盈率 TTM")).toBeInTheDocument();
    expect(screen.getByText("市场")).toBeInTheDocument();
    expect(screen.getByText("行业")).toBeInTheDocument();
  });

  it("renders direction label for lower direction", () => {
    render(<MetricRow metric={metric} />);
    expect(screen.getByText(/越低越好/)).toBeInTheDocument();
  });

  it("renders direction label for higher direction", () => {
    render(<MetricRow metric={{ ...metric, direction: "higher" }} />);
    expect(screen.getByText(/越高越好/)).toBeInTheDocument();
  });

  it("hides percentile bars when percentiles are null", () => {
    render(
      <MetricRow
        metric={{
          ...metric,
          percentile_market: null,
          percentile_industry: null,
        }}
      />,
    );
    expect(screen.queryByText("市场")).not.toBeInTheDocument();
    expect(screen.queryByText("行业")).not.toBeInTheDocument();
  });

  it("shows dash for null numeric value", () => {
    render(<MetricRow metric={{ ...metric, numeric_value: null }} />);
    expect(screen.getByText("--")).toBeInTheDocument();
  });
});
