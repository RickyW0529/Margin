/**
 * @fileoverview Research scope settings page.
 */

import { CompanyPoolSelector } from "@/components/company-pool-selector";
import { ConfigVersionList } from "@/components/config-version-list";
import {
  fetchIndicatorViews,
  fetchResearchScopes,
  fetchUniverseConfigs,
} from "@/lib/api";

export const dynamic = "force-dynamic";

/** Renders company-pool, indicator-view, and frozen research-scope settings. */
export default async function ScopeSettingsPage() {
  const [universes, indicators, scopes] = await Promise.allSettled([
    fetchUniverseConfigs(),
    fetchIndicatorViews(),
    fetchResearchScopes(),
  ]);

  return (
    <main className="mx-auto max-w-4xl space-y-6 px-10 py-9">
      <header>
        <p className="text-xs font-medium uppercase tracking-wider text-accent">
          Settings
        </p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
          Scope 设置
        </h1>
        <p className="mt-1.5 text-sm text-muted-foreground">
          公司池、指标视图与冻结研究作用域均为 append-only 版本，激活后生成新研究作用域。
        </p>
      </header>
      <CompanyPoolSelector
        scopes={fulfilled(scopes)}
        universes={fulfilled(universes)}
      />
      <div className="grid gap-6 md:grid-cols-2">
        <ConfigVersionList
          title="指标视图版本"
          kind="indicator-views"
          records={fulfilled(indicators)}
          empty="暂无指标视图配置"
        />
      </div>
      <ConfigVersionList
        title="冻结 Research Scope"
        kind="research-scopes"
        records={fulfilled(scopes)}
        empty="暂无冻结 scope"
      />
    </main>
  );
}

function fulfilled<T>(result: PromiseSettledResult<T[]>): T[] {
  return result.status === "fulfilled" ? result.value : [];
}
