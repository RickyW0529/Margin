"use client";

/**
 * @fileoverview Current review vs effective assessment panel for v0.2 detail.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useLanguage, type UiLanguage } from "@/lib/i18n";

type CurrentReview = {
  outcome?: unknown;
  reason?: unknown;
};

type EffectiveAssessment = {
  freshness?: unknown;
  stale_reason?: unknown;
};

type CurrentVsEffectivePanelProps = {
  currentReview: CurrentReview | null;
  effectiveAssessment: EffectiveAssessment | null;
};

/** Renders the distinction between this run's review and the effective thesis. */
export function CurrentVsEffectivePanel({
  currentReview,
  effectiveAssessment,
}: CurrentVsEffectivePanelProps) {
  const { language, t } = useLanguage();
  const outcome = text(currentReview?.outcome) || "unknown";
  const reason = text(currentReview?.reason);
  const freshness = text(effectiveAssessment?.freshness) || "unknown";
  const staleReason = text(effectiveAssessment?.stale_reason);

  return (
    <Card aria-labelledby="current-effective-title">
      <CardHeader>
        <CardTitle id="current-effective-title">{t("currentStateTitle")}</CardTitle>
        <Badge tone={freshnessTone(freshness)}>
          {freshnessLabel(freshness, language)}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-2">
        <article className="grid gap-1.5 rounded-md border border-border bg-muted/40 p-4">
          <strong className="text-sm font-semibold text-foreground">
            {t("currentReview")}：{outcomeLabel(outcome, language)}
          </strong>
          <span className="text-xs leading-relaxed text-muted-foreground">
            {reason ? humanizeReason(reason, language) : t("currentNoReason")}
          </span>
        </article>
        <article className="grid gap-1.5 rounded-md border border-border bg-muted/40 p-4">
          <strong className="text-sm font-semibold text-foreground">
            {t("effectiveAssessment")}：{freshnessLabel(freshness, language)}
          </strong>
          <span className="text-xs leading-relaxed text-muted-foreground">
            {staleReason
              ? humanizeReason(staleReason, language)
              : freshness === "fresh"
                ? language === "zh"
                  ? "当前结论仍可作为展示依据。"
                  : "The current thesis is still usable."
                : t("currentNoAssessment")}
          </span>
        </article>
      </CardContent>
    </Card>
  );
}

function freshnessTone(freshness: string): "positive" | "caution" | "muted" {
  if (freshness === "fresh") {
    return "positive";
  }
  if (freshness === "stale" || freshness === "deferred") {
    return "caution";
  }
  return "muted";
}

function outcomeLabel(outcome: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    abstain: { en: "Abstained", zh: "拒绝结论" },
    carry_forward_verified: { en: "Carry forward", zh: "沿用已验证" },
    invalidate_thesis: { en: "Invalidated", zh: "失效候选" },
    review_deferred: { en: "Deferred", zh: "延期" },
    update_assessment: { en: "Updated", zh: "更新" },
    unknown: { en: "Unknown", zh: "未知" },
  };
  return labels[outcome]?.[language] ?? outcome;
}

function freshnessLabel(freshness: string, language: UiLanguage): string {
  const labels: Record<string, Record<UiLanguage, string>> = {
    deferred: { en: "Deferred", zh: "延期" },
    fresh: { en: "Fresh", zh: "有效" },
    stale: { en: "Stale", zh: "已过期" },
    unknown: { en: "Unknown", zh: "未知" },
  };
  return labels[freshness]?.[language] ?? freshness;
}

function humanizeReason(value: string, language: UiLanguage): string {
  const known: Record<string, Record<UiLanguage, string>> = {
    news_target_incomplete: {
      en: "News coverage for this review is incomplete.",
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
  if (!/[_-]/.test(value)) {
    return value;
  }
  return value.replace(/[_-]+/g, " ").trim();
}

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}
