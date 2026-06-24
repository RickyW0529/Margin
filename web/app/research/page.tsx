/**
 * @fileoverview Research dashboard page.
 * Lists v0.2 valuation discovery candidates with server-side pagination and
 * retains operational controls for research runs, provider status and a
 * read-only Copilot in a right rail.
 */

import { ProviderStatusPanel } from "@/components/provider-status-panel";
import { ReadOnlyCopilotPanel } from "@/components/read-only-copilot-panel";
import { ResearchFilterBar } from "@/components/research-filter-bar";
import { ResearchResultsTable } from "@/components/research-results-table";
import { ResearchRunForm } from "@/components/research-run-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchProviderStatus,
  fetchResearchCandidates,
  type ProviderStatus,
  type ResearchCandidateListResponse,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

type SearchParams = Record<string, string | string[] | undefined>;

type ResearchDashboardPageProps = {
  searchParams?: Promise<SearchParams> | SearchParams;
};

/** Research dashboard page with filter bar and operational right rail. */
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

  const [candidateResult, providersResult] = await Promise.allSettled([
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
  const candidateItems = candidates?.items ?? [];
  const reviewRequiredCount = candidateItems.filter(
    (item) => item.review_required,
  ).length;
  const staleCount = candidateItems.filter(
    (item) => item.assessment_freshness === "stale",
  ).length;
  const blockedProviderCount = providers.filter(
    (provider) =>
      !["healthy", "ready", "ok"].includes(provider.status.toLowerCase()),
  ).length;

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-10 py-9">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Research
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            研究候选面板
          </h1>
          <p className="mt-1.5 text-sm text-muted-foreground">
            作用域内全部公司均展示，不隐藏被淘汰公司 · 研究作用域 v2026.06
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            不是买卖指令
          </span>
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            {filterValues.universe} 公司池
          </span>
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            {candidateItems.length} 个候选
          </span>
        </div>
      </header>

      {candidateError ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
          role="alert"
        >
          {candidateError}
        </div>
      ) : null}

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <SummaryCard label="当前筛选" value={filterValues.universe} helper={filterValues.scope_version_id} />
        <SummaryCard label="需要复核" value={`${reviewRequiredCount}`} helper="AI/人工待确认" />
        <SummaryCard label="结论 stale" value={`${staleCount}`} helper="需关注有效结论指针" />
        <SummaryCard label="Provider blocker" value={`${blockedProviderCount}`} helper="影响刷新/证据链" />
      </section>

      <ResearchFilterBar defaultValues={filterValues} />

      <section className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid gap-4">
          <Card>
            <CardHeader>
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-accent">
                  Valuation discovery
                </p>
                <CardTitle className="mt-1">
                  全量底座上的用户可见研究候选
                </CardTitle>
              </div>
              <span className="text-xs text-muted-foreground">
                {candidates
                  ? `${candidates.items.length} items · as of ${formatDate(candidates.as_of)}`
                  : "0 items"}
              </span>
            </CardHeader>
            <CardContent>
              {candidates ? (
                <ResearchResultsTable
                  items={candidates.items}
                  pageInfo={candidates.page_info}
                  scopeVersionId={candidates.scope_version_id}
                  universe={filterValues.universe}
                />
              ) : (
                <div className="grid place-items-center rounded-md border border-dashed border-border py-10 text-sm text-muted-foreground">
                  候选列表未返回数据
                </div>
              )}
            </CardContent>
          </Card>
        </div>
        <aside className="grid gap-4">
          {operationalError ? (
            <div
              className="flex items-center gap-2 rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
              role="alert"
            >
              {operationalError}
            </div>
          ) : null}
          <ResearchRunForm />
          <ProviderStatusPanel providers={providers} title="研究 Provider 状态" />
          <ReadOnlyCopilotPanel
            scopeVersionId={filterValues.scope_version_id}
            universe={filterValues.universe}
          />
        </aside>
      </section>
    </main>
  );
}

function SummaryCard({
  label,
  value,
  helper,
}: {
  label: string;
  value: string;
  helper: string;
}) {
  return (
    <div className="grid gap-1.5 rounded-lg border border-border bg-card p-3.5 shadow-sm">
      <span className="text-xs font-medium text-muted-foreground">
        {label}
      </span>
      <strong className="text-xl font-semibold tracking-tight text-foreground">
        {value}
      </strong>
      <span className="text-xs text-muted-foreground">{helper}</span>
    </div>
  );
}

function param(params: SearchParams, key: string): string {
  const value = params[key];
  if (Array.isArray(value)) {
    return value[0] ?? "";
  }
  return value ?? "";
}
