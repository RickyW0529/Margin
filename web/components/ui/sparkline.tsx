"use client";

import { cn } from "@/lib/utils";

type SparklineProps = {
  values: number[];
  className?: string;
  strokeClassName?: string;
  fillClassName?: string;
};

/** Minimal inline sparkline for compact metric context. */
export function Sparkline({
  values,
  className,
  strokeClassName,
  fillClassName,
}: SparklineProps) {
  if (values.length < 2) {
    return (
      <div
        className={cn("h-8 w-full rounded-md bg-muted/50", className)}
        aria-hidden="true"
      />
    );
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 120;
  const height = 32;
  const points = values.map((value, index) => {
    const x = (index / (values.length - 1)) * width;
    const y = height - ((value - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  });
  const area = `0,${height} ${points.join(" ")} ${width},${height}`;
  return (
    <svg
      aria-hidden="true"
      className={cn("h-8 w-full overflow-visible", className)}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
    >
      <polygon
        className={cn("fill-accent/10", fillClassName)}
        points={area}
      />
      <polyline
        className={cn("fill-none stroke-accent", strokeClassName)}
        points={points.join(" ")}
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
    </svg>
  );
}
