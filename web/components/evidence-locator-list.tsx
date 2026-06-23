/**
 * @fileoverview Escaped evidence locator list for v0.2 detail pages.
 */

import type { EvidenceLocatorListItem } from "@/lib/api";

type EvidenceLocatorListProps = {
  evidence: EvidenceLocatorListItem[];
};

/** Renders evidence locator rows without interpreting external text as HTML. */
export function EvidenceLocatorList({ evidence }: EvidenceLocatorListProps) {
  if (evidence.length === 0) {
    return <div className="empty-state compact">暂无 v0.2 证据定位</div>;
  }

  return (
    <section className="panel" aria-labelledby="evidence-locator-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Evidence package</p>
          <h2 id="evidence-locator-title">证据定位</h2>
        </div>
        <span>{evidence.length} locators</span>
      </div>
      <ul className="evidence-locator-list">
        {evidence.map((item) => (
          <li key={item.evidence_id}>
            <div>
              <strong>{item.title || item.evidence_id}</strong>
              <span>{item.locator}</span>
              <span>snapshot</span>
              <span>{item.snapshot_id || "--"}</span>
              {item.pit_timestamp ? <span>PIT {item.pit_timestamp}</span> : null}
            </div>
            <div className="evidence-locator-meta">
              <span className="badge positive">{item.source_level}</span>
              {item.source_url ? (
                <a
                  className="secondary-link"
                  href={item.source_url}
                  rel="noreferrer"
                  target="_blank"
                >
                  原文
                </a>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
