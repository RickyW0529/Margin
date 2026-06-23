"use client";

/**
 * @fileoverview Strategy detail client component.
 *
 * Renders the strategy profile, its versions and lifecycle controls
 * (validate / backtest / paper-trade / activate / archive) plus a prompt
 * preview. Mutating actions re-fetch the profile so the lifecycle stays in
 * sync with the backend.
 */

import { useCallback, useState } from "react";
import Link from "next/link";

import {
  activateStrategyVersion,
  archiveStrategy,
  backtestStrategyVersion,
  fetchStrategyDetail,
  fetchStrategyPrompt,
  paperTradeStrategyVersion,
  validateStrategyVersion,
} from "@/lib/api";

type StrategyVersionLike = {
  version_id?: string;
  name?: string;
  state?: string;
  description?: string;
  created_at?: string;
};

type StrategyProfileLike = Record<string, unknown> & {
  strategy_id?: string;
  owner_id?: string;
  name?: string;
  active_version_id?: string;
  versions?: StrategyVersionLike[];
};

type StrategyDetailClientProps = {
  strategyId: string;
  initialProfile: StrategyProfileLike | null;
  initialError: string | null;
};

const LIFECYCLE_ORDER: Record<string, string> = {
  draft: "validate",
  validating: "validate",
  invalid: "validate",
  backtesting: "backtest",
  paper_trading: "paper-trade",
  active: "active",
};

export function StrategyDetailClient({
  strategyId,
  initialProfile,
  initialError,
}: StrategyDetailClientProps) {
  const [profile, setProfile] = useState<StrategyProfileLike | null>(initialProfile);
  const [error, setError] = useState<string | null>(initialError);
  const [pending, setPending] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [promptError, setPromptError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const next = await fetchStrategyDetail(strategyId);
      setProfile(next as StrategyProfileLike);
      setError(null);
    } catch {
      setError("策略刷新失败");
    }
  }, [strategyId]);

  async function runAction(
    key: string,
    fn: () => Promise<unknown>,
  ) {
    setPending(key);
    try {
      await fn();
      await reload();
    } catch {
      setError(`${key} 失败，请确认管理员会话与策略状态。`);
    } finally {
      setPending(null);
    }
  }

  async function showPrompt(versionId: string) {
    setPromptError(null);
    try {
      const response = await fetchStrategyPrompt(strategyId, versionId);
      setPrompt(response.prompt);
    } catch {
      setPromptError("Prompt 加载失败");
    }
  }

  const versions = profile?.versions ?? [];

  return (
    <main className="workspace-shell">
      <section className="workspace-header" aria-labelledby="strategy-title">
        <div>
          <p className="eyebrow">Strategy</p>
          <h1 id="strategy-title">{profile?.name ?? strategyId}</h1>
        </div>
        <div className="status-strip">
          <span>{profile?.strategy_id ?? ""}</span>
          <span>owner {String(profile?.owner_id ?? "")}</span>
          <Link className="secondary-link" href="/strategies">
            返回列表
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
            <p className="eyebrow">Versions</p>
            <h2>版本生命周期</h2>
          </div>
          <span>active {String(profile?.active_version_id ?? "--")}</span>
        </div>
        {versions.length === 0 ? (
          <div className="empty-state compact">暂无版本</div>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>version_id</th>
                  <th>名称</th>
                  <th>状态</th>
                  <th>创建</th>
                  <th>Prompt</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {versions.map((version) => {
                  const next = LIFECYCLE_ORDER[version.state ?? ""] ?? "done";
                  return (
                    <tr key={String(version.version_id)}>
                      <td className="symbol-cell">{version.version_id}</td>
                      <td>{version.name}</td>
                      <td>
                        <span className={`badge ${stateBadgeClass(version.state)}`}>
                          {version.state}
                        </span>
                      </td>
                      <td className="table-helper">{shortDate(version.created_at)}</td>
                      <td>
                        <button
                          className="table-link"
                          onClick={() => void showPrompt(String(version.version_id))}
                          type="button"
                        >
                          查看
                        </button>
                      </td>
                      <td>
                        <div className="research-filter-actions">
                          {next === "validate" ? (
                            <button
                              className="primary-button"
                              disabled={pending === "validate"}
                              onClick={() =>
                                void runAction("validate", () =>
                                  validateStrategyVersion(
                                    strategyId,
                                    String(version.version_id),
                                  ),
                                )
                              }
                              type="button"
                            >
                              {pending === "validate" ? "..." : "校验"}
                            </button>
                          ) : null}
                          {next === "backtest" ? (
                            <button
                              className="primary-button"
                              disabled={pending === "backtest"}
                              onClick={() =>
                                void runAction("backtest", () =>
                                  backtestStrategyVersion(
                                    strategyId,
                                    String(version.version_id),
                                  ),
                                )
                              }
                              type="button"
                            >
                              {pending === "backtest" ? "..." : "回测"}
                            </button>
                          ) : null}
                          {next === "paper-trade" ? (
                            <button
                              className="primary-button"
                              disabled={pending === "paper-trade"}
                              onClick={() =>
                                void runAction("paper-trade", () =>
                                  paperTradeStrategyVersion(
                                    strategyId,
                                    String(version.version_id),
                                  ),
                                )
                              }
                              type="button"
                            >
                              {pending === "paper-trade" ? "..." : "纸面"}
                            </button>
                          ) : null}
                          {next === "active" ? null : (
                            <button
                              className="secondary-button"
                              disabled={pending === "activate"}
                              onClick={() =>
                                void runAction("activate", () =>
                                  activateStrategyVersion(
                                    strategyId,
                                    String(version.version_id),
                                  ),
                                )
                              }
                              type="button"
                            >
                              {pending === "activate" ? "..." : "激活"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Prompt preview</p>
            <h2>合并 Prompt</h2>
          </div>
        </div>
        {promptError ? <p className="form-error">{promptError}</p> : null}
        {prompt ? (
          <div className="report-panel">
            <pre>{prompt}</pre>
          </div>
        ) : (
          <p className="helper-text">点击某版本的「查看」预览合并后的 Prompt。</p>
        )}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Danger zone</p>
            <h2>归档策略</h2>
          </div>
        </div>
        <button
          className="secondary-button"
          disabled={pending === "archive"}
          onClick={() =>
            void runAction("archive", () => archiveStrategy(strategyId))
          }
          type="button"
        >
          {pending === "archive" ? "归档中..." : "归档当前激活版本"}
        </button>
      </section>
    </main>
  );
}

function shortDate(value: string | undefined): string {
  if (!value) {
    return "--";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(parsed);
}

function stateBadgeClass(state: string | undefined): string {
  if (state === "active") {
    return "positive";
  }
  if (state === "archived" || state === "invalid" || state === "suspended") {
    return "invalidated";
  }
  if (state === "validating" || state === "backtesting" || state === "paper_trading") {
    return "watch";
  }
  return "";
}