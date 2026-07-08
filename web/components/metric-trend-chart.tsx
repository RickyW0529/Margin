/**
 * @fileoverview Compact SVG trend chart for recommendation detail metrics.
 */

import type { MetricTrend } from "@/lib/api";
import { formatNumber } from "@/lib/utils";

type MetricTrendChartProps = {
  trend: MetricTrend;
};

const WIDTH = 280;
const HEIGHT = 88;
const PADDING_X = 8;
const PADDING_Y = 10;

/** Renders a compact trend line with stable dimensions. */
export function MetricTrendChart({ trend }: MetricTrendChartProps) {
  const points = trend.points.filter(
    (point): point is { date: string; value: number } =>
      typeof point.value === "number" && Number.isFinite(point.value),
  );
  const first = points[0] ?? null;
  const last = points.at(-1) ?? null;

  return (
    <div className="grid gap-2 rounded-md border border-border bg-muted/30 p-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="truncate text-xs font-medium text-foreground">
          {trend.label}
        </span>
        <span className="shrink-0 tabular-nums text-xs text-muted-foreground">
          {last ? formatTrendValue(last.value, trend.unit) : "--"}
        </span>
      </div>
      {points.length >= 2 && first !== null && last !== null ? (
        <>
          <svg
            aria-label={`${trend.label}趋势`}
            className="h-24 w-full text-accent"
            preserveAspectRatio="none"
            role="img"
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          >
            <line
              className="text-border"
              stroke="currentColor"
              strokeWidth="1"
              x1={PADDING_X}
              x2={WIDTH - PADDING_X}
              y1={HEIGHT - PADDING_Y}
              y2={HEIGHT - PADDING_Y}
            />
            <polyline
              fill="none"
              points={polyline(points)}
              stroke="currentColor"
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2.5"
            />
          </svg>
          <div className="flex justify-between gap-3 text-[11px] text-muted-foreground">
            <span className="min-w-0 truncate">
              {first.date} · {formatTrendValue(first.value, trend.unit)}
            </span>
            <span className="min-w-0 truncate text-right">
              {last.date} · {formatTrendValue(last.value, trend.unit)}
            </span>
          </div>
        </>
      ) : (
        <div className="grid h-24 place-items-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
          趋势数据不足
        </div>
      )}
    </div>
  );
}

function polyline(points: Array<{ value: number }>): string {
  const values = points.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const xStep = (WIDTH - PADDING_X * 2) / Math.max(points.length - 1, 1);
  return points
    .map((point, index) => {
      const x = PADDING_X + index * xStep;
      const y =
        HEIGHT - PADDING_Y - ((point.value - min) / range) * (HEIGHT - PADDING_Y * 2);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function formatTrendValue(value: number, unit?: string | null): string {
  if (unit === "%") {
    return `${formatNumber(value, 1)}%`;
  }
  if (unit === "CNY") {
    return `¥${formatNumber(value, 2)}`;
  }
  if (unit) {
    return `${formatNumber(value, 2)} ${unit}`;
  }
  return formatNumber(value, 2);
}
