/**
 * @fileoverview Universe status page for v0.2 research candidates.
 */

import Link from "next/link";

import { fetchResearchCandidates, type ResearchCandidateListResponse } from "@/lib/api";

export const dynamic = "force-dynamic";

const DEFAULT_SCOPE_VERSION_ID =
  process.env.MARGIN_DEFAULT_SCOPE_VERSION_ID ?? "scope-current";

const UNIVERSES = [
  { code: "ALL_A", label: "全 A" },
  { code: "HS300", label: "沪深 300" },
  { code: "CSI500", label: "中证 500" },
] as const;

/** Renders company-pool status cards backed by the server-paginated candidate API. */
export default async function ResearchUniversePage() {
  const results = await Promise.allSettled(
    UNIVERSES.map((universe) =>
      fetchResearchCandidates({
        limit: 1,
        scope_version_id: DEFAULT_SCOPE_VERSION_ID,
        universe: universe.code,
      }),
    ),
  );

  return (
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="universe-title">
        <div>
          <p className="eyebrow">Universe</p>
          <h1 id="universe-title">公司池状态</h1>
        </div>
        <div className="status-strip">
          <span>{DEFAULT_SCOPE_VERSION_ID}</span>
          <span>server paginated</span>
        </div>
      </section>
      <section className="candidate-grid" aria-label="公司池列表">
        {UNIVERSES.map((universe, index) => {
          const result = results[index];
          const response =
            result?.status === "fulfilled" ? result.value : null;
          return (
            <UniverseCard
              key={universe.code}
              code={universe.code}
              label={universe.label}
              response={response}
            />
          );
        })}
      </section>
    </main>
  );
}

function UniverseCard({
  code,
  label,
  response,
}: {
  code: string;
  label: string;
  response: ResearchCandidateListResponse | null;
}) {
  const passCount = response?.facets.screening_status?.pass ?? 0;
  return (
    <article className="candidate-card">
      <div className="candidate-card-header">
        <div>
          <p className="eyebrow">Company pool</p>
          <h2>{label}</h2>
        </div>
        <span className={`badge ${response ? "positive" : "risk"}`}>
          {response ? "ready" : "unavailable"}
        </span>
      </div>
      <dl className="candidate-facts">
        <div>
          <dt>样本状态</dt>
          <dd>{response ? `${response.items.length} loaded` : "--"}</dd>
        </div>
        <div>
          <dt>PASS facet</dt>
          <dd>{passCount}</dd>
        </div>
      </dl>
      <Link
        className="secondary-link"
        href={`/research?scope_version_id=${encodeURIComponent(
          DEFAULT_SCOPE_VERSION_ID,
        )}&universe=${encodeURIComponent(code)}`}
      >
        查看候选
      </Link>
    </article>
  );
}
