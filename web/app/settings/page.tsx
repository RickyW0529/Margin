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
        <p className="text-[11px] font-medium tracking-[0.14em] text-muted-foreground uppercase">
          {t("settingsEyebrow")}
        </p>
        <h1 className="text-display mt-2 text-3xl text-foreground">
          {t("settingsTitle")}
        </h1>
      </header>
      <section className="grid gap-3 md:grid-cols-2">
        {SETTINGS.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className="group grid gap-4 rounded-2xl border border-border/90 bg-card p-5 no-underline shadow-xs transition-all duration-150 hover:border-border hover:shadow-sm"
            >
              <span className="grid size-10 place-items-center rounded-xl bg-muted/70 text-accent transition-colors group-hover:bg-accent/10">
                <Icon className="size-4" />
              </span>
              <span className="grid gap-1.5">
                <strong className="text-[15px] font-semibold tracking-tight text-foreground">
                  {t(item.titleKey)}
                </strong>
                <span className="text-sm leading-relaxed text-muted-foreground">
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
