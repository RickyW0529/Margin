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
    <main className="mx-auto max-w-3xl space-y-6 px-6 py-8 md:px-10">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-muted-foreground">{t("settingsEyebrow")}</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
            {t("scheduleTitle")}
          </h1>
        </div>
        <Button asChild size="sm" variant="secondary">
          <Link href="/settings">{t("scheduleBack")}</Link>
        </Button>
      </header>
      <StockAnalysisSchedulePanel initialSchedule={schedule} />
    </main>
  );
}
