import * as React from "react";

import { cn } from "@/lib/utils";

export const Input = React.forwardRef<
  HTMLInputElement,
  React.InputHTMLAttributes<HTMLInputElement>
>(({ className, ...props }, ref) => (
  <input
    ref={ref}
    className={cn(
      "flex h-11 w-full rounded-xl border border-border/90 bg-input-background px-4 text-[15px] text-foreground shadow-xs placeholder:text-muted-foreground/80 transition-colors duration-150 focus-visible:border-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/25 disabled:opacity-50",
      className,
    )}
    {...props}
  />
));
Input.displayName = "Input";
