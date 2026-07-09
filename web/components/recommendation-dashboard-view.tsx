"use client";

/**
 * @fileoverview Language-aware recommendation dashboard view.
 */

import Link from "next/link";
import { Inbox } from "lucide-react";

import { DashboardRefreshControl } from "@/components/dashboard-refresh-control";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { Sparkline } from "@/components/ui/sparkline";
import { Stat } from "@/components/ui/stat";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
  const scoreSeries = items
    .map((item) => item.final_score)
    .filter((value): value is number => typeof value === "number")
    .slice(0, 12);

  return (
    <TooltipProvider delayDuration={200}>
      <main className="page-shell space-y-8">
        <header className="flex flex-wrap items-end justify-between gap-6">
          <div className="min-w-0">
            <p className="text-[11px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
              {formatDate(candidates?.as_of)}
            </p>
            <h1 className="text-display mt-2 text-3xl text-foreground md:text-4xl">
              {t("dashboardTitle")}
            </h1>
          </div>
          <DashboardRefreshControl />
        </header>

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label={t("dashboardCount")}
            value={items.length}
            hint={language === "zh" ? "当前候选数量" : "Current candidates"}
          />
          <Stat
            label={t("dashboardAvgConfidence")}
            value={formatPercentOne(averageConfidence, language)}
            progress={
              averageConfidence == null
                ? null
                : Math.round(
                    (averageConfidence <= 1
                      ? averageConfidence
                      : averageConfidence / 100) * 100,
                  )
            }
            hint={
              language === "zh" ? "平均研究置信度" : "Average research confidence"
            }
          />
          <Stat
            label={t("dashboardNeedsReview")}
            value={reviewCount}
            delta={reviewCount > 0 ? reviewCount : 0}
            hint={language === "zh" ? "需人工复核" : "Needs human review"}
          />
          <div className="grid gap-2 rounded-2xl border border-border/90 bg-card p-4 shadow-xs">
            <p className="text-[11px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
              {language === "zh" ? "分数分布" : "Score pulse"}
            </p>
            <Sparkline
              values={
                scoreSeries.length >= 2
                  ? scoreSeries
                  : [0.4, 0.45, 0.5, 0.48, 0.55]
              }
            />
            <p className="text-xs text-muted-foreground">
              {language === "zh"
                ? "Top 候选量化分数走势"
                : "Top candidate score shape"}
            </p>
          </div>
        </section>

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
            <EmptyState
              icon={Inbox}
              title={t("dashboardEmpty")}
              description={
                language === "zh"
                  ? "完成一次研究刷新后，候选会显示在这里。"
                  : "Run a research refresh to populate today's list."
              }
            />
          )}
        </section>
      </main>
    </TooltipProvider>
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
        "grid gap-4 rounded-2xl border border-border/90 bg-card p-5 shadow-xs transition-all duration-150 md:grid-cols-[auto_minmax(0,1fr)_minmax(220px,250px)]",
        "hover:border-border hover:shadow-sm",
      )}
    >
      <div className="grid size-10 place-items-center rounded-xl bg-muted/80 text-[13px] font-semibold tabular text-foreground">
        {rank}
      </div>
      <div className="grid gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <HoverCard openDelay={120}>
              <HoverCardTrigger asChild>
                <Link
                  href={detailHref}
                  className="text-lg font-semibold tracking-tight text-foreground no-underline transition-colors hover:text-accent"
                >
                  {item.name}
                </Link>
              </HoverCardTrigger>
              <HoverCardContent align="start" className="w-80">
                <div className="grid gap-2">
                  <div>
                    <p className="text-sm font-semibold text-foreground">{item.name}</p>
                    <p className="text-xs tabular text-muted-foreground">{item.symbol}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div className="rounded-xl bg-muted/50 px-3 py-2">
                      <p className="text-muted-foreground">{t("dashboardConfidence")}</p>
                      <p className="mt-1 font-semibold tabular text-foreground">
                        {formatPercentOne(item.confidence, language)}
                      </p>
                    </div>
                    <div className="rounded-xl bg-muted/50 px-3 py-2">
                      <p className="text-muted-foreground">{t("dashboardQuantScore")}</p>
                      <p className="mt-1 font-semibold tabular text-foreground">
                        {formatScore(item.final_score)}
                      </p>
                    </div>
                  </div>
                  {item.risk_flags.length > 0 ? (
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {t("dashboardRisk")}：{item.risk_flags.slice(0, 3).join(" / ")}
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      {language === "zh" ? "暂无显著风险标记" : "No major risk flags"}
                    </p>
                  )}
                </div>
              </HoverCardContent>
            </HoverCard>
            <p className="mt-0.5 text-sm tabular text-muted-foreground">{item.symbol}</p>
          </div>
          <Badge tone={statusTone(item.screening_status)}>
            {statusLabel(item.screening_status, language)}
          </Badge>
        </div>
        <div className="flex flex-wrap gap-2">
          {reasons.map((reason) => (
            <Tooltip key={reason}>
              <TooltipTrigger asChild>
                <span className="rounded-full border border-border/70 bg-muted/50 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
                  {reason}
                </span>
              </TooltipTrigger>
              <TooltipContent>{reason}</TooltipContent>
            </Tooltip>
          ))}
        </div>
        {item.risk_flags.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            {t("dashboardRisk")}：{item.risk_flags.slice(0, 2).join(" / ")}
          </p>
        ) : null}
      </div>
      <div className="grid gap-2.5 rounded-xl bg-muted/35 p-3.5 md:self-start">
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
          className="mt-1 text-xs font-medium text-accent no-underline transition-opacity hover:opacity-80"
        >
          {t("dashboardDetail")}
        </Link>
      </div>
    </article>
  );
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <strong className="tabular font-semibold tracking-tight text-foreground">{value}</strong>
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
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  const percent = value <= 1 ? value * 100 : value;
  return `${percent.toFixed(1)}${language === "zh" ? "%" : "%"}`;
}
