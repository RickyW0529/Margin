"use client";

import * as React from "react";

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
  return (
    <div
      className={cn(
        "grid gap-2.5 rounded-2xl border border-border bg-card p-5 shadow-xs",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">{label}</p>
        {typeof delta === "number" && delta !== 0 ? (
          <span className="text-xs tabular text-muted-foreground">
            {delta > 0 ? "+" : ""}
            {delta}
          </span>
        ) : null}
      </div>
      <p className="text-3xl font-semibold leading-none tracking-tight tabular text-foreground">
        {value}
      </p>
      {hint ? (
        <p className="text-sm text-muted-foreground">{hint}</p>
      ) : null}
      {typeof progress === "number" ? (
        <Progress className="mt-1 h-1.5" value={progress} />
      ) : null}
    </div>
  );
}
