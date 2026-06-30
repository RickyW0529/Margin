/**
 * @fileoverview Tests for the factor radar chart component.
 */

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FactorRadarChart } from "@/components/factor-radar-chart";
import type { FactorScoreItem } from "@/lib/api";

const factorScores: FactorScoreItem[] = [
  { factor_key: "quality_score", label: "质量", score: 75.0, weight: 0.35 },
  { factor_key: "value_score", label: "价值", score: 88.0, weight: 0.25 },
  { factor_key: "growth_score", label: "成长", score: 60.0, weight: 0.15 },
  { factor_key: "momentum_score", label: "动量", score: 70.0, weight: 0.15 },
  { factor_key: "risk_score", label: "风险", score: 65.0, weight: 0.10 },
];

describe("FactorRadarChart", () => {
  it("renders the chart container for valid scores", () => {
    const { container } = render(<FactorRadarChart factorScores={factorScores} />);
    expect(container.firstChild).not.toBeNull();
  });

  it("shows empty state message when no factor scores", () => {
    render(<FactorRadarChart factorScores={[]} />);
    expect(screen.getByText("暂无因子分数数据")).toBeInTheDocument();
  });

  it("handles null scores without crashing", () => {
    const nullScores: FactorScoreItem[] = [
      { factor_key: "quality_score", label: "质量", score: null, weight: 0.35 },
    ];
    const { container } = render(<FactorRadarChart factorScores={nullScores} />);
    expect(container.firstChild).not.toBeNull();
  });
});
