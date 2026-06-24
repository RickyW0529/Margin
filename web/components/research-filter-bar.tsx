/**
 * @fileoverview Server-side GET filter bar for v0.2 research candidates.
 */

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

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

/** Renders non-secret research filters as a GET form driving URL state. */
export function ResearchFilterBar({ defaultValues = {} }: ResearchFilterBarProps) {
  return (
    <section
      className="rounded-lg border border-border bg-card p-4"
      aria-labelledby="research-filters-title"
    >
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            Server filters
          </p>
          <h2
            id="research-filters-title"
            className="mt-1 text-sm font-semibold text-foreground"
          >
            研究候选筛选
          </h2>
        </div>
        <span className="text-xs text-muted-foreground">URL state</span>
      </div>
      <form action="/research" className="grid grid-cols-2 gap-3 md:grid-cols-4" method="get">
        <div className="grid gap-1.5">
          <Label>Scope 版本</Label>
          <Input
            aria-label="Scope 版本"
            name="scope_version_id"
            required
            type="text"
            defaultValue={defaultValues.scope_version_id ?? "scope-current"}
          />
        </div>
        <div className="grid gap-1.5">
          <Label>公司池</Label>
          <Select
            aria-label="公司池"
            name="universe"
            defaultValue={defaultValues.universe ?? "ALL_A"}
          >
            {UNIVERSES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label>量化状态</Label>
          <Select
            aria-label="量化状态"
            name="screening_status"
            defaultValue={defaultValues.screening_status ?? ""}
          >
            {SCREENING_STATUSES.map(([value, label]) => (
              <option key={label} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label>数据状态</Label>
          <Select
            aria-label="数据状态"
            name="data_status"
            defaultValue={defaultValues.data_status ?? ""}
          >
            {DATA_STATUSES.map(([value, label]) => (
              <option key={label} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label>复核要求</Label>
          <Select
            aria-label="复核要求"
            name="review_required"
            defaultValue={defaultValues.review_required ?? ""}
          >
            {REVIEW_REQUIRED.map(([value, label]) => (
              <option key={label} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label>结论新鲜度</Label>
          <Select
            aria-label="结论新鲜度"
            name="assessment_freshness"
            defaultValue={defaultValues.assessment_freshness ?? ""}
          >
            {FRESHNESS.map(([value, label]) => (
              <option key={label} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5 md:col-span-2">
          <Label>搜索</Label>
          <Input
            aria-label="搜索"
            name="query"
            placeholder="代码、名称或状态"
            type="search"
            defaultValue={defaultValues.query ?? ""}
          />
        </div>
        <div className="col-span-2 flex flex-wrap gap-2 md:col-span-4">
          <Button type="submit">应用筛选</Button>
          <Button asChild variant="secondary" type="button">
            <a href="/research">清空</a>
          </Button>
        </div>
      </form>
    </section>
  );
}
