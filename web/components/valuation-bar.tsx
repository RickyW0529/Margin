/**
 * @fileoverview Intrinsic value range bar with current price marker.
 *
 * Renders only when all three numeric inputs are present; otherwise returns
 * null so detail pages without backend intrinsic-range data degrade quietly.
 */

type ValuationBarProps = {
  price: number | null | undefined;
  intrinsicLow: number | null | undefined;
  intrinsicHigh: number | null | undefined;
};

/** Intrinsic value range bar with current price marker. */
export function ValuationBar({
  price,
  intrinsicLow,
  intrinsicHigh,
}: ValuationBarProps) {
  if (
    price == null ||
    intrinsicLow == null ||
    intrinsicHigh == null ||
    intrinsicHigh <= intrinsicLow
  ) {
    return null;
  }

  const min = Math.min(price, intrinsicLow) * 0.92;
  const max = Math.max(price, intrinsicHigh) * 1.08;
  const pct = (v: number) => ((v - min) / (max - min)) * 100;

  return (
    <div className="py-6 pb-2">
      <div className="relative h-1.5 rounded-full bg-muted">
        <div
          className="absolute h-full rounded-full bg-positive-soft"
          style={{
            left: `${pct(intrinsicLow)}%`,
            width: `${pct(intrinsicHigh) - pct(intrinsicLow)}%`,
          }}
        />
        <Marker
          pct={pct(intrinsicLow)}
          label={`${intrinsicLow}`}
          sub="区间下沿"
        />
        <Marker
          pct={pct(intrinsicHigh)}
          label={`${intrinsicHigh}`}
          sub="区间上沿"
          align="right"
        />
        <div
          className="absolute -top-1 -translate-x-1/2"
          style={{ left: `${pct(price)}%` }}
        >
          <div className="size-3.5 rounded-full bg-primary ring-4 ring-background" />
          <div className="absolute top-5 left-1/2 -translate-x-1/2 whitespace-nowrap text-center">
            <div className="tabular text-sm text-foreground">¥{price}</div>
            <div className="text-xs text-muted-foreground">现价</div>
          </div>
        </div>
      </div>
      <div className="h-10" />
    </div>
  );
}

function Marker({
  pct,
  label,
  sub,
  align = "left",
}: {
  pct: number;
  label: string;
  sub: string;
  align?: "left" | "right";
}) {
  return (
    <div
      className="absolute -bottom-9"
      style={{
        left: `${pct}%`,
        transform: align === "right" ? "translateX(-100%)" : "none",
      }}
    >
      <div className="tabular text-xs text-positive">{label}</div>
      <div className="text-[10px] text-muted-foreground">{sub}</div>
    </div>
  );
}
