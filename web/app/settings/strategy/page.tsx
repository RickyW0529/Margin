/**
 * @fileoverview Strategy settings page.
 */

import {
  fetchQuantFeatureSets,
  fetchQuantStrategies,
  fetchStylePrompts,
  type VersionedConfigRecord,
} from "@/lib/api";

export const dynamic = "force-dynamic";

/** Renders active quant strategy, feature-set, and style-prompt versions. */
export default async function StrategySettingsPage() {
  const [strategies, featureSets, prompts] = await Promise.allSettled([
    fetchQuantStrategies(),
    fetchQuantFeatureSets(),
    fetchStylePrompts(),
  ]);

  return (
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="strategy-title">
        <div>
          <p className="eyebrow">Settings</p>
          <h1 id="strategy-title">Strategy 设置</h1>
        </div>
        <div className="status-strip">
          <span>versioned config</span>
          <span>activation audited</span>
        </div>
      </section>
      <section className="workspace-grid">
        <ConfigPanel title="量化策略" records={fulfilled(strategies)} />
        <ConfigPanel title="量化特征集" records={fulfilled(featureSets)} />
      </section>
      <ConfigPanel title="风格 Prompt" records={fulfilled(prompts)} />
    </main>
  );
}

function ConfigPanel({
  title,
  records,
}: {
  title: string;
  records: VersionedConfigRecord[];
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>{title}</h2>
        <span>{records.length} versions</span>
      </div>
      {records.length === 0 ? (
        <div className="empty-state compact">暂无版本</div>
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

function fulfilled<T>(result: PromiseSettledResult<T[]>): T[] {
  return result.status === "fulfilled" ? result.value : [];
}
