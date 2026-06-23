/**
 * @fileoverview Research item detail page.
 * Displays evidence, valuation, audit trace, report, and feedback for a research item.
 */

import { CurrentVsEffectivePanel } from "@/components/current-vs-effective-panel";
import { EvidenceLocatorList } from "@/components/evidence-locator-list";
import { ResearchFeedbackForm } from "@/components/research-feedback-form";
import { ResearchStatusBadge } from "@/components/research-status-badge";
import {
  fetchResearchItemDetailV2,
  type ResearchItemDetailV2,
} from "@/lib/api";

import { createResearchFeedbackAction } from "./actions";

/**
 * Props for the research item detail page.
 */
type ResearchItemPageProps = {
  params: Promise<{ itemId: string }>;
};

/**
 * Research item detail page that loads item data and binds the feedback action.
 * @param params - Route params containing the research item identifier.
 * @returns The rendered research item detail page.
 */
export default async function ResearchItemPage({ params }: ResearchItemPageProps) {
  const { itemId } = await params;
  let detail: ResearchItemDetailV2 | null = null;
  let error: string | null = null;

  const detailResult = await Promise.allSettled([fetchResearchItemDetailV2(itemId)]);

  if (detailResult[0].status === "fulfilled") {
    detail = detailResult[0].value;
  } else {
    error = "研究详情暂时不可用";
  }

  return (
    <main className="workspace-shell detail-shell">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">Research Item</p>
          <h1>{detail?.item.symbol ?? itemId}</h1>
        </div>
        {detail ? <ResearchStatusBadge status={detail.item.screening_status} /> : null}
      </section>

      {error ? (
        <div className="notice-panel" role="alert">{error}</div>
      ) : (
        <div className="side-rail">
          <section className="panel thesis-block">
            <div className="panel-heading">
              <h2>研究结论</h2>
              <span>
                {detail?.item.confidence == null
                  ? "--"
                  : `${(detail.item.confidence * 100).toFixed(0)}%`}
              </span>
            </div>
            <p>{safeText(detail?.thesis.statement) ?? "暂无结论"}</p>
            <div className="risk-line">
              <span>run {detail?.versions.run_id ?? "--"}</span>
              <span>snapshot {detail?.versions.snapshot_id ?? "--"}</span>
              <span>workflow {detail?.versions.workflow_run_id ?? "--"}</span>
            </div>
          </section>
          <CurrentVsEffectivePanel
            currentReview={detail?.current_review ?? null}
            effectiveAssessment={detail?.effective_assessment ?? null}
          />
          {detail ? <FactorSnapshotPanel detail={detail} /> : null}
          <EvidenceLocatorList evidence={detail?.evidence ?? []} />
          <ResearchFeedbackForm
            action={createResearchFeedbackAction.bind(null, itemId)}
          />
        </div>
      )}
    </main>
  );
}

function safeText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function FactorSnapshotPanel({ detail }: { detail: ResearchItemDetailV2 }) {
  return (
    <section className="panel" aria-labelledby="factor-snapshot-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Quant snapshot</p>
          <h2 id="factor-snapshot-title">量化与风险快照</h2>
        </div>
        <span>{detail.item.research_guardrail}</span>
      </div>
      <dl className="fact-list">
        <span>筛选状态</span>
        <strong>{detail.item.screening_status}</strong>
        <span>数据状态</span>
        <strong>{detail.item.data_status}</strong>
        <span>最终分数</span>
        <strong>{numberText(detail.item.final_score)}</strong>
        <span>折价率</span>
        <strong>{percentText(detail.item.discount_rate)}</strong>
        <span>风险标记</span>
        <strong>{detail.item.risk_flags.join(" / ") || "无"}</strong>
      </dl>
      <p className="helper-text">{safeJson(detail.factors)}</p>
    </section>
  );
}

function numberText(value: number | null): string {
  return value == null ? "--" : value.toFixed(2);
}

function percentText(value: number | null): string {
  return value == null ? "--" : `${(value * 100).toFixed(0)}%`;
}

function safeJson(value: Record<string, unknown>): string {
  try {
    return JSON.stringify(value);
  } catch {
    return "{}";
  }
}
