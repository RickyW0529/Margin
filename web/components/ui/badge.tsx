import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        positive: "border-positive-soft bg-positive-soft text-positive",
        caution: "border-caution-soft bg-caution-soft text-caution",
        negative: "border-negative-soft bg-negative-soft text-negative",
        neutral: "border-border bg-muted text-foreground",
        muted: "border-border bg-muted text-muted-foreground",
        accent: "border-accent/20 bg-accent/10 text-accent",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ tone }), className)} {...props} />
  );
}

export { badgeVariants };
