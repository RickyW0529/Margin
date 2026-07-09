"use client";

import { CommandPalette } from "@/components/command-palette";
import { TooltipProvider } from "@/components/ui/tooltip";

/** Client-side shell providers shared across the app. */
export function AppProviders({ children }: { children: React.ReactNode }) {
  return (
    <TooltipProvider delayDuration={200}>
      {children}
      <CommandPalette />
    </TooltipProvider>
  );
}
