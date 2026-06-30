/**
 * @fileoverview Quant overview card showing final score, status, guardrail.
 */

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { CompanyQuantProfile } from "@/lib/api";
import { formatDate, formatNumber } from "@/lib/utils";

type QuantOverviewCardProps = {
  profile: CompanyQuantProfile;
};

const GUARDRAIL_LABELS: Record<string, string> = {
  research_allowed: "允许研究",
  limited_research: "受限研究",
  research_blocked: "研究阻断",
  overheat_caution: "过热警惕",
  confidence_reduced: "置信度降低",
  thesis_recheck_required: "需重检论点",
};

const DATA_STATUS_LABELS: Record<string, string> = {
  ok: "完整",
  insufficient: "不足",
  pit_degraded: "PIT 降级",
};

const SCREENING_STATUS_LABELS: Record<string, string> = {
  pass: "通过",
  near_threshold: "接近阈值",
  watchlist: "观察名单",
  reject: "淘汰",
};

const SCREENING_STATUS_TONES: Record<string, BadgeProps["tone"]> = {
  pass: "positive",
  near_threshold: "accent",
  watchlist: "caution",
  reject: "negative",
};

/** Renders the quant screening overview card with headline metrics. */
export function QuantOverviewCard({ profile }: QuantOverviewCardProps) {
  const guardrailLabel = GUARDRAIL_LABELS[profile.research_guardrail] ?? profile.research_guardrail;
  const dataStatusLabel = DATA_STATUS_LABELS[profile.data_status] ?? profile.data_status;
  const screeningLabel = SCREENING_STATUS_LABELS[profile.screening_status] ?? profile.screening_status;
  const screeningTone = SCREENING_STATUS_TONES[profile.screening_status] ?? "muted";

  return (
    <Card>
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Quant overview
          </p>
          <CardTitle className="mt-1">量化概览</CardTitle>
        </div>
        <div className="flex items-center gap-2">
          <Badge tone={screeningTone}>{screeningLabel}</Badge>
          <Badge tone="muted">{guardrailLabel}</Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="最终分数" value={formatNumber(profile.final_score, 1)} highlight />
          <Stat label="总排名" value={profile.rank_overall == null ? "--" : `#${profile.rank_overall}`} />
          <Stat label="行业排名" value={profile.rank_in_industry == null ? "--" : `#${profile.rank_in_industry}`} />
          <Stat label="数据状态" value={dataStatusLabel} />
        </div>
        {profile.risk_flags.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-muted-foreground">风险标记</span>
            {profile.risk_flags.map((flag) => (
              <Badge key={flag} tone="caution">
                {flag}
              </Badge>
            ))}
          </div>
        ) : null}
        {profile.reason_summary ? (
          <p className="text-sm leading-relaxed text-foreground">
            {profile.reason_summary}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>run {profile.quant_run_id.slice(0, 16)}</span>
          <span>决策 {formatDate(profile.decision_at)}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function Stat({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: boolean;
}) {
  return (
    <div className="grid gap-1 rounded-md border border-border bg-muted/40 px-3 py-2.5">
      <span className="text-xs text-muted-foreground">{label}</span>
      <strong
        className={
          highlight
            ? "tabular text-lg font-semibold text-accent"
            : "tabular text-sm font-semibold text-foreground"
        }
      >
        {value}
      </strong>
    </div>
  );
}
