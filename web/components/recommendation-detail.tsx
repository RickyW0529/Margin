"use client";

/**
 * @fileoverview Recommendation detail view with quant visuals and evidence.
 */

import { CurrentVsEffectivePanel } from "@/components/current-vs-effective-panel";
import { EvidenceLocatorList } from "@/components/evidence-locator-list";
import { FactorScoreBar } from "@/components/factor-score-bar";
import { MetricTrendChart } from "@/components/metric-trend-chart";
import { MarkdownContent } from "@/components/markdown-content";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Stat } from "@/components/ui/stat";
import type {
  MetricTrend,
  RawMetricCard,
  ResearchItemDetailV2,
  ValuationState,
} from "@/lib/api";
import { useLanguage, type UiLanguage } from "@/lib/i18n";
import {
  recommendationReasonLabel,
  recommendationSourceLabel,
} from "@/lib/recommendation-labels";
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
    <section className="page-shell grid min-w-0 grid-cols-[minmax(0,1fr)] gap-8">
      <header className="flex min-w-0 flex-wrap items-start justify-between gap-5">
        <div className="min-w-0">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">
            {item.name}
          </h1>
          <p className="mt-2 text-base tabular text-muted-foreground">
            {item.symbol || item.security_id}
          </p>
        </div>
        <Badge tone={statusTone(item.screening_status)}>
          {statusLabel(item.screening_status, language)}
        </Badge>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label={t("detailConfidence")}
          value={formatPercentOne(
            reviewConfidence(detail.current_review, item.confidence),
          )}
          progress={Math.round(
            (reviewConfidence(detail.current_review, item.confidence) ?? 0) * 100,
          )}
        />
        <Stat
          label={language === "zh" ? "融合后仓位" : "Fused weight"}
          value={formatPercentOne(item.adjusted_weight)}
          progress={Math.round((item.adjusted_weight ?? 0) * 100)}
        />
        <Stat
          label={t("dashboardQuantScore")}
          value={formatScore(item.final_score)}
        />
        <Stat
          label={t("dashboardDiscount")}
          value={formatPercentOne(item.discount_rate)}
        />
      </div>

      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 lg:grid-cols-[minmax(0,1fr)_380px]">
        <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5">
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
            </CardHeader>
            <CardContent className="grid gap-3">
              <MarkdownContent
                className="text-sm leading-7"
                content={safeText(detail.thesis.statement) ?? t("detailNoConclusion")}
              />
              {reviewReason ? (
                <div className="rounded-xl border border-caution/15 bg-caution-soft px-3 py-2 text-sm text-caution">
                  {humanizeCode(reviewReason, language)}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <CurrentVsEffectivePanel
            currentReview={detail.current_review}
            effectiveAssessment={detail.effective_assessment}
          />
          <FusionDecisionCard item={item} language={language} />
          <EvidenceLocatorList evidence={detail.evidence} />
        </div>

        <aside className="grid min-w-0 grid-cols-[minmax(0,1fr)] content-start gap-5">
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
                {dataStatusLabel(item.data_status, language)}
              </Badge>
            </CardHeader>
            <CardContent className="grid gap-4">
              {factorEntries.length > 0 ? (
                <div className="grid gap-3">
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
                    {recommendationReasonLabel(flag, language)}
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

function FusionDecisionCard({
  item,
  language,
}: {
  item: ResearchItemDetailV2["item"];
  language: UiLanguage;
}) {
  const adjustment = item.agent_adjustment;
  if (!adjustment || Object.keys(adjustment).length === 0) {
    return null;
  }
  const reasons = Array.isArray(adjustment.reasons) ? adjustment.reasons : [];
  const sources = Array.isArray(adjustment.sources) ? adjustment.sources : [];
  return (
    <Card>
      <CardHeader>
        <div>
          <p className="text-xs font-medium tracking-[0.12em] text-accent uppercase">
            {language === "zh" ? "双路融合" : "Dual-path fusion"}
          </p>
          <CardTitle className="mt-1">
            {language === "zh" ? "推荐形成过程" : "How this recommendation was formed"}
          </CardTitle>
        </div>
        <Badge tone="positive">{language === "zh" ? "已复核" : "Reviewed"}</Badge>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <MetricTile
            label={language === "zh" ? "ML 量化贡献" : "ML contribution"}
            value={formatContribution(adjustment.quant_contribution)}
          />
          <MetricTile
            label={language === "zh" ? "财报催化贡献" : "Catalyst contribution"}
            value={formatContribution(adjustment.catalyst_contribution)}
          />
          <MetricTile
            label={language === "zh" ? "最终仓位" : "Final weight"}
            value={formatPercentOne(item.adjusted_weight, language)}
          />
        </div>
        {sources.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {sources.map((source) => (
              <Badge key={source} tone={source.includes("catalyst") ? "caution" : "accent"}>
                {recommendationSourceLabel(source, language)}
              </Badge>
            ))}
          </div>
        ) : null}
        {reasons.length > 0 ? (
          <ul className="grid list-disc gap-2 pl-5 text-sm leading-6 text-foreground marker:text-muted-foreground">
            {reasons.map((reason) => (
              <li key={reason}>{recommendationReasonLabel(reason, language)}</li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  );
}

function formatContribution(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
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
    <div className="grid min-w-0 gap-1.5 rounded-xl border border-border bg-muted/40 px-4 py-3.5">
      <span className="text-sm text-muted-foreground">{label}</span>
      <strong className="break-words text-[15px] font-semibold text-foreground">
        {value}
      </strong>
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

function factorLabel(value: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    final_score: { en: "Final score", zh: "最终分数" },
    quality: { en: "Quality", zh: "质量" },
    risk_score: { en: "Risk", zh: "风险" },
  };
  return labels[value]?.[language] ?? value;
}

function humanizeCode(value: string, language: UiLanguage): string {
  const known: Record<string, Record<UiLanguage, string>> = {
    news_target_incomplete: {
      en: "News coverage is still incomplete for this review.",
      zh: "本轮复核所需新闻尚未齐全。",
    },
    evidence_unavailable: {
      en: "Supporting evidence is not available yet.",
      zh: "支撑证据尚不可用。",
    },
  };
  if (known[value]) {
    return known[value][language];
  }
  if (!value.includes("_") && !value.includes("-")) {
    return value;
  }
  return value.replace(/[_-]+/g, " ").trim();
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
