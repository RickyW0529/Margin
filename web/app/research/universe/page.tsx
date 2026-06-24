/**
 * @fileoverview Universe status page for v0.2 research candidates.
 */

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchResearchCandidates,
  type ResearchCandidateListResponse,
} from "@/lib/api";

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
    <main className="mx-auto max-w-5xl space-y-6 px-10 py-9">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Universe
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            公司池状态
          </h1>
        </div>
        <div className="flex gap-2">
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            {DEFAULT_SCOPE_VERSION_ID}
          </span>
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            server paginated
          </span>
        </div>
      </header>
      <section className="grid gap-4 md:grid-cols-3">
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
    <Card className="grid gap-4">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Company pool
          </p>
          <CardTitle className="mt-1">{label}</CardTitle>
        </div>
        <Badge tone={response ? "positive" : "negative"}>
          {response ? "ready" : "unavailable"}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-3">
        <dl className="grid grid-cols-2 gap-2">
          <div className="grid gap-1 rounded-md border border-border bg-muted/40 p-3">
            <dt className="text-xs text-muted-foreground">样本状态</dt>
            <dd className="text-sm font-semibold text-foreground">
              {response ? `${response.items.length} loaded` : "--"}
            </dd>
          </div>
          <div className="grid gap-1 rounded-md border border-border bg-muted/40 p-3">
            <dt className="text-xs text-muted-foreground">PASS facet</dt>
            <dd className="tabular text-sm font-semibold text-foreground">
              {passCount}
            </dd>
          </div>
        </dl>
        <Button asChild variant="secondary" size="sm">
          <Link
            href={`/research?scope_version_id=${encodeURIComponent(
              DEFAULT_SCOPE_VERSION_ID,
            )}&universe=${encodeURIComponent(code)}`}
          >
            查看候选
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}
