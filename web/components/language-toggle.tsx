"use client";

/**
 * @fileoverview Compact language switcher.
 */

import { useLanguage } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type LanguageToggleProps = {
  tone?: "default" | "dark";
};

/** Toggles the workspace UI language. */
export function LanguageToggle({ tone = "default" }: LanguageToggleProps) {
  const { language, setLanguage, t } = useLanguage();
  return (
    <div
      aria-label={t("languageLabel")}
      className={cn(
        "inline-flex rounded-full p-0.5 text-xs shadow-xs",
        tone === "dark"
          ? "border border-white/10 bg-white/8"
          : "border border-border/80 bg-card/90",
      )}
      role="group"
    >
      <button
        aria-pressed={language === "zh"}
        className={languageButtonClass(language === "zh", tone)}
        onClick={() => setLanguage("zh")}
        type="button"
      >
        {t("languageZh")}
      </button>
      <button
        aria-pressed={language === "en"}
        className={languageButtonClass(language === "en", tone)}
        onClick={() => setLanguage("en")}
        type="button"
      >
        {t("languageEn")}
      </button>
    </div>
  );
}

function languageButtonClass(active: boolean, tone: "default" | "dark"): string {
  if (tone === "dark") {
    return cn(
      "rounded-full px-2.5 py-1 transition-colors duration-150",
      active ? "bg-white text-black shadow-xs" : "text-white/55 hover:text-white",
    );
  }
  return cn(
    "rounded-full px-2.5 py-1 transition-colors duration-150",
    active
      ? "bg-foreground text-background shadow-xs"
      : "text-muted-foreground hover:text-foreground",
  );
}
