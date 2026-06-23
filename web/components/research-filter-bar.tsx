/**
 * @fileoverview Server-side GET filter bar for v0.2 research candidates.
 */

type ResearchFilterValues = {
  scope_version_id?: string;
  universe?: string;
  screening_status?: string;
  data_status?: string;
  review_required?: string;
  assessment_freshness?: string;
  query?: string;
};

type ResearchFilterBarProps = {
  defaultValues?: ResearchFilterValues;
};

const UNIVERSES = [
  ["ALL_A", "全 A"],
  ["HS300", "沪深 300"],
  ["CSI500", "中证 500"],
] as const;

const SCREENING_STATUSES = [
  ["", "全部状态"],
  ["pass", "PASS"],
  ["near_threshold", "NEAR_THRESHOLD"],
  ["watchlist", "WATCHLIST"],
  ["risk_flag", "RISK_FLAG"],
  ["data_insufficient", "DATA_INSUFFICIENT"],
] as const;

const DATA_STATUSES = [
  ["", "全部数据状态"],
  ["complete", "complete"],
  ["partial", "partial"],
  ["stale", "stale"],
  ["missing", "missing"],
] as const;

const REVIEW_REQUIRED = [
  ["", "全部"],
  ["true", "需要复核"],
  ["false", "无需复核"],
] as const;

const FRESHNESS = [
  ["", "全部新鲜度"],
  ["fresh", "fresh"],
  ["stale", "stale"],
  ["deferred", "deferred"],
] as const;

/**
 * Renders non-secret research candidate filters as a progressive-enhancement
 * GET form. The form drives server pagination and keeps filter state in URL
 * query parameters only.
 */
export function ResearchFilterBar({
  defaultValues = {},
}: ResearchFilterBarProps) {
  return (
    <section className="panel research-filter-panel" aria-labelledby="research-filters-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Server filters</p>
          <h2 id="research-filters-title">研究候选筛选</h2>
        </div>
        <span>URL state</span>
      </div>
      <form action="/research" className="research-filter-form" method="get">
        <label className="form-field">
          <span>Scope 版本</span>
          <input
            aria-label="Scope 版本"
            name="scope_version_id"
            required
            type="text"
            defaultValue={defaultValues.scope_version_id ?? "scope-current"}
          />
        </label>
        <label className="form-field">
          <span>公司池</span>
          <select
            aria-label="公司池"
            name="universe"
            defaultValue={defaultValues.universe ?? "ALL_A"}
          >
            {UNIVERSES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          <span>量化状态</span>
          <select
            aria-label="量化状态"
            name="screening_status"
            defaultValue={defaultValues.screening_status ?? ""}
          >
            {SCREENING_STATUSES.map(([value, label]) => (
              <option key={label} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          <span>数据状态</span>
          <select
            aria-label="数据状态"
            name="data_status"
            defaultValue={defaultValues.data_status ?? ""}
          >
            {DATA_STATUSES.map(([value, label]) => (
              <option key={label} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          <span>复核要求</span>
          <select
            aria-label="复核要求"
            name="review_required"
            defaultValue={defaultValues.review_required ?? ""}
          >
            {REVIEW_REQUIRED.map(([value, label]) => (
              <option key={label} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field">
          <span>结论新鲜度</span>
          <select
            aria-label="结论新鲜度"
            name="assessment_freshness"
            defaultValue={defaultValues.assessment_freshness ?? ""}
          >
            {FRESHNESS.map(([value, label]) => (
              <option key={label} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="form-field research-query-field">
          <span>搜索</span>
          <input
            aria-label="搜索"
            name="query"
            placeholder="代码、名称或状态"
            type="search"
            defaultValue={defaultValues.query ?? ""}
          />
        </label>
        <div className="research-filter-actions">
          <button className="primary-button" type="submit">
            应用筛选
          </button>
          <a className="secondary-link" href="/research">
            清空
          </a>
        </div>
      </form>
    </section>
  );
}
