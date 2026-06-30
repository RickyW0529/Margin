/**
 * @fileoverview Single Analysis Mart metric row with percentile bars.
 *
 * Displays metric name, numeric value, direction, and dual percentile bars
 * (market and industry) in a compact row layout.
 */

import { formatNumber } from "@/lib/utils";

import type { AnalysisMetric } from "@/lib/api";

type MetricRowProps = {
  metric: AnalysisMetric;
};

const DIRECTION_LABELS: Record<string, string> = {
  higher: "越高越好",
  lower: "越低越好",
};

/** Renders one Analysis Mart metric with percentile bars. */
export function MetricRow({ metric }: MetricRowProps) {
  const marketPct = metric.percentile_market;
  const industryPct = metric.percentile_industry;
  const directionLabel = DIRECTION_LABELS[metric.direction] ?? metric.direction;
  const valueDisplay = metric.numeric_value == null
    ? "--"
    : `${formatNumber(metric.numeric_value, 2)}${metric.unit ?? ""}`;

  return (
    <div className="grid gap-2 border-b border-border py-3 last:border-b-0">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">
            {metric.metric_name}
          </p>
          <p className="text-xs text-muted-foreground">
            {metric.metric_group} · {directionLabel}
          </p>
        </div>
        <div className="flex shrink-0 items-baseline gap-3">
          <span className="tabular text-sm font-semibold text-foreground">
            {valueDisplay}
          </span>
        </div>
      </div>
      {(marketPct != null || industryPct != null) ? (
        <div className="grid gap-1.5">
          {marketPct != null ? (
            <PercentileBar label="市场" percentile={marketPct} rank={metric.rank_market} />
          ) : null}
          {industryPct != null ? (
            <PercentileBar label="行业" percentile={industryPct} rank={metric.rank_industry} />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PercentileBar({
  label,
  percentile,
  rank,
}: {
  label: string;
  percentile: number;
  rank: number | null;
}) {
  const pct = Math.max(0, Math.min(100, percentile));
  const tone =
    pct >= 66 ? "var(--positive)" : pct >= 33 ? "var(--caution)" : "var(--negative)";
  return (
    <div className="flex items-center gap-2">
      <span className="w-8 shrink-0 text-xs text-muted-foreground">{label}</span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${pct}%`, backgroundColor: tone }}
        />
      </div>
      <span className="tabular w-12 shrink-0 text-right text-xs text-muted-foreground">
        {percentile.toFixed(0)}%
        {rank != null ? ` (#${rank})` : ""}
      </span>
    </div>
  );
}
