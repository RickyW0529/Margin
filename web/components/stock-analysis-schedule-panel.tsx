"use client";

/**
 * @fileoverview Simple user-facing schedule control for automatic stock analysis.
 */

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  updateStockAnalysisSchedule,
  type StockAnalysisSchedule,
} from "@/lib/api";
import { useLanguage } from "@/lib/i18n";
import { formatDate } from "@/lib/utils";

type StockAnalysisSchedulePanelProps = {
  initialSchedule: StockAnalysisSchedule | null;
};

/** Renders the only user-configurable scheduled stock-analysis task. */
export function StockAnalysisSchedulePanel({
  initialSchedule,
}: StockAnalysisSchedulePanelProps) {
  const { language, t } = useLanguage();
  const labelSeparator = language === "zh" ? "：" : ": ";
  const [schedule, setSchedule] = useState<StockAnalysisSchedule | null>(
    initialSchedule,
  );
  const [enabled, setEnabled] = useState(initialSchedule?.enabled ?? false);
  const [time, setTime] = useState(formatTimeValue(initialSchedule));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    const parsed = parseTimeValue(time);
    if (!parsed) {
      setError(t("scheduleInvalidTime"));
      return;
    }
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const updated = await updateStockAnalysisSchedule({
        enabled,
        hour: parsed.hour,
        minute: parsed.minute,
      });
      setSchedule(updated);
      setSaved(true);
    } catch {
      setError(t("scheduleError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card aria-labelledby="stock-analysis-schedule-title">
      <CardHeader>
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-accent">
            {t("scheduleCardEyebrow")}
          </p>
          <CardTitle id="stock-analysis-schedule-title" className="mt-1">
            {t("scheduleCardTitle")}
          </CardTitle>
        </div>
        <span className="rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-muted-foreground">
          {schedule?.enabled ? t("scheduleEnabled") : t("scheduleDisabled")}
        </span>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-2 rounded-md border border-border bg-muted/40 p-4">
          <strong className="text-sm text-foreground">{t("scheduleTaskName")}</strong>
          <p className="text-sm leading-relaxed text-muted-foreground">
            {t("scheduleTaskDesc")}
          </p>
          <div className="grid gap-1 text-xs text-muted-foreground">
            <span>{t("scheduleNext")}{labelSeparator}{formatDate(schedule?.next_run_at)}</span>
            <span>{t("scheduleLast")}{labelSeparator}{formatDate(schedule?.last_triggered_at)}</span>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-[1fr_auto] sm:items-end">
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              checked={enabled}
              className="size-4 rounded border-border"
              disabled={busy}
              onChange={(event) => setEnabled(event.target.checked)}
              type="checkbox"
            />
            {t("scheduleToggle")}
          </label>
          <div className="grid gap-1">
            <Label htmlFor="stock-analysis-time">{t("scheduleTime")}</Label>
            <Input
              id="stock-analysis-time"
              disabled={busy}
              onChange={(event) => setTime(event.target.value)}
              type="time"
              value={time}
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button disabled={busy} loading={busy} onClick={save} type="button">
            {t("scheduleSave")}
          </Button>
          {saved ? (
            <span className="text-xs text-positive">{t("scheduleSaved")}</span>
          ) : null}
          {error ? (
            <span className="text-xs text-negative" role="alert">
              {error}
            </span>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

function formatTimeValue(schedule: StockAnalysisSchedule | null): string {
  const hour = schedule?.hour ?? 8;
  const minute = schedule?.minute ?? 30;
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function parseTimeValue(value: string): { hour: number; minute: number } | null {
  const match = /^(\d{2}):(\d{2})$/.exec(value);
  if (!match) {
    return null;
  }
  const hour = Number(match[1]);
  const minute = Number(match[2]);
  if (hour > 23 || minute > 59) {
    return null;
  }
  return { hour, minute };
}
