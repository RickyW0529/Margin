"use client";

/**
 * @fileoverview Form component for launching a v0.2 valuation refresh.
 * On success it navigates to the run detail page so the user can watch progress.
 */

import { useState } from "react";
import { useRouter } from "next/navigation";

import {
  startValuationDiscoveryRefresh,
  type ValuationDiscoveryRefreshCreate,
  type ValuationDiscoveryRefreshStart,
} from "@/lib/api";

/** Props for the ResearchRunForm component. */
type ResearchRunFormProps = {
  /** Refresh submission handler, injectable for tests. */
  startRefresh?: (
    refresh: ValuationDiscoveryRefreshCreate,
  ) => Promise<ValuationDiscoveryRefreshStart>;
};

/** Renders a scope-driven valuation-discovery refresh form. */
export function ResearchRunForm({
  startRefresh = startValuationDiscoveryRefresh,
}: ResearchRunFormProps = {}) {
  const router = useRouter();
  const [scopeVersionId, setScopeVersionId] = useState("scope-current");
  const [decisionAt, setDecisionAt] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const result = await startRefresh({
        scope_version_id: scopeVersionId.trim(),
        decision_at: decisionAt
          ? new Date(decisionAt).toISOString()
          : new Date().toISOString(),
      });
      router.push(`/research/runs/${result.run_id}`);
    } catch (caught) {
      const message =
        caught instanceof Error && caught.message.includes("Local admin session")
          ? "请先在右上角解锁管理员模式。"
          : "启动失败，请检查管理员会话、active scope、Provider 和后端任务队列。";
      setError(message);
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="research-run-form-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Valuation Discovery</p>
          <h2 id="research-run-form-title">启动估值发现刷新</h2>
        </div>
        <span>POST /api/v1/valuation-discovery/refreshes</span>
      </div>
      <form className="action-form" onSubmit={submit}>
        <div className="form-grid">
          <label className="form-field">
            <span>研究作用域版本</span>
            <input
              aria-label="研究作用域版本"
              name="scope_version_id"
              onChange={(event) => setScopeVersionId(event.target.value)}
              required
              value={scopeVersionId}
            />
          </label>
          <label className="form-field">
            <span>决策时间</span>
            <input
              aria-label="决策时间"
              name="decision_at"
              onChange={(event) => setDecisionAt(event.target.value)}
              type="datetime-local"
              value={decisionAt}
            />
          </label>
        </div>
        <p className="helper-text">
          公司池、指标视图、量化策略、Prompt 和工具权限均来自 active scope。
          这里不会按手工 symbol 跑旧研究工作流。
        </p>
        {error ? (
          <div className="notice-panel compact" role="alert">
            {error}
          </div>
        ) : null}
        <button className="primary-button" disabled={pending} type="submit">
          {pending ? "正在提交..." : "启动估值发现"}
        </button>
      </form>
    </section>
  );
}