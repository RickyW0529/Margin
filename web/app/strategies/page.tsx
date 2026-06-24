/**
 * @fileoverview Strategy templates and per-owner profile list page.
 */

import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchStrategies,
  fetchStrategyTemplates,
  type StrategyProfile,
  type StrategyTemplate,
} from "@/lib/api";

export const dynamic = "force-dynamic";

const DEFAULT_OWNER_ID = "local-admin";

/** Renders strategy templates plus the current owner's strategy profiles. */
export default async function StrategiesPage() {
  let templates: StrategyTemplate[] = [];
  let profiles: StrategyProfile[] = [];
  let error: string | null = null;

  const [templatesResult, profilesResult] = await Promise.allSettled([
    fetchStrategyTemplates(),
    fetchStrategies(DEFAULT_OWNER_ID),
  ]);

  templates = fulfilled(templatesResult);
  profiles = fulfilled(profilesResult);
  if (templatesResult.status === "rejected" && profilesResult.status === "rejected") {
    error = "策略接口暂时不可用";
  }

  return (
    <main className="mx-auto max-w-5xl space-y-6 px-10 py-9">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Strategies
          </p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            策略模板与版本管理
          </h1>
        </div>
        <div className="flex gap-2">
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            {templates.length} 模板
          </span>
          <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
            {profiles.length} 已创建
          </span>
        </div>
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
              Templates
            </p>
            <CardTitle className="mt-1">内置策略模板</CardTitle>
          </div>
          <span className="text-xs text-muted-foreground">
            GET /strategies/templates
          </span>
        </CardHeader>
        <CardContent className="grid gap-3">
          {templates.length === 0 ? (
            <div className="grid place-items-center rounded-md border border-dashed border-border py-6 text-sm text-muted-foreground">
              暂无模板
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-border">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/50 text-left">
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      template_id
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      名称
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      分类
                    </th>
                    <th className="px-3 py-2.5 text-xs font-semibold text-muted-foreground">
                      描述
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {templates.map((template) => (
                    <tr
                      key={template.template_id}
                      className="border-b border-border transition-colors last:border-b-0 hover:bg-muted/30"
                    >
                      <td className="px-3 py-3 font-mono text-xs text-foreground">
                        {template.template_id}
                      </td>
                      <td className="px-3 py-3 text-foreground">
                        {template.name}
                      </td>
                      <td className="px-3 py-3 text-xs text-muted-foreground">
                        {template.category}
                      </td>
                      <td className="px-3 py-3 text-xs text-muted-foreground">
                        {template.description}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-accent">
              Profiles
            </p>
            <CardTitle className="mt-1">已创建策略</CardTitle>
          </div>
          <span className="text-xs text-muted-foreground">
            owner {DEFAULT_OWNER_ID}
          </span>
        </CardHeader>
        <CardContent className="grid gap-2">
          {profiles.length === 0 ? (
            <div className="grid place-items-center rounded-md border border-dashed border-border py-6 text-sm text-muted-foreground">
              尚未创建策略
            </div>
          ) : (
            profiles.map((profile, index) => (
              <Link
                key={String(profile.strategy_id ?? index)}
                href={`/strategies/${encodeURIComponent(
                  String(profile.strategy_id ?? ""),
                )}`}
                className="flex items-center justify-between gap-3 rounded-md border border-border bg-muted/40 px-3 py-2.5 no-underline transition-colors hover:bg-card"
              >
                <div className="grid min-w-0 gap-0.5">
                  <strong className="truncate text-sm font-semibold text-foreground">
                    {String(
                      profile.name ?? profile.strategy_id ?? `策略 ${index + 1}`,
                    )}
                  </strong>
                  <span className="truncate text-xs text-muted-foreground">
                    {String(profile.description ?? "")}
                  </span>
                </div>
                <span className="shrink-0 font-mono text-xs text-muted-foreground">
                  {String(profile.strategy_id ?? "")}
                </span>
              </Link>
            ))
          )}
        </CardContent>
      </Card>
    </main>
  );
}

function fulfilled<T>(result: PromiseSettledResult<T[]>): T[] {
  return result.status === "fulfilled" ? result.value : [];
}
