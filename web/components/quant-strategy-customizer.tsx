"use client";

/**
 * @fileoverview User-facing quant strategy preset customizer.
 */

import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  createVersionedConfig,
  type QuantStrategyDefaults,
  type QuantStrategyPreset,
  type VersionedConfigRecord,
} from "@/lib/api";

const FACTOR_LABELS: Record<string, string> = {
  value: "估值",
  dividend: "分红",
  reversal: "短期反转",
  liquidity: "流动性",
  volume_sentiment: "量能",
  momentum: "中期动量",
  risk_health: "回撤/波动",
  theme_hotness: "题材热度",
};

type QuantStrategyCustomizerProps = {
  defaults: QuantStrategyDefaults;
  createConfig?: (
    kind: "quant-strategies",
    body: Record<string, unknown>,
  ) => Promise<VersionedConfigRecord>;
};

/** Renders a compact editor for monthly manual quant strategy versions. */
export function QuantStrategyCustomizer({
  defaults,
  createConfig = createVersionedConfig,
}: QuantStrategyCustomizerProps) {
  const initialUniverse =
    defaults.presets[defaults.default_universe] !== undefined
      ? defaults.default_universe
      : Object.keys(defaults.presets)[0];
  const [universe, setUniverse] = useState(initialUniverse);
  const selectedPreset = defaults.presets[universe] ?? Object.values(defaults.presets)[0];
  const [buyThreshold, setBuyThreshold] = useState(selectedPreset.buy_threshold);
  const [sellThreshold, setSellThreshold] = useState(selectedPreset.sell_threshold);
  const [minAmount, setMinAmount] = useState(selectedPreset.min_avg_amount_20d);
  const [weighting, setWeighting] = useState(selectedPreset.weighting);
  const [weights, setWeights] = useState<Record<string, number>>(
    selectedPreset.factor_weights,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const normalizedWeightSum = useMemo(
    () => Object.values(weights).reduce((sum, value) => sum + Number(value || 0), 0),
    [weights],
  );

  function handleUniverseChange(nextUniverse: string) {
    const nextPreset = defaults.presets[nextUniverse];
    if (!nextPreset) {
      return;
    }
    setUniverse(nextUniverse);
    setBuyThreshold(nextPreset.buy_threshold);
    setSellThreshold(nextPreset.sell_threshold);
    setMinAmount(nextPreset.min_avg_amount_20d);
    setWeighting(nextPreset.weighting);
    setWeights(nextPreset.factor_weights);
  }

  function updateWeight(key: string, value: number) {
    setWeights((current) => ({ ...current, [key]: value }));
  }

  function validate(): boolean {
    if (sellThreshold >= buyThreshold) {
      setError("卖出阈值必须低于买入阈值，保留月度调仓缓冲。");
      return false;
    }
    if (minAmount < 0) {
      setError("最小 20 日成交额不能为负。");
      return false;
    }
    if (normalizedWeightSum <= 0) {
      setError("因子权重合计必须大于 0。");
      return false;
    }
    setError(null);
    return true;
  }

  async function handleCreate() {
    if (!validate()) {
      return;
    }
    setBusy(true);
    setSuccess(null);
    const versionId = `quant-strategy-${universe.toLowerCase()}-${Date.now()}`;
    const thresholds = buildThresholds(defaults, universe, selectedPreset, {
      buyThreshold,
      minAmount,
      sellThreshold,
      weighting,
      weights,
    });
    try {
      const created = await createConfig("quant-strategies", {
        version_id: versionId,
        owner_id: "local-admin",
        strategy_family: "default",
        factor_weights: weights,
        thresholds,
        calibration_report_id: `ui-custom-${universe.toLowerCase()}`,
        lifecycle: "review",
      });
      setSuccess(`${String(created.version_id ?? versionId)} 已保存，激活前不会生效。`);
    } catch {
      setError("保存失败，请检查版本内容或后端策略配置服务。");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Default quant
          </p>
          <CardTitle className="mt-1">默认量化策略与自定义版本</CardTitle>
        </div>
        <Badge tone="accent">月度调仓</Badge>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 md:grid-cols-4">
          <div className="grid gap-1.5 md:col-span-2">
            <Label htmlFor="quant-universe">评分预设</Label>
            <Select
              id="quant-universe"
              value={universe}
              onChange={(event) => handleUniverseChange(event.target.value)}
            >
              {Object.entries(defaults.presets).map(([code, preset]) => (
                <option key={code} value={code}>
                  {preset.label}
                </option>
              ))}
            </Select>
            <span className="text-xs text-muted-foreground">
              只调整阈值和权重；股票池在研究范围页配置。
            </span>
          </div>
          <Metric label="默认买入" value={selectedPreset.buy_threshold} />
          <Metric label="默认卖出" value={selectedPreset.sell_threshold} />
        </div>

        <div className="grid gap-3 md:grid-cols-4">
          <NumberField
            label="买入阈值"
            value={buyThreshold}
            onChange={setBuyThreshold}
          />
          <NumberField
            label="卖出阈值"
            value={sellThreshold}
            onChange={setSellThreshold}
          />
          <NumberField
            label="最小成交额"
            step={1_000_000}
            value={minAmount}
            onChange={setMinAmount}
          />
          <div className="grid gap-1.5">
            <Label htmlFor="quant-weighting">权重方式</Label>
            <Select
              id="quant-weighting"
              value={weighting}
              onChange={(event) => setWeighting(event.target.value)}
            >
              <option value="inv_vol_score">分数 / 波动</option>
              <option value="score_excess">分数超额</option>
              <option value="equal">等权</option>
            </Select>
          </div>
        </div>

        <div className="grid gap-2 rounded-md border border-border bg-muted/40 p-3">
          <div className="flex items-center justify-between gap-3">
            <span className="text-xs font-medium text-muted-foreground">
              因子权重
            </span>
            <span className="text-xs text-muted-foreground">
              合计 {normalizedWeightSum.toFixed(2)}
            </span>
          </div>
          <div className="grid gap-2 md:grid-cols-7">
            {Object.entries(weights).map(([key, value]) => (
              <NumberField
                key={key}
                label={FACTOR_LABELS[key] ?? key}
                step={0.01}
                value={value}
                onChange={(next) => updateWeight(key, next)}
              />
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2">
            <Badge tone="muted">不做 top-N 预截断</Badge>
            <Badge tone="muted">全 A 不设市值过滤</Badge>
            <Badge tone="muted">题材热度默认 10%</Badge>
            <Badge tone="muted">仅研究输出，不下单</Badge>
          </div>
          <Button loading={busy} disabled={busy} onClick={handleCreate} type="button">
            保存量化策略版本
          </Button>
        </div>
        {error ? (
          <p className="text-xs text-negative" role="alert">
            {error}
          </p>
        ) : null}
        {success ? (
          <p className="text-xs text-positive" role="status">
            {success}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="grid gap-1 rounded-md border border-border bg-muted/40 px-3 py-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <strong className="text-sm font-semibold text-foreground">{value}</strong>
    </div>
  );
}

function NumberField({
  label,
  onChange,
  step = 1,
  value,
}: {
  label: string;
  onChange: (value: number) => void;
  step?: number;
  value: number;
}) {
  return (
    <div className="grid gap-1.5">
      <Label>{label}</Label>
      <Input
        aria-label={label}
        step={step}
        type="number"
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </div>
  );
}

function buildThresholds(
  defaults: QuantStrategyDefaults,
  universe: string,
  preset: QuantStrategyPreset,
  values: {
    buyThreshold: number;
    minAmount: number;
    sellThreshold: number;
    weighting: string;
    weights: Record<string, number>;
  },
) {
  return {
    profile: defaults.profile,
    default_universe: universe,
    execution_boundary: defaults.execution_boundary,
    presets: {
      ...defaults.presets,
      [universe]: {
        ...preset,
        buy_threshold: values.buyThreshold,
        sell_threshold: values.sellThreshold,
        min_avg_amount_20d: values.minAmount,
        weighting: values.weighting,
        factor_weights: values.weights,
        candidate_policy: {
          ...preset.candidate_policy,
          no_top_n: true,
          market_cap_filter: false,
        },
      },
    },
  };
}
