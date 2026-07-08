"use client";

/**
 * @fileoverview Compact language switcher.
 */

import { useLanguage } from "@/lib/i18n";

type LanguageToggleProps = {
  tone?: "default" | "dark";
};

/** Toggles the workspace UI language. */
export function LanguageToggle({ tone = "default" }: LanguageToggleProps) {
  const { language, setLanguage, t } = useLanguage();
  return (
    <div
      aria-label={t("languageLabel")}
      className={
        tone === "dark"
          ? "inline-flex rounded-full border border-white/10 bg-white/8 p-0.5 text-xs"
          : "inline-flex rounded-full border border-border bg-muted p-0.5 text-xs"
      }
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
    return [
      "rounded-full px-2.5 py-1 transition-colors",
      active
        ? "bg-white text-black shadow-sm"
        : "text-white/55 hover:text-white",
    ].join(" ");
  }
  return [
    "rounded-full px-2.5 py-1 transition-colors",
    active
      ? "bg-background text-foreground shadow-sm"
      : "text-muted-foreground hover:text-foreground",
  ].join(" ");
}
