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
    <main className="mx-auto max-w-5xl space-y-6 px-6 py-8 md:px-10">
      <header>
        <p className="text-sm text-muted-foreground">{t("settingsEyebrow")}</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
          {t("settingsTitle")}
        </h1>
      </header>
      <section className="grid gap-4 md:grid-cols-2">
        {SETTINGS.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className="grid gap-4 rounded-lg border border-border bg-card p-5 no-underline transition-colors hover:bg-muted/50"
            >
              <span className="grid size-10 place-items-center rounded-md bg-muted text-accent">
                <Icon className="size-5" />
              </span>
              <span className="grid gap-1">
                <strong className="text-base text-foreground">
                  {t(item.titleKey)}
                </strong>
                <span className="text-sm text-muted-foreground">
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
