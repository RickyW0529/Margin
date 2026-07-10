"use client";

/**
 * @fileoverview Language-aware recommendation dashboard view.
 */

import Link from "next/link";
import { BrainCircuit, FileSearch2, GitMerge, Inbox, ShieldCheck } from "lucide-react";

import { DashboardRefreshControl } from "@/components/dashboard-refresh-control";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { Stat } from "@/components/ui/stat";
import type {
  ResearchCandidateListItemV2,
  ResearchCandidateListResponse,
} from "@/lib/api";
import { useLanguage, type UiLanguage } from "@/lib/i18n";
import {
  recommendationReasonLabel,
  recommendationSourceLabel,
} from "@/lib/recommendation-labels";
import { cn, formatDate, formatScore } from "@/lib/utils";

type RecommendationDashboardViewProps = {
  candidates: ResearchCandidateListResponse | null;
};

/** Renders today's recommendations without exposing backend plumbing. */
export function RecommendationDashboardView({
  candidates,
}: RecommendationDashboardViewProps) {
  const { language, t } = useLanguage();
  const loadFailed = candidates === null;
  const items = candidates?.items ?? [];
  const hasPublishedResults = Boolean(candidates?.portfolio_summary || items.length > 0);
  const reviewCount = items.filter((item) => item.review_required).length;
  const confidenceValues = items
    .map((item) => item.confidence)
    .filter((value): value is number => value != null);
  const averageConfidence =
    confidenceValues.length === 0
      ? null
      : confidenceValues.reduce((total, value) => total + value, 0) /
        confidenceValues.length;
  const computedStockWeight = items.reduce(
    (total, item) => total + (item.adjusted_weight ?? item.target_weight ?? 0),
    0,
  );
  const stockWeight =
    loadFailed || !hasPublishedResults
      ? null
      : candidates?.portfolio_summary?.stock_weight ?? computedStockWeight;
  const cashWeight =
    loadFailed || !hasPublishedResults || stockWeight == null
      ? null
      : candidates?.portfolio_summary?.cash_weight ?? Math.max(0, 1 - stockWeight);

  return (
    <main className="page-shell space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <h1 className="text-3xl font-semibold tracking-tight text-foreground">
            {t("dashboardTitle")}
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            {language === "zh"
              ? "量化模型与财报催化研究独立运行，由研究智能体完成反证复核与仓位融合。"
              : "Independent quant and earnings-catalyst workers, challenged and fused by the research agent."}
          </p>
          {candidates?.as_of ? (
            <p className="mt-2 text-xs tabular text-muted-foreground">
              {formatDate(candidates.as_of)}
            </p>
          ) : null}
        </div>
        <DashboardRefreshControl />
      </header>

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label={t("dashboardCount")} value={loadFailed ? "—" : items.length} />
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
        />
        <Stat
          label={language === "zh" ? "股票仓位" : "Equity exposure"}
          value={formatPortfolioPercent(stockWeight, language)}
          progress={stockWeight == null ? null : Math.round(Math.min(1, stockWeight) * 100)}
        />
        <Stat
          label={language === "zh" ? "现金仓位" : "Cash reserve"}
          value={formatPortfolioPercent(cashWeight, language)}
          progress={cashWeight == null ? null : Math.round(Math.min(1, cashWeight) * 100)}
        />
      </section>

      <section className="rounded-2xl border border-border bg-card p-5 shadow-xs" aria-label={language === "zh" ? "推荐生成链路" : "Recommendation pipeline"}>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="grid flex-1 gap-3 text-sm md:grid-cols-[minmax(0,1fr)_auto_minmax(12rem,0.7fr)] md:items-center">
            <div className="grid gap-2 sm:grid-cols-2">
              <PipelineLabel icon={BrainCircuit} label={language === "zh" ? "ML 量化分支" : "ML quant branch"} />
              <PipelineLabel icon={FileSearch2} label={language === "zh" ? "财报催化分支" : "Earnings catalyst branch"} />
            </div>
            <GitMerge className="mx-auto size-5 rotate-90 text-muted-foreground md:rotate-0" aria-hidden="true" />
            <PipelineLabel icon={ShieldCheck} label={language === "zh" ? "反证与仓位融合" : "Challenge & portfolio fusion"} />
          </div>
          {loadFailed ? (
            <Badge tone="negative">
              {language === "zh" ? "数据暂不可用" : "Data unavailable"}
            </Badge>
          ) : !hasPublishedResults ? (
            <Badge tone="muted">
              {language === "zh" ? "尚未运行" : "Not run yet"}
            </Badge>
          ) : reviewCount > 0 ? (
            <Badge tone="caution">
              {reviewCount} {t("dashboardNeedsReview")}
            </Badge>
          ) : (
            <Badge tone="positive">{language === "zh" ? "融合完成" : "Fusion complete"}</Badge>
          )}
        </div>
      </section>

      <section className="grid gap-4">
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
            title={
              loadFailed
                ? language === "zh" ? "推荐数据暂不可用" : "Recommendation data unavailable"
                : t("dashboardEmpty")
            }
            description={
              loadFailed
                ? language === "zh"
                  ? "读取推荐结果失败。你可以稍后重试，或启动新的研究任务。"
                  : "The recommendation result could not be loaded. Retry later or start a new research run."
                : language === "zh"
                  ? "完成一次研究刷新后，候选会显示在这里。"
                  : "Run a research refresh to populate today's list."
            }
          />
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
        "grid gap-5 rounded-2xl border border-border bg-card p-5 shadow-xs md:grid-cols-[auto_minmax(0,1fr)_minmax(220px,260px)] md:p-6",
      )}
    >
      <div className="grid size-11 place-items-center rounded-xl bg-muted text-sm font-semibold tabular text-foreground">
        {rank}
      </div>
      <div className="grid min-w-0 gap-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <Link
              href={detailHref}
              className="text-lg font-semibold tracking-tight text-foreground no-underline hover:underline"
            >
              {item.name}
            </Link>
            <p className="mt-1 text-[15px] tabular text-muted-foreground">
              {item.symbol}
            </p>
          </div>
          <Badge tone={statusTone(item.screening_status)}>
            {statusLabel(item.screening_status, language)}
          </Badge>
        </div>
        {reasons.length > 0 ? (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {reasons.join(" · ")}
          </p>
        ) : null}
        {Array.isArray(item.agent_adjustment?.reasons) && item.agent_adjustment.reasons.length > 0 ? (
          <p className="text-sm leading-relaxed text-foreground">
            {item.agent_adjustment.reasons
              .slice(0, 2)
              .map((reason) => recommendationReasonLabel(reason, language))
              .join("；")}
          </p>
        ) : null}
        <RecommendationSources item={item} language={language} />
        {item.risk_flags.length > 0 ? (
          <p className="text-sm text-muted-foreground">
            {t("dashboardRisk")}：
            {item.risk_flags
              .slice(0, 2)
              .map((flag) => recommendationReasonLabel(flag, language))
              .join(" / ")}
          </p>
        ) : null}
      </div>
      <div className="grid gap-2.5 border-t border-border pt-4 md:border-t-0 md:border-l md:pl-5 md:pt-0">
        <MetricLine
          label={language === "zh" ? "融合后仓位" : "Fused weight"}
          value={formatPortfolioPercent(item.adjusted_weight, language)}
        />
        {item.target_weight != null && item.target_weight !== item.adjusted_weight ? (
          <MetricLine
            label={language === "zh" ? "模型基础仓位" : "Model weight"}
            value={formatPortfolioPercent(item.target_weight, language)}
          />
        ) : null}
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
        <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
          <div
            className="h-full rounded-full bg-accent"
            style={{ width: `${Math.min(100, Math.max(0, (item.adjusted_weight ?? 0) * 100))}%` }}
          />
        </div>
        <Link
          href={detailHref}
          className="mt-2 text-sm font-medium text-accent no-underline hover:underline"
        >
          {t("dashboardDetail")}
        </Link>
      </div>
    </article>
  );
}

