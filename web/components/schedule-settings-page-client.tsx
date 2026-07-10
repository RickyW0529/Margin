"use client";

/**
 * @fileoverview Client wrapper for the automatic research schedule page.
 */

import Link from "next/link";

import { StockAnalysisSchedulePanel } from "@/components/stock-analysis-schedule-panel";
import { Button } from "@/components/ui/button";
import type { StockAnalysisSchedule } from "@/lib/api";
import { useLanguage } from "@/lib/i18n";

/** Renders the schedule settings page in the selected UI language. */
export function ScheduleSettingsPageClient({
  schedule,
}: {
  schedule: StockAnalysisSchedule | null;
}) {
  const { t } = useLanguage();
  return (
    <main className="page-shell space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          {t("scheduleTitle")}
        </h1>
        <Button asChild size="sm" variant="secondary">
          <Link href="/settings">{t("scheduleBack")}</Link>
        </Button>
      </header>
      <StockAnalysisSchedulePanel initialSchedule={schedule} />
    </main>
  );
}
