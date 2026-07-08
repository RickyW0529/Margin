/**
 * @fileoverview User-facing automatic research schedule settings.
 */

import { ScheduleSettingsPageClient } from "@/components/schedule-settings-page-client";
import { fetchStockAnalysisSchedule } from "@/lib/api";

export const dynamic = "force-dynamic";

/** Renders the automatic research schedule settings page. */
export default async function ScheduleSettingsPage() {
  const schedule = await fetchStockAnalysisSchedule().catch(() => null);

  return <ScheduleSettingsPageClient schedule={schedule} />;
}
