/**
 * @fileoverview Valuation discovery run history page.
 */

import Link from "next/link";

import { Badge, type BadgeProps } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchValuationDiscoveryRuns,
  type ValuationDiscoveryRefreshSummary,
} from "@/lib/api";
import { formatDate } from "@/lib/utils";

export const dynamic = "force-dynamic";

function runTone(state: string): BadgeProps["tone"] {
  if (state === "succeeded") {
    return "positive";
  }
  if (state === "failed_final" || state === "cancelled") {
    return "negative";
  }
  if (state.startsWith("waiting") || state === "running" || state === "partial") {
    return "caution";
  }
  return "muted";
}

/** Renders the valuation-discovery run history, newest first. */
export default async function ResearchRunsPage() {
  let items: ValuationDiscoveryRefreshSummary[] = [];
  let error: string | null = null;

  try {
    const response = await fetchValuationDiscoveryRuns({ limit: 50 });
    items = response.items;
  } catch {
    error = "运行记录暂时不可用";
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-10 py-9">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Valuation discovery
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            运行记录
          </h1>
        </div>
        <Button asChild variant="secondary" size="sm">
          <Link href="/research">返回研究候选</Link>
        </Button>
      </header>

      {error ? (
        <div
          className="flex items-center gap-2 rounded-lg border border-negative-soft bg-negative-soft px-4 py-3 text-sm text-negative"
          role="alert"
        >
          {error}
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-accent">
              History
            </p>
            <CardTitle className="mt-1">最近刷新</CardTitle>
          </div>
          <span className="text-xs text-muted-foreground">newest first</span>
        </CardHeader>
        <CardContent className="grid gap-3">
          {items.length === 0 ? (
            <div className="grid place-items-center rounded-md border border-dashed border-border py-10 text-sm text-muted-foreground">
              暂无运行记录
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[720px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50 text-left">
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      Run
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      状态
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      Scope
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      开始
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      完成
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground" />
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr
                      key={item.run_id}
                      className="border-b border-border transition-colors last:border-b-0 hover:bg-muted/30"
                    >
                      <td className="px-3 py-3 font-mono text-xs text-foreground">
                        {item.run_id}
                      </td>
                      <td className="px-3 py-3">
                        <Badge tone={runTone(item.state)}>{item.state}</Badge>
                      </td>
                      <td className="px-3 py-3 text-xs text-muted-foreground">
                        {item.scope_version_id || "--"}
                      </td>
                      <td className="px-3 py-3 text-xs text-muted-foreground">
                        {formatDate(item.started_at)}
                      </td>
                      <td className="px-3 py-3 text-xs text-muted-foreground">
                        {formatDate(item.finished_at)}
                      </td>
                      <td className="px-3 py-3">
                        <Link
                          className="text-xs font-medium text-accent no-underline hover:underline"
                          href={`/research/runs/${encodeURIComponent(item.run_id)}`}
                        >
                          查看
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
