/**
 * @fileoverview Quant strategy customizer tests.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  QuantStrategyCustomizer,
} from "./quant-strategy-customizer";
import type { QuantStrategyDefaults } from "@/lib/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const defaults: QuantStrategyDefaults = {
  profile: "monthly_manual_pool_threshold_no_top_n_v1",
  default_universe: "ALL_A",
  execution_boundary: "research_only_no_order",
  presets: {
    ALL_A: preset("ALL_A", "全A", 76, 66),
    CSI300: preset("CSI300", "沪深300", 68, 60),
    CSI500: preset("CSI500", "中证500", 72, 64),
  },
};

test("quant customizer saves a no-top-n strategy version for selected pool", async () => {
  vi.spyOn(Date, "now").mockReturnValue(123);
  const createConfig = vi.fn().mockResolvedValue({
    version_id: "quant-strategy-csi300-123",
  });

  render(
    <QuantStrategyCustomizer defaults={defaults} createConfig={createConfig} />,
  );

  fireEvent.change(screen.getByLabelText("评分预设"), {
    target: { value: "CSI300" },
  });
  fireEvent.change(screen.getByLabelText("买入阈值"), {
    target: { value: "70" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存量化策略版本" }));

  await waitFor(() => expect(createConfig).toHaveBeenCalled());
  const [kind, body] = createConfig.mock.calls[0];
  expect(kind).toBe("quant-strategies");
  expect(body).toMatchObject({
    version_id: "quant-strategy-csi300-123",
    strategy_family: "default",
    lifecycle: "review",
    calibration_report_id: "ui-custom-csi300",
  });
  expect(body.thresholds).toMatchObject({
    default_universe: "CSI300",
    execution_boundary: "research_only_no_order",
  });
  expect(body.thresholds.presets.CSI300).toMatchObject({
    buy_threshold: 70,
    candidate_policy: {
      market_cap_filter: false,
      no_top_n: true,
      theme_tilt: {
        enabled: true,
      },
    },
    factor_weights: {
      theme_hotness: 0.1,
    },
    rebalance_frequency: "monthly",
  });
  expect(
    await screen.findByText("策略版本已保存，激活前不会影响线上筛选。"),
  ).toBeInTheDocument();
});

test("quant customizer validates monthly rebalance buffer", () => {
  const createConfig = vi.fn();
  render(
    <QuantStrategyCustomizer defaults={defaults} createConfig={createConfig} />,
  );

  fireEvent.change(screen.getByLabelText("买入阈值"), {
    target: { value: "60" },
  });
  fireEvent.change(screen.getByLabelText("卖出阈值"), {
    target: { value: "60" },
  });
  fireEvent.click(screen.getByRole("button", { name: "保存量化策略版本" }));

  expect(screen.getByRole("alert")).toHaveTextContent("卖出阈值必须低于买入阈值");
  expect(createConfig).not.toHaveBeenCalled();
});

function preset(
  universeCode: string,
  label: string,
  buyThreshold: number,
  sellThreshold: number,
) {
  return {
    benchmark_index_code: universeCode === "ALL_A" ? null : "000300.SH",
    buy_threshold: buyThreshold,
    calibration: {},
    candidate_policy: {
      market_cap_filter: false,
      no_top_n: true,
      theme_tilt: {
        enabled: true,
      },
    },
    factor_weights: {
      dividend: 0.16,
      liquidity: 0.1,
      momentum: 0.08,
      reversal: 0.14,
      risk_health: 0.08,
      theme_hotness: 0.1,
      value: 0.38,
      volume_sentiment: 0.06,
    },
    label,
    min_avg_amount_20d: 50_000_000,
    rebalance_frequency: "monthly",
    sell_threshold: sellThreshold,
    universe_code: universeCode,
    weighting: "inv_vol_score",
  };
}
