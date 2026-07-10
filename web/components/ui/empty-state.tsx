import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

type EmptyStateProps = {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
};

/** Quiet empty surface used across list and dashboard pages. */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "grid place-items-center gap-4 rounded-2xl border border-border bg-card px-8 py-16 text-center shadow-xs",
        className,
      )}
    >
      {Icon ? <Icon className="size-7 text-muted-foreground" /> : null}
      <div className="grid max-w-md gap-2">
        <p className="text-base font-semibold text-foreground">{title}</p>
        {description ? (
          <p className="text-[15px] leading-relaxed text-muted-foreground">
            {description}
          </p>
        ) : null}
      </div>
      {action}
    </div>
  );
}
