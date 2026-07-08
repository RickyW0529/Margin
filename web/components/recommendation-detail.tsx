"use client";

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
import { useLanguage, type UiLanguage } from "@/lib/i18n";
import { formatNumber, formatScore } from "@/lib/utils";

type RecommendationDetailProps = {
  detail: ResearchItemDetailV2;
};

/** Renders a focused detail page for one dashboard recommendation. */
export function RecommendationDetail({ detail }: RecommendationDetailProps) {
  const { language, t } = useLanguage();
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
          <p className="text-sm text-muted-foreground">{t("detailRecommendation")}</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            {item.name}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">{item.security_id}</p>
        </div>
        <Badge tone={statusTone(item.screening_status)}>
          {statusLabel(item.screening_status, language)}
        </Badge>
      </header>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-4">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>{t("detailConclusion")}</CardTitle>
                {aiStatus ? (
                  <span className="mt-1 block text-xs text-muted-foreground">
                    {t("detailAiStatus")} {reviewStatusLabel(aiStatus, language)}
                  </span>
                ) : null}
              </div>
              <span className="text-xs text-muted-foreground">
                {t("detailConfidence")} {formatPercentOne(reviewConfidence(detail.current_review, item.confidence))}
              </span>
            </CardHeader>
            <CardContent className="grid gap-3">
              <p className="text-sm leading-relaxed text-foreground">
                {safeText(detail.thesis.statement) ?? t("detailNoConclusion")}
              </p>
              {reviewReason ? (
                <div className="rounded-md border border-caution-soft bg-caution-soft px-3 py-2 text-sm text-caution">
                  {reviewReason}
                </div>
              ) : null}
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                <span>
                  {t("detailScope")} {item.scope_version_id}
                </span>
                <span>
                  {t("detailSnapshot")} {detail.versions.snapshot_id ?? "--"}
                </span>
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
          <ValuationCard
            itemDiscount={item.discount_rate}
            labels={{
              currentState: t("detailValuationState"),
              intrinsicValue: t("detailIntrinsicValue"),
              margin: t("detailMargin"),
              missingReason: t("detailValuationMissingReason"),
              ready: t("detailValuationReady"),
              title: t("detailValuation"),
              unavailable: t("detailValuationUnavailable"),
              valuationMissing: t("detailValuationMissing"),
            }}
            valuation={valuation}
            language={language}
          />

          <Card>
            <CardHeader>
              <CardTitle>{t("detailQuantTitle")}</CardTitle>
              <Badge tone="muted">
                {guardrailLabel(item.research_guardrail, language)}
              </Badge>
            </CardHeader>
            <CardContent className="grid gap-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <MetricTile
                  label={t("detailScreeningStatus")}
                  value={statusLabel(item.screening_status, language)}
                />
                <MetricTile
                  label={t("detailDataStatus")}
                  value={dataStatusLabel(item.data_status, language)}
                />
                <MetricTile
                  label={t("detailFinalScore")}
                  value={formatScore(item.final_score)}
                />
                <MetricTile
                  label={t("detailConfidence")}
                  value={formatPercentOne(item.confidence, language)}
                />
              </div>
              {factorEntries.length > 0 ? (
                <div className="grid gap-3 border-t border-border pt-3">
                  {factorEntries.map(([key, value]) => (
                    <FactorScoreBar
                      key={key}
                      label={factorLabel(key, language)}
                      value={value as number}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("detailNoFactors")}
                </p>
              )}
            </CardContent>
          </Card>

          <TrendCard
            labels={{
              noTrends: t("detailNoTrends"),
              series: t("detailTrendSeries"),
              title: t("detailTrendTitle"),
            }}
            rawMetrics={rawMetrics}
            trends={trends}
          />

          <Card>
            <CardHeader>
              <CardTitle>{t("detailRiskTitle")}</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2">
              {item.risk_flags.length > 0 ? (
                item.risk_flags.map((flag) => (
                  <Badge key={flag} tone="caution">
                    {flag}
                  </Badge>
                ))
              ) : (
                <p className="text-sm text-muted-foreground">
                  {t("detailNoRisk")}
                </p>
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
  labels,
  language,
}: {
  valuation?: ValuationState;
  itemDiscount: number | null;
  language: UiLanguage;
  labels: {
    currentState: string;
    intrinsicValue: string;
    margin: string;
    missingReason: string;
    ready: string;
    title: string;
    unavailable: string;
    valuationMissing: string;
  };
}) {
  const discount = valuation?.margin_of_safety ?? valuation?.discount_rate ?? itemDiscount;
  const hasValuation = valuation?.status === "available" && discount != null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{labels.title}</CardTitle>
        <Badge tone={hasValuation ? "positive" : "caution"}>
          {hasValuation ? labels.ready : labels.valuationMissing}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-3">
        <MetricTile
          label={hasValuation ? labels.margin : labels.currentState}
          value={hasValuation ? formatPercentOne(discount, language) : labels.unavailable}
        />
        {valuation?.intrinsic_value != null ? (
          <MetricTile
            label={labels.intrinsicValue}
            value={formatCurrency(valuation.intrinsic_value)}
          />
        ) : null}
        {valuation?.message ? (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {valuation.message}
          </p>
        ) : !hasValuation ? (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {labels.missingReason}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function TrendCard({
  trends,
  rawMetrics,
  labels,
}: {
  trends: MetricTrend[];
  rawMetrics: RawMetricCard[];
  labels: {
    noTrends: string;
    series: string;
    title: string;
  };
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{labels.title}</CardTitle>
        <span className="text-xs text-muted-foreground">
          {trends.length} {labels.series}
        </span>
      </CardHeader>
      <CardContent className="grid gap-3">
        {trends.length > 0 ? (
          trends.slice(0, 4).map((trend) => (
            <MetricTrendChart key={trend.metric} trend={trend} />
          ))
        ) : (
          <div className="grid place-items-center rounded-md border border-dashed border-border py-8 text-sm text-muted-foreground">
            {labels.noTrends}
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

function statusLabel(status: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    near_threshold: { en: "Near threshold", zh: "接近阈值" },
    pass: { en: "Pass", zh: "通过" },
    reject: { en: "Rejected", zh: "淘汰" },
    watchlist: { en: "Watchlist", zh: "观察" },
  };
  return labels[status]?.[language] ?? status;
}

function dataStatusLabel(status: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    complete: { en: "Complete", zh: "完整" },
    missing: { en: "Missing", zh: "缺失" },
    partial: { en: "Partial", zh: "部分完整" },
  };
  return labels[status]?.[language] ?? status;
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

function reviewStatusLabel(status: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    abstain: { en: "Abstained", zh: "放弃结论" },
    evidence_unavailable: { en: "Evidence unavailable", zh: "证据不足" },
    pending: { en: "Running", zh: "运行中" },
    review_deferred: { en: "Deferred", zh: "延期" },
    update_assessment: { en: "Updated", zh: "已更新" },
  };
  return labels[status]?.[language] ?? status;
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

function formatPercentOne(
  value: number | null | undefined,
  language: UiLanguage = "zh",
): string {
  if (value == null) {
    return "--";
  }
  return new Intl.NumberFormat(language === "zh" ? "zh-CN" : "en-US", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
    style: "percent",
  }).format(value);
}

function guardrailLabel(value: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    allow_research: { en: "Research allowed", zh: "研究允许" },
    blocked: { en: "Blocked", zh: "已阻止" },
  };
  return labels[value]?.[language] ?? value;
}

function factorLabel(value: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    final_score: { en: "Final score", zh: "最终分数" },
    quality: { en: "Quality", zh: "质量" },
    risk_score: { en: "Risk", zh: "风险" },
  };
  return labels[value]?.[language] ?? value;
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

function formatCurrency(value: number): string {
  return `¥${new Intl.NumberFormat("zh-CN", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  }).format(value)}`;
}
