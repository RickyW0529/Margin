/**
 * @fileoverview Research scope settings page.
 */

import {
  fetchIndicatorViews,
  fetchResearchScopes,
  fetchUniverseConfigs,
  type VersionedConfigRecord,
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
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="scope-title">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 id="scope-title">Scope 设置</h1>
        </div>
        <div className="status-strip">
          <span>用户视图</span>
          <span>不改变量化必需特征</span>
        </div>
      </section>
      <section className="workspace-grid">
        <ConfigPanel
          title="公司池版本"
          records={fulfilled(universes)}
          empty="暂无公司池配置"
        />
        <ConfigPanel
          title="指标视图版本"
          records={fulfilled(indicators)}
          empty="暂无指标视图配置"
        />
      </section>
      <ConfigPanel
        title="冻结 Research Scope"
        records={fulfilled(scopes)}
        empty="暂无冻结 scope"
      />
    </main>
  );
}

function ConfigPanel({
  title,
  records,
  empty,
}: {
  title: string;
  records: VersionedConfigRecord[];
  empty: string;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        <span>{records.length} versions</span>
      </div>
      {records.length === 0 ? (
        <div className="empty-state compact">{empty}</div>
      ) : (
        <ul className="provider-list">
          {records.map((record, index) => (
            <li key={`${record.version_id ?? title}-${index}`}>
              <div>
                <strong>{record.version_id ?? `version-${index + 1}`}</strong>
                <span>{record.lifecycle ?? "unknown"}</span>
              </div>
              <span className="badge">{record.owner_id ?? "local-admin"}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function fulfilled<T>(
  result: PromiseSettledResult<T[]>,
): T[] {
  return result.status === "fulfilled" ? result.value : [];
}
