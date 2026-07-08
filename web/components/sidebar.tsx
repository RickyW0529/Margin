"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageCircle,
  MonitorUp,
  Settings,
  ShieldCheck,
} from "lucide-react";

import { LanguageToggle } from "@/components/language-toggle";
import { useLanguage, type TranslationKey } from "@/lib/i18n";
import { useRecentQuestions } from "@/lib/recent-questions";
import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  labelKey: TranslationKey;
  icon: React.ElementType;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/", labelKey: "navAsk", icon: MessageCircle },
  { href: "/dashboard", labelKey: "navDashboard", icon: MonitorUp },
  { href: "/settings", labelKey: "navSettings", icon: Settings },
];

/** Mobile header navigation for narrow screens. */
export function MobileNavigation() {
  const pathname = usePathname() ?? "/";
  const { t } = useLanguage();

  return (
    <div className="grid min-w-0 flex-1 gap-3 md:hidden">
      <div className="flex min-w-0 items-center justify-between gap-3">
        <Link
          href="/"
          className="inline-flex min-w-0 items-center gap-2.5 no-underline"
        >
          <span className="grid size-8 place-items-center rounded-md bg-foreground text-background">
            <ShieldCheck className="size-4" />
          </span>
          <span className="min-w-0 leading-tight">
            <span className="block truncate text-base font-semibold text-foreground">
              Margin
            </span>
          </span>
        </Link>
        <LanguageToggle />
      </div>
      <nav
        className="grid grid-cols-3 gap-1 rounded-md border border-border bg-muted/40 p-1"
        aria-label={t("navSettings")}
      >
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(`${item.href}/`));
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-9 min-w-0 items-center justify-center gap-1.5 rounded px-1.5 text-xs font-medium no-underline transition-colors",
                active
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:bg-background/70 hover:text-foreground",
              )}
            >
              <Icon className="size-3.5 shrink-0" />
              <span className="truncate">{t(item.labelKey)}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

/** Minimal application sidebar for the user-facing workspace. */
export function Sidebar() {
  const pathname = usePathname() ?? "/";
  const { t } = useLanguage();
  const recentQuestions = useRecentQuestions();

  return (
    <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col self-start overflow-y-auto border-r border-sidebar-border bg-sidebar p-3 text-sidebar-foreground md:flex">
      <Link href="/" className="inline-flex items-center gap-2.5 no-underline">
        <span className="grid size-8 place-items-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground">
          <ShieldCheck className="size-4" />
        </span>
        <span className="leading-tight">
          <span className="block text-base font-semibold text-sidebar-accent-foreground">
            Margin
          </span>
        </span>
      </Link>

      <nav className="mt-8 grid content-start gap-1" aria-label="main navigation">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(`${item.href}/`));
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm no-underline transition-colors",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
              )}
            >
              <Icon
                className={cn(
                  "size-4 shrink-0",
                  active ? "text-accent" : "text-sidebar-foreground/60",
                )}
              />
              {t(item.labelKey)}
            </Link>
          );
        })}
      </nav>

      <div className="mt-8 grid gap-2">
        <h2 className="px-3 text-xs font-medium text-sidebar-accent-foreground">
          {t("navRecent")}
        </h2>
        {recentQuestions.length > 0 ? (
          <div className="grid gap-0.5">
            {recentQuestions.map((question) => (
              <Link
                key={question.id}
                className="truncate rounded-md px-3 py-2 text-sm text-sidebar-foreground/86 no-underline transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
                href="/"
                title={question.text}
              >
                {question.text}
              </Link>
            ))}
          </div>
        ) : (
          <p className="px-3 py-2 text-sm text-sidebar-foreground/45">
            {t("navRecentEmpty")}
          </p>
        )}
      </div>
    </aside>
  );
}
