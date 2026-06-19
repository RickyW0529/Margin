import type { EvidenceView } from "@/lib/api";

type EvidencePanelProps = {
  evidence: EvidenceView | null;
};

export function EvidencePanel({ evidence }: EvidencePanelProps) {
  if (!evidence || !evidence.locators_available) {
    return <div className="empty-state compact">证据暂不可用</div>;
  }

  const locators = Object.entries(evidence.evidence_by_level).flatMap(
    ([level, items]) => items.map((item) => ({ ...item, level })),
  );

  return (
    <section className="panel evidence-panel" aria-labelledby="evidence-title">
      <div className="panel-heading">
        <h2 id="evidence-title">证据展开</h2>
        <span>置信度 {(evidence.overall_confidence * 100).toFixed(0)}%</span>
      </div>

      <div className="evidence-grid">
        <div>
          <h3>结论与推断</h3>
          <ul className="condition-list">
            {evidence.claims.map((claim) => (
              <li key={claim.claim_id}>
                <strong>{claim.statement}</strong>
                <span>
                  {claim.fact_or_inference} · {(claim.confidence * 100).toFixed(0)}%
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>来源定位</h3>
          <ul className="event-list">
            {locators.map((locator) => (
              <li key={locator.evidence_id}>
                <span>
                  <strong>{locator.evidence_id}</strong>
                  {locator.section ? ` · ${locator.section}` : ""}
                  {locator.page ? ` · 第 ${locator.page} 页` : ""}
                  {locator.source_url ? (
                    <>
                      {" · "}
                      <a
                        className="table-link"
                        href={locator.source_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        原文
                      </a>
                    </>
                  ) : null}
                </span>
                <strong>{locator.source_level}</strong>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