function PipelineLabel({ icon: Icon, label }: { icon: React.ElementType; label: string }) {
  return (
    <span className="inline-flex min-h-11 items-center gap-2 font-medium text-foreground">
      <span className="grid size-8 place-items-center rounded-xl bg-muted text-accent">
        <Icon className="size-4" />
      </span>
      {label}
    </span>
  );
}

function RecommendationSources({
  item,
  language,
}: {
  item: ResearchCandidateListItemV2;
  language: UiLanguage;
}) {
  const rawSources = item.agent_adjustment?.sources;
  const sources = Array.isArray(rawSources)
    ? rawSources
    : item.agent_adjustment?.source
      ? [item.agent_adjustment.source]
      : [];
  if (sources.length === 0) {
    return null;
  }
  return (
    <div className="flex flex-wrap gap-2" aria-label={language === "zh" ? "推荐来源" : "Recommendation sources"}>
      {sources.map((source) => (
        <Badge key={source} tone={source.toLowerCase().includes("catalyst") ? "caution" : "accent"}>
          {recommendationSourceLabel(source, language)}
        </Badge>
      ))}
    </div>
  );
}

function MetricLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 text-[15px]">
      <span className="text-muted-foreground">{label}</span>
      <strong className="tabular text-base font-semibold text-foreground">
        {value}
      </strong>
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

function formatPortfolioPercent(
  value: number | null | undefined,
  language: UiLanguage,
): string {
  if (value == null || Number.isNaN(value)) {
    return "—";
  }
  return new Intl.NumberFormat(language === "zh" ? "zh-CN" : "en-US", {
    maximumFractionDigits: 1,
    minimumFractionDigits: 1,
    style: "percent",
  }).format(value);
}
