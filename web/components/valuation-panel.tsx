/**
 * @fileoverview Panel component that displays valuation ranges and value-trap
 * risk for a research item.
 */

import type { ValuationView } from "@/lib/api";

/** Props for the ValuationPanel component. */
type ValuationPanelProps = {
  /** Valuation view data, or null when unavailable. */
  valuation: ValuationView | null;
};

const currency = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const percent = new Intl.NumberFormat("zh-CN", {
  style: "percent",
  maximumFractionDigits: 0,
});

/**
 * Formats a valuation range as a localized currency string.
 *
 * @param range Tuple of low and high valuation values, or null.
 * @returns Formatted range or "--".
 */
function rangeText(range: [number, number] | null): string {
  return range ? `${currency.format(range[0])} – ${currency.format(range[1])}` : "--";
}

/**
 * Renders valuation ranges, value-trap score, and analyst notes.
 *
 * @param valuation Valuation view data to display.
 * @returns The valuation panel or an empty state.
 */
export function ValuationPanel({ valuation }: ValuationPanelProps) {
  if (!valuation) {
    return <div className="empty-state compact">估值数据暂不可用</div>;
  }

  return (
    <section className="panel" aria-labelledby="valuation-title">
      <div className="panel-heading">
        <h2 id="valuation-title">估值视图</h2>
        <span>{valuation.method ?? "unknown"}</span>
      </div>
      <dl className="fact-list">
        <span>基准估值区间</span>
        <strong>{rangeText(valuation.base_valuation_range)}</strong>
        <span>悲观估值区间</span>
        <strong>{rangeText(valuation.pessimistic_range)}</strong>
        <span>价值陷阱风险</span>
        <strong>
          {valuation.value_trap_score == null
            ? "--"
            : percent.format(valuation.value_trap_score)}
        </strong>
      </dl>
      <p className="helper-text">{valuation.notes}</p>
    </section>
  );
}
