"use client";

/**
 * @fileoverview Settings hub page.
 */

import Link from "next/link";
import {
  Clock3,
  Database,
  KeyRound,
  Layers,
  SlidersHorizontal,
} from "lucide-react";

import { useLanguage, type TranslationKey } from "@/lib/i18n";

const SETTINGS = [
  {
    href: "/settings/providers",
    titleKey: "settingsProviders",
    descriptionKey: "settingsProvidersDesc",
    icon: KeyRound,
  },
  {
    href: "/settings/data",
    titleKey: "settingsData",
    descriptionKey: "settingsDataDesc",
    icon: Database,
  },
  {
    href: "/settings/scope",
    titleKey: "settingsScope",
    descriptionKey: "settingsScopeDesc",
    icon: Layers,
  },
  {
    href: "/settings/schedule",
    titleKey: "settingsSchedule",
    descriptionKey: "settingsScheduleDesc",
    icon: Clock3,
  },
  {
    href: "/settings/strategy",
    titleKey: "settingsStrategy",
    descriptionKey: "settingsStrategyDesc",
    icon: SlidersHorizontal,
  },
] satisfies Array<{
  href: string;
  titleKey: TranslationKey;
  descriptionKey: TranslationKey;
  icon: React.ElementType;
}>;

/** Renders a compact settings hub for advanced configuration. */
export default function SettingsPage() {
  const { t } = useLanguage();
  return (
    <main className="page-shell space-y-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight text-foreground">
          {t("settingsTitle")}
        </h1>
      </header>
      <section className="grid gap-3">
        {SETTINGS.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className="flex items-start gap-4 rounded-2xl border border-border bg-card px-5 py-5 shadow-xs no-underline transition-colors duration-150 hover:bg-muted/40"
            >
              <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-muted text-muted-foreground">
                <Icon className="size-5" />
              </span>
              <span className="grid min-w-0 gap-1 pt-0.5">
                <strong className="text-base font-semibold text-foreground">
                  {t(item.titleKey)}
                </strong>
                <span className="text-[15px] leading-relaxed text-muted-foreground">
                  {t(item.descriptionKey)}
                </span>
              </span>
            </Link>
          );
        })}
      </section>
    </main>
  );
}
