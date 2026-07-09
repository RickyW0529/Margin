import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-tight whitespace-nowrap",
  {
    variants: {
      tone: {
        positive: "border-positive/15 bg-positive-soft text-positive",
        caution: "border-caution/15 bg-caution-soft text-caution",
        negative: "border-negative/15 bg-negative-soft text-negative",
        neutral: "border-border/80 bg-muted/80 text-foreground/80",
        muted: "border-border/70 bg-muted/60 text-muted-foreground",
        accent: "border-accent/15 bg-accent/8 text-accent",
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
