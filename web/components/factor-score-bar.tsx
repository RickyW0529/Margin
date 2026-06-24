/**
 * @fileoverview Horizontal score bar for factor breakdowns.
 */

type FactorScoreBarProps = {
  value: number | null | undefined;
  label?: string;
  max?: number;
};

/** Renders a labelled progress bar for a 0-max numeric score. */
export function FactorScoreBar({
  value,
  label,
  max = 100,
}: FactorScoreBarProps) {
  const safe = value == null || Number.isNaN(value) ? null : value;
  const pct =
    safe == null ? 0 : Math.max(0, Math.min(100, (safe / max) * 100));
  return (
    <div className="w-full">
      {label ? (
        <div className="mb-1 flex items-baseline justify-between">
          <span className="text-xs text-muted-foreground">{label}</span>
          <span className="tabular text-xs text-foreground">
            {safe == null ? "--" : safe}
          </span>
        </div>
      ) : null}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full bg-accent transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}
