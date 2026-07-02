/**
 * @fileoverview Recommendation detail view with quant visuals and evidence.
 */

import { CurrentVsEffectivePanel } from "@/components/current-vs-effective-panel";
import { EvidenceLocatorList } from "@/components/evidence-locator-list";
import { FactorScoreBar } from "@/components/factor-score-bar";
import { MetricTrendChart } from "@/components/metric-trend-chart";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  MetricTrend,
  RawMetricCard,
  ResearchItemDetailV2,
  ValuationState,
} from "@/lib/api";
import { formatNumber, formatScore } from "@/lib/utils";

type RecommendationDetailProps = {
  detail: ResearchItemDetailV2;
};

/** Renders a focused detail page for one dashboard recommendation. */
export function RecommendationDetail({ detail }: RecommendationDetailProps) {
  const item = detail.item;
  const aiStatus = safeText(detail.thesis.ai_status);
  const reviewReason = safeText(detail.current_review.reason);
  const valuation = detail.factors.valuation;
  const trends = detail.factors.trends ?? [];
  const rawMetrics = detail.factors.raw_metrics ?? [];
  const factorEntries = Object.entries(detail.factors).filter(
    ([, value]) => typeof value === "number",
  );

  return (
    <section className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4">
      <header className="flex min-w-0 flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm text-muted-foreground">推荐详情</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            {item.name}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{item.security_id}</p>
        </div>
        <Badge tone={statusTone(item.screening_status)}>
          {statusLabel(item.screening_status)}
        </Badge>
      </header>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>研究结论</CardTitle>
                {aiStatus ? (
                  <span className="mt-1 block text-xs text-muted-foreground">
                    AI 状态 {reviewStatusLabel(aiStatus)}
                  </span>
                ) : null}
              </div>
              <span className="text-xs text-muted-foreground">
                置信度 {formatPercentOne(reviewConfidence(detail.current_review, item.confidence))}
              </span>
            </CardHeader>
            <CardContent className="grid gap-3">
              <p className="text-sm leading-relaxed text-foreground">
                {safeText(detail.thesis.statement) ?? "暂无结论"}
              </p>
              {reviewReason ? (
                <div className="rounded-md border border-caution-soft bg-caution-soft px-3 py-2 text-sm text-caution">
                  {reviewReason}
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>scope {item.scope_version_id}</span>
                <span>snapshot {detail.versions.snapshot_id ?? "--"}</span>
              </div>
            </CardContent>
          </Card>

          <CurrentVsEffectivePanel
            currentReview={detail.current_review}
            effectiveAssessment={detail.effective_assessment}
          />
          <EvidenceLocatorList evidence={detail.evidence} />
        </div>

        <aside className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-4">
          <ValuationCard valuation={valuation} itemDiscount={item.discount_rate} />

          <Card>
            <CardHeader>
              <CardTitle>量化可视化</CardTitle>
              <Badge tone="muted">{item.research_guardrail}</Badge>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <MetricTile label="筛选状态" value={statusLabel(item.screening_status)} />
                <MetricTile label="数据状态" value={item.data_status} />
                <MetricTile label="最终分数" value={formatScore(item.final_score)} />
                <MetricTile label="置信度" value={formatPercentOne(item.confidence)} />
              </div>
              {factorEntries.length > 0 ? (
                <div className="grid gap-3 border-t border-border pt-3">
                  {factorEntries.map(([key, value]) => (
                    <FactorScoreBar key={key} label={key} value={value as number} />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">暂无因子快照。</p>
              )}
            </CardContent>
          </Card>

          <TrendCard trends={trends} rawMetrics={rawMetrics} />

          <Card>
            <CardHeader>
              <CardTitle>风险与复核</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2">
              {item.risk_flags.length > 0 ? (
                item.risk_flags.map((flag) => (
                  <Badge key={flag} tone="caution">
                    {flag}
                  </Badge>
                ))
              ) : (
                <p className="text-sm text-muted-foreground">暂无明显风险标记。</p>
              )}
            </CardContent>
          </Card>
        </aside>
      </div>
    </section>
  );
}

function ValuationCard({
  valuation,
  itemDiscount,
}: {
  valuation?: ValuationState;
  itemDiscount: number | null;
}) {
  const discount = valuation?.discount_rate ?? itemDiscount;
  const hasValuation = valuation?.status === "available" && discount != null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>估值折价</CardTitle>
        <Badge tone={hasValuation ? "positive" : "caution"}>
          {hasValuation ? "available" : "missing"}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-3">
        <MetricTile
          label="折价 / 安全边际"
          value={hasValuation ? formatPercentOne(discount) : "AI 估值未形成"}
        />
        {valuation?.intrinsic_value != null ? (
          <MetricTile
            label="内在价值"
            value={`¥${formatNumber(valuation.intrinsic_value, 2)}`}
          />
        ) : null}
        {valuation?.message ? (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {valuation.message}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function TrendCard({
  trends,
  rawMetrics,
}: {
  trends: MetricTrend[];
  rawMetrics: RawMetricCard[];
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>关键趋势</CardTitle>
        <span className="text-xs text-muted-foreground">
          {trends.length} series
        </span>
      </CardHeader>
      <CardContent className="grid gap-3">
        {trends.length > 0 ? (
          trends.slice(0, 4).map((trend) => (
            <MetricTrendChart key={trend.metric} trend={trend} />
          ))
        ) : (
          <div className="grid place-items-center rounded-md border border-dashed border-border py-8 text-sm text-muted-foreground">
            暂无趋势数据
          </div>
        )}
        {rawMetrics.length > 0 ? (
          <div className="grid gap-2 border-t border-border pt-3 sm:grid-cols-2">
            {rawMetrics.slice(0, 6).map((metric) => (
              <MetricTile
                key={metric.metric}
                label={metric.label}
                value={formatRawMetric(metric)}
              />
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

function MetricTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid min-w-0 gap-1 rounded-md border border-border bg-muted/40 px-3 py-2.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <strong className="break-words text-sm text-foreground">{value}</strong>
    </div>
  );
}

function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    pass: "通过",
    near_threshold: "接近阈值",
    watchlist: "观察",
    reject: "淘汰",
  };
  return labels[status] ?? status;
}

function statusTone(status: string): "positive" | "accent" | "caution" | "negative" | "muted" {
  if (status === "pass") {
    return "positive";
  }
  if (status === "near_threshold") {
    return "accent";
  }
  if (status === "watchlist") {
    return "caution";
  }
  if (status === "reject") {
    return "negative";
  }
  return "muted";
}

function reviewStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    update_assessment: "已更新",
    review_deferred: "延期",
    abstain: "放弃结论",
    evidence_unavailable: "证据不足",
    pending: "运行中",
  };
  return labels[status] ?? status;
}

function safeText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function reviewConfidence(
  currentReview: Record<string, unknown>,
  fallback: number | null,
): number | null {
  return typeof currentReview.confidence === "number"
    ? currentReview.confidence
    : fallback;
}

function formatPercentOne(value: number | null | undefined): string {
  if (value == null) {
    return "--";
  }
  return new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
    style: "percent",
  }).format(value);
}

function formatRawMetric(metric: RawMetricCard): string {
  if (metric.value == null) {
    return "--";
  }
  if (metric.unit === "%") {
    return `${formatNumber(metric.value, 1)}%`;
  }
  if (metric.unit === "CNY") {
    return `¥${formatNumber(metric.value, 2)}`;
  }
  if (metric.unit) {
    return `${formatNumber(metric.value, 2)} ${metric.unit}`;
  }
  return formatNumber(metric.value, 2);
}
