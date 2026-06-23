/**
 * @fileoverview Valuation discovery run history page.
 * Renders recent refresh runs and links to per-run detail + polling.
 */

import Link from "next/link";

import {
  fetchValuationDiscoveryRuns,
  type ValuationDiscoveryRefreshSummary,
} from "@/lib/api";

export const dynamic = "force-dynamic";

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
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="runs-title">
        <div>
          <p className="eyebrow">Valuation discovery</p>
          <h1 id="runs-title">运行记录</h1>
        </div>
        <div className="status-strip">
          <span>{items.length} 条</span>
          <Link className="secondary-link" href="/research">
            返回研究候选
          </Link>
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
            <p className="eyebrow">History</p>
            <h2>最近刷新</h2>
          </div>
          <span>newest first</span>
        </div>
        {items.length === 0 ? (
          <div className="empty-state">暂无运行记录</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Run</th>
                  <th>状态</th>
                  <th>Scope</th>
                  <th>开始</th>
                  <th>完成</th>
                  <th aria-label="操作" />
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.run_id}>
                    <td className="symbol-cell">{item.run_id}</td>
                    <td>
                      <span className={`badge ${runBadgeClass(item.state)}`}>
                        {item.state}
                      </span>
                    </td>
                    <td>{item.scope_version_id || "--"}</td>
                    <td>{formatDate(item.started_at) || "--"}</td>
                    <td>{formatDate(item.finished_at) || "--"}</td>
                    <td>
                      <Link
                        className="table-link"
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
      </section>
    </main>
  );
}

function formatDate(value: string | null): string {
  if (!value) {
    return "";
  }
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

function runBadgeClass(state: string): string {
  if (state === "succeeded") {
    return "positive";
  }
  if (state === "failed_final" || state === "cancelled") {
    return "invalidated";
  }
  if (state.startsWith("waiting")) {
    return "watch";
  }
  return "";
}