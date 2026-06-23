/**
 * @fileoverview Strategy templates and per-owner profile list page.
 * Backed by GET /strategies/templates and GET /strategies?owner_id=.
 */

import Link from "next/link";

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
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="strategies-title">
        <div>
          <p className="eyebrow">Strategies</p>
          <h1 id="strategies-title">策略模板与版本管理</h1>
        </div>
        <div className="status-strip">
          <span>{templates.length} 模板</span>
          <span>{profiles.length} 已创建</span>
          <span>owner: {DEFAULT_OWNER_ID}</span>
        </div>
      </section>
      {error ? (
        <div className="notice-panel" role="alert">
          <span>{error}</span>
        </div>
      ) : null}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Templates</p>
            <h2>内置策略模板</h2>
          </div>
          <span>GET /strategies/templates</span>
        </div>
        {templates.length === 0 ? (
          <div className="empty-state compact">暂无模板</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>template_id</th>
                  <th>名称</th>
                  <th>分类</th>
                  <th>描述</th>
                </tr>
              </thead>
              <tbody>
                {templates.map((template) => (
                  <tr key={template.template_id}>
                    <td className="symbol-cell">{template.template_id}</td>
                    <td>{template.name}</td>
                    <td>{template.category}</td>
                    <td className="table-helper">{template.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Profiles</p>
            <h2>已创建策略</h2>
          </div>
          <span>owner {DEFAULT_OWNER_ID}</span>
        </div>
        {profiles.length === 0 ? (
          <div className="empty-state compact">尚未创建策略</div>
        ) : (
          <ul className="provider-list">
            {profiles.map((profile, index) => (
              <li key={String(profile.strategy_id ?? index)}>
                <div>
                  <Link
                    className="card-title-link"
                    href={`/strategies/${encodeURIComponent(
                      String(profile.strategy_id ?? ""),
                    )}`}
                  >
                    {String(profile.name ?? profile.strategy_id ?? `策略 ${index + 1}`)}
                  </Link>
                  <span>{String(profile.description ?? "")}</span>
                </div>
                <span className="badge">{String(profile.strategy_id ?? "")}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function fulfilled<T>(result: PromiseSettledResult<T[]>): T[] {
  return result.status === "fulfilled" ? result.value : [];
}