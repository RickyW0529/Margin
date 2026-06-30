/**
 * @fileoverview Single Analysis Mart finding card.
 *
 * Displays severity badge, title, description, confidence bar, and evidence
 * reference chips in a compact card layout.
 */

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { formatPercent } from "@/lib/utils";

import type { AnalysisFinding } from "@/lib/api";

type FindingCardProps = {
  finding: AnalysisFinding;
};

const SEVERITY_TONES: Record<string, BadgeProps["tone"]> = {
  info: "accent",
  positive: "positive",
  warning: "caution",
  critical: "negative",
};

const SEVERITY_LABELS: Record<string, string> = {
  info: "信息",
  positive: "利好",
  warning: "警告",
  critical: "严重",
};

const FINDING_TYPE_LABELS: Record<string, string> = {
  value: "价值",
  quality: "质量",
  growth: "成长",
  momentum: "动量",
  risk: "风险",
  data_quality: "数据质量",
};

/** Renders one Analysis Mart finding in a card. */
export function FindingCard({ finding }: FindingCardProps) {
  const severityTone = SEVERITY_TONES[finding.severity] ?? "muted";
  const severityLabel = SEVERITY_LABELS[finding.severity] ?? finding.severity;
  const typeLabel = FINDING_TYPE_LABELS[finding.finding_type] ?? finding.finding_type;

  return (
    <Card>
      <CardContent className="grid gap-2.5">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <Badge tone="muted">{typeLabel}</Badge>
            <Badge tone={severityTone}>{severityLabel}</Badge>
          </div>
          <span className="text-xs text-muted-foreground">
            置信度 {formatPercent(finding.confidence)}
          </span>
        </div>
        <h4 className="text-sm font-semibold text-foreground">{finding.title}</h4>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {finding.description}
        </p>
        {finding.evidence_ids.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-xs text-muted-foreground">证据引用</span>
            {finding.evidence_ids.map((eid) => (
              <Badge key={eid} tone="muted">
                {eid.slice(0, 12)}
              </Badge>
            ))}
          </div>
        ) : null}
        <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
          <div
            className="h-full rounded-full bg-accent transition-all"
            style={{ width: `${Math.round(finding.confidence * 100)}%` }}
          />
        </div>
      </CardContent>
    </Card>
  );
}
