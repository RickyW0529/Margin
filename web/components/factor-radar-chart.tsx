"use client";

/**
 * @fileoverview Five-factor radar chart using recharts.
 *
 * Renders the five quant factor group scores (quality / value / growth /
 * momentum / risk) as a radar chart. Scores are 0-100. Missing scores are
 * treated as 0 but rendered with a distinct muted segment.
 */

import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

import type { FactorScoreItem } from "@/lib/api";

type FactorRadarChartProps = {
  factorScores: FactorScoreItem[];
  className?: string;
};

type RadarDatum = {
  label: string;
  score: number;
  raw: number | null;
};

/** Renders a five-factor radar chart for quant screening scores. */
export function FactorRadarChart({ factorScores, className }: FactorRadarChartProps) {
  const data: RadarDatum[] = factorScores.map((item) => ({
    label: item.label,
    score: item.score == null ? 0 : Math.max(0, Math.min(100, item.score)),
    raw: item.score,
  }));

  if (data.length === 0) {
    return (
      <div className={className}>
        <p className="text-sm text-muted-foreground">暂无因子分数数据</p>
      </div>
    );
  }

  return (
    <div className={className} style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer>
        <RadarChart data={data} outerRadius="72%">
          <PolarGrid stroke="var(--border)" />
          <PolarAngleAxis
            dataKey="label"
            tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 100]}
            tick={{ fill: "var(--muted-foreground)", fontSize: 10 }}
            tickCount={5}
            axisLine={false}
          />
          <Radar
            dataKey="score"
            stroke="var(--accent)"
            fill="var(--accent)"
            fillOpacity={0.18}
            strokeWidth={2}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: "calc(var(--radius) - 2px)",
              fontSize: 12,
              color: "var(--foreground)",
            }}
            formatter={(value, _name, item) => {
              const raw = (item as { payload?: RadarDatum })?.payload?.raw;
              return raw == null ? "缺失" : raw.toFixed(1);
            }}
            labelFormatter={(label) => `${label} 因子分数`}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
