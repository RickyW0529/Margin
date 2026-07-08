"use client";

/**
 * @fileoverview Language-aware recommendation dashboard view.
 */

import Link from "next/link";

import { DashboardRefreshControl } from "@/components/dashboard-refresh-control";
import { Badge } from "@/components/ui/badge";
import type {
  ResearchCandidateListItemV2,
  ResearchCandidateListResponse,
} from "@/lib/api";
import { useLanguage, type UiLanguage } from "@/lib/i18n";
import { cn, formatDate, formatScore } from "@/lib/utils";

type RecommendationDashboardViewProps = {
  candidates: ResearchCandidateListResponse | null;
};

/** Renders today's recommendations without exposing backend plumbing. */
export function RecommendationDashboardView({
  candidates,
}: RecommendationDashboardViewProps) {
  const { language, t } = useLanguage();
  const items = candidates?.items ?? [];
  const reviewCount = items.filter((item) => item.review_required).length;
  const averageConfidence =
    items.length === 0
      ? null
      : items.reduce((total, item) => total + (item.confidence ?? 0), 0) /
        items.length;

  return (
    <main className="mx-auto max-w-7xl space-y-6 px-6 py-8 md:px-10">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted-foreground">
            {formatDate(candidates?.as_of)}
          </p>
          <h1 className="mt-1 text-4xl font-semibold tracking-tight text-foreground">
            {t("dashboardTitle")}
          </h1>
        </div>
        <div className="grid justify-items-start gap-3 md:justify-items-end">
          <DashboardRefreshControl />
          <div className="flex flex-wrap gap-2 md:justify-end">
            <MetricPill label={t("dashboardCount")} value={`${items.length}`} />
            <MetricPill
              label={t("dashboardAvgConfidence")}
              value={formatPercentOne(averageConfidence, language)}
            />
            <MetricPill label={t("dashboardNeedsReview")} value={`${reviewCount}`} />
          </div>
        </div>
      </header>

      <section className="grid gap-3">
        {items.length > 0 ? (
          items.map((item, index) => (
            <RecommendationCard
              key={item.item_id}
              item={item}
              language={language}
              rank={index + 1}
            />
          ))
        ) : (
          <div className="rounded-lg border border-dashed border-border bg-card px-4 py-10 text-center text-sm text-muted-foreground">
            {t("dashboardEmpty")}
          </div>
        )}
      </section>
    </main>
  );
}

function RecommendationCard({
  item,
  language,
  rank,
}: {
  item: ResearchCandidateListItemV2;
  language: UiLanguage;
  rank: number;
}) {
  const { t } = useLanguage();
  const reasons = buildReasons(item, language, t);
  const detailHref = `/dashboard/items/${encodeURIComponent(item.item_id)}`;
  return (
    <article
      className={cn(
        "grid gap-4 rounded-lg border bg-card p-4 shadow-sm transition-colors md:grid-cols-[auto_minmax(0,1fr)_minmax(220px,260px)]",
        "border-border",
      )}
    >
      <div className="grid size-10 place-items-center rounded-md bg-muted text-sm font-semibold text-foreground">
        {rank}
      </div>
      <div className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Link
              href={detailHref}
              className="text-lg font-semibold text-foreground no-underline hover:text-accent"
            >
              {item.name}
            </Link>
            <p className="text-sm text-muted-foreground">{item.symbol}</p>
          </div>
          <Badge tone={statusTone(item.screening_status)}>
            {statusLabel(item.screening_status, language)}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          {reasons.map((reason) => (
            <span
              key={reason}
              className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground"
            >
              {reason}
            </span>
          ))}
        </div>
        {item.risk_flags.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            {t("dashboardRisk")}：{item.risk_flags.slice(0, 2).join(" / ")}
          </p>
        ) : null}
      </div>
      <div className="grid gap-2 rounded-md bg-muted/40 p-3 md:self-start">
        <MetricLine
          label={t("dashboardConfidence")}
          value={formatPercentOne(item.confidence, language)}
        />
        <MetricLine
          label={t("dashboardQuantScore")}
          value={formatScore(item.final_score)}
        />
        <MetricLine
          label={t("dashboardDiscount")}
          value={formatPercentOne(item.discount_rate, language)}
        />
        <Link
          href={detailHref}
          className="mt-1 text-xs font-medium text-accent no-underline hover:underline"
        >
          {t("dashboardDetail")}
        </Link>
      </div>
    </article>
  );
}

function MetricPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      <strong className="ml-2 text-sm text-foreground">{value}</strong>
    </div>
  );
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-sm">
      <span className="text-muted-foreground">{label} </span>
      <strong className="text-foreground">{value}</strong>
    </div>
  );
}

function buildReasons(
  item: ResearchCandidateListItemV2,
  language: UiLanguage,
  t: ReturnType<typeof useLanguage>["t"],
): string[] {
  const reasons = [
    item.data_status === "complete"
      ? t("dashboardDataComplete")
      : t("dashboardDataMissing"),
  ];
  if (item.review_required) {
    reasons.push(t("dashboardNeedsReview"));
  }
  if (item.current_review_outcome) {
    reasons.push(reviewOutcomeLabel(item.current_review_outcome, language));
  }
  return reasons.slice(0, 4);
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

function reviewOutcomeLabel(outcome: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    abstain: { en: "Abstained", zh: "放弃结论" },
    review_deferred: { en: "Deferred", zh: "延期" },
    update_assessment: { en: "Updated", zh: "已更新" },
  };
  return labels[outcome]?.[language] ?? outcome;
}

function statusTone(
  status: string,
): "positive" | "accent" | "caution" | "negative" | "muted" {
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

function formatPercentOne(
  value: number | null | undefined,
  language: UiLanguage,
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
