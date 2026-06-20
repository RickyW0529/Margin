/**
 * @fileoverview Research item detail page.
 * Displays evidence, valuation, audit trace, report, and feedback for a research item.
 */

import { EvidencePanel } from "@/components/evidence-panel";
import { ReportPanel } from "@/components/report-panel";
import { ResearchFeedbackForm } from "@/components/research-feedback-form";
import { ResearchStatusBadge } from "@/components/research-status-badge";
import { ValuationPanel } from "@/components/valuation-panel";
import {
  fetchResearchItem,
  fetchResearchItemAudit,
  fetchResearchItemEvidence,
  fetchResearchItemExport,
  fetchResearchItemReport,
  fetchResearchItemValuation,
  type AuditView,
  type EvidenceView,
  type ReportExport,
  type ResearchReport,
  type ResearchItem,
  type ValuationView,
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
  let item: ResearchItem | null = null;
  let evidence: EvidenceView | null = null;
  let valuation: ValuationView | null = null;
  let audit: AuditView | null = null;
  let report: ResearchReport | null = null;
  let exported: ReportExport | null = null;
  let error: string | null = null;

  try {
    [item, evidence, valuation, audit, report, exported] = await Promise.all([
      fetchResearchItem(itemId),
      fetchResearchItemEvidence(itemId),
      fetchResearchItemValuation(itemId),
      fetchResearchItemAudit(itemId),
      fetchResearchItemReport(itemId),
      fetchResearchItemExport(itemId, "json"),
    ]);
  } catch {
    error = "研究详情暂时不可用";
  }

  return (
    <main className="workspace-shell detail-shell">
      <section className="workspace-header">
        <div>
          <p className="eyebrow">Research Item</p>
          <h1>{item?.symbol ?? itemId}</h1>
        </div>
        {item ? <ResearchStatusBadge status={item.status} /> : null}
      </section>

      {error ? (
        <div className="notice-panel" role="alert">{error}</div>
      ) : (
        <div className="side-rail">
          <section className="panel thesis-block">
            <div className="panel-heading">
              <h2>研究结论</h2>
              <span>{item ? `${(item.confidence * 100).toFixed(0)}%` : "--"}</span>
            </div>
            <p>{item?.statement ?? "暂无结论"}</p>
            <div className="risk-line">
              <span>run {item?.run_id}</span>
              <span>snapshot {item?.snapshot_id ?? "--"}</span>
              <span>trace {audit?.trace_count ?? 0}</span>
            </div>
          </section>
          <ValuationPanel valuation={valuation} />
          <EvidencePanel evidence={evidence} />
          <ReportPanel report={report} exported={exported} />
          <ResearchFeedbackForm
            action={createResearchFeedbackAction.bind(null, itemId)}
          />
        </div>
      )}
    </main>
  );
}
