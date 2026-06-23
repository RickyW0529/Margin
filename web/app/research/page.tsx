/**
 * @fileoverview Research dashboard page.
 * Lists v0.2 valuation discovery candidates with server-side pagination and
 * retains operational controls for research runs and provider status in a
 * right rail.
 */

import { ProviderStatusPanel } from "@/components/provider-status-panel";
import { ReadOnlyCopilotPanel } from "@/components/read-only-copilot-panel";
import { ResearchFilterBar } from "@/components/research-filter-bar";
import { ResearchResultsTable } from "@/components/research-results-table";
import { ResearchRunForm } from "@/components/research-run-form";
import {
  fetchResearchCandidates,
  fetchProviderStatus,
  type ProviderStatus,
  type ResearchCandidateListResponse,
} from "@/lib/api";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

type ResearchDashboardPageProps = {
  searchParams?: Promise<SearchParams> | SearchParams;
};

/** Research dashboard page with filter rail and operational right rail. */
export default async function ResearchDashboardPage({
  searchParams,
}: ResearchDashboardPageProps = {}) {
  const params = await Promise.resolve(searchParams ?? {});
  const filterValues = {
    assessment_freshness: param(params, "assessment_freshness"),
    data_status: param(params, "data_status"),
    query: param(params, "query"),
    review_required: param(params, "review_required"),
    scope_version_id: param(params, "scope_version_id") || "scope-current",
    screening_status: param(params, "screening_status"),
    universe: param(params, "universe") || "ALL_A",
  };
  const cursor = param(params, "cursor");

  let candidates: ResearchCandidateListResponse | null = null;
  let providers: ProviderStatus[] = [];
  let candidateError: string | null = null;
  let operationalError: string | null = null;

  const [candidateResult, providersResult] =
    await Promise.allSettled([
      fetchResearchCandidates({
        ...filterValues,
        cursor,
        limit: Number(param(params, "limit") || 50),
      }),
      fetchProviderStatus(),
    ]);

  if (candidateResult.status === "fulfilled") {
    candidates = candidateResult.value;
  } else {
    candidateError = "研究候选列表暂时不可用";
  }
  if (providersResult.status === "fulfilled") {
    providers = providersResult.value;
  } else {
    operationalError = "Provider 状态暂时不可用";
  }

  return (
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="research-title">
        <div>
          <p className="eyebrow">Research</p>
          <h1 id="research-title">研究候选面板</h1>
        </div>
        <div className="status-strip">
          <span>不是买卖指令</span>
          <span>{filterValues.universe} 公司池</span>
          <span>{candidates?.items.length ?? 0} 个候选</span>
        </div>
      </section>

      {candidateError ? (
        <div className="notice-panel" role="alert">
          <span>{candidateError}</span>
        </div>
      ) : null}

      <ResearchFilterBar defaultValues={filterValues} />

      <section className="research-layout">
        <div className="research-main">
          <section className="panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Valuation discovery</p>
                <h2>全量底座上的用户可见研究候选</h2>
              </div>
              <span>
                {candidates
                  ? `${candidates.items.length} items · as of ${formatDate(
                      candidates.as_of,
                    )}`
                  : "0 items"}
              </span>
            </div>
            {candidates ? (
              <ResearchResultsTable
                items={candidates.items}
                pageInfo={candidates.page_info}
                scopeVersionId={candidates.scope_version_id}
                universe={filterValues.universe}
              />
            ) : (
              <div className="empty-state">候选列表未返回数据</div>
            )}
          </section>
        </div>
        <aside className="research-rail">
          {operationalError ? (
            <div className="notice-panel" role="alert">
              <span>{operationalError}</span>
            </div>
          ) : null}
          <ReadOnlyCopilotPanel
            scopeVersionId={filterValues.scope_version_id}
            universe={filterValues.universe}
          />
          <ResearchRunForm />
          <ProviderStatusPanel providers={providers} title="研究 Provider 状态" />
        </aside>
      </section>
    </main>
  );
}

function param(params: SearchParams, key: string): string {
  const value = params[key];
  if (Array.isArray(value)) {
    return value[0] ?? "";
  }
  return value ?? "";
}

function formatDate(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(parsed);
}