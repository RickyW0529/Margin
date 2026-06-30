/**
 * @fileoverview Rejection / review reasons panel for quant screening results.
 *
 * Shows review_reasons, reason_summary, and risk_flags in a structured panel.
 * PASS companies display a positive "no rejection reasons" state.
 */

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type RejectionReasonPanelProps = {
  screeningStatus: string;
  reviewRequired: boolean;
  reviewReasons: string[];
  riskFlags: string[];
  reasonSummary: string;
};

const REVIEW_REASON_LABELS: Record<string, string> = {
  data_status_not_ok: "数据状态不达标",
  risk_score_below_40: "风险分数低于 40",
  quality_score_below_50: "质量分数低于 50",
  overheat: "短期过热",
};

/** Renders the rejection / review reasons panel. */
export function RejectionReasonPanel({
  screeningStatus,
  reviewRequired,
  reviewReasons,
  riskFlags,
  reasonSummary,
}: RejectionReasonPanelProps) {
  const isPassed = screeningStatus === "pass";
  const hasReasons = reviewReasons.length > 0 || riskFlags.length > 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle>筛选原因与风险</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        {isPassed && !hasReasons ? (
          <div className="flex items-center gap-2 rounded-md border border-positive-soft bg-positive-soft px-3 py-2.5">
            <Badge tone="positive">通过</Badge>
            <span className="text-sm text-foreground">
              该公司通过全部硬性筛选，无淘汰原因。
            </span>
          </div>
        ) : null}

        {reviewReasons.length > 0 ? (
          <div className="grid gap-1.5">
            <span className="text-xs text-muted-foreground">复核原因</span>
            <div className="flex flex-wrap gap-1.5">
              {reviewReasons.map((reason) => (
                <Badge key={reason} tone="caution">
                  {REVIEW_REASON_LABELS[reason] ?? reason}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}

        {riskFlags.length > 0 ? (
          <div className="grid gap-1.5">
            <span className="text-xs text-muted-foreground">风险标记</span>
            <div className="flex flex-wrap gap-1.5">
              {riskFlags.map((flag) => (
                <Badge key={flag} tone="negative">
                  {flag}
                </Badge>
              ))}
            </div>
          </div>
        ) : null}

        {reviewRequired ? (
          <p className="text-xs text-muted-foreground">
            该公司标记为需要人工复核。
          </p>
        ) : null}

        {reasonSummary ? (
          <div className="grid gap-1.5 border-t border-border pt-3">
            <span className="text-xs text-muted-foreground">原因摘要</span>
            <p className="text-sm leading-relaxed text-foreground">{reasonSummary}</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
