"use client";

import * as React from "react";
import { TrendingDown, TrendingUp } from "lucide-react";

import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

type StatProps = {
  label: string;
  value: React.ReactNode;
  hint?: string;
  delta?: number | null;
  progress?: number | null;
  className?: string;
};

/** Compact metric tile with optional delta and progress accent. */
export function Stat({
  label,
  value,
  hint,
  delta,
  progress,
  className,
}: StatProps) {
  const positive = typeof delta === "number" && delta > 0;
  const negative = typeof delta === "number" && delta < 0;
  return (
    <div
      className={cn(
        "grid gap-2 rounded-2xl border border-border/90 bg-card p-4 shadow-xs",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[11px] font-medium tracking-[0.12em] text-muted-foreground uppercase">
          {label}
        </p>
        {typeof delta === "number" ? (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
              positive && "bg-positive-soft text-positive",
              negative && "bg-negative-soft text-negative",
              !positive && !negative && "bg-muted text-muted-foreground",
            )}
          >
            {positive ? (
              <TrendingUp className="size-3" />
            ) : negative ? (
              <TrendingDown className="size-3" />
            ) : null}
            {delta > 0 ? "+" : ""}
            {delta.toFixed(1)}
          </span>
        ) : null}
      </div>
      <p className="text-2xl font-semibold tracking-tight tabular text-foreground">
        {value}
      </p>
      {hint ? (
        <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
      ) : null}
      {typeof progress === "number" ? (
        <Progress className="mt-1" value={progress} />
      ) : null}
    </div>
  );
}
