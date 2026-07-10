"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageCircle, MonitorUp, Settings } from "lucide-react";

import { LanguageToggle } from "@/components/language-toggle";
import { useAgentChatSessions } from "@/lib/agent-chat-history";
import { useLanguage, type TranslationKey } from "@/lib/i18n";
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
          className="min-w-0 text-[15px] font-semibold tracking-tight text-foreground no-underline"
        >
          Margin
        </Link>
        <LanguageToggle />
      </div>
      <nav
        className="grid grid-cols-3 gap-1 rounded-xl border border-border bg-card p-1"
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
                "flex min-h-9 min-w-0 items-center justify-center gap-1.5 rounded-lg px-1.5 text-xs font-medium no-underline transition-colors duration-150",
                active
                  ? "bg-foreground text-background"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
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
  const {
    error: recentError,
    loading: recentLoading,
    sessions: recentSessions,
  } = useAgentChatSessions();

  return (
    <aside className="sticky top-0 hidden h-screen w-[17rem] shrink-0 flex-col self-start border-r border-sidebar-border bg-sidebar text-sidebar-foreground md:flex">
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto p-5">
        <Link
          href="/"
          className="px-3 text-lg font-semibold tracking-tight text-sidebar-accent-foreground no-underline"
        >
          Margin
        </Link>

        <nav
          className="mt-10 grid content-start gap-1"
          aria-label="main navigation"
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
                  "flex items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium no-underline transition-colors duration-150",
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground",
                )}
              >
                <Icon
                  className={cn(
                    "size-[1.125rem] shrink-0",
                    active
                      ? "text-sidebar-ring"
                      : "text-sidebar-foreground/40",
                  )}
                />
                {t(item.labelKey)}
              </Link>
            );
          })}
        </nav>

        <div className="mt-10 grid gap-1.5">
          <h2 className="px-3 text-xs font-medium tracking-wide text-sidebar-foreground/40">
            {t("navRecent")}
          </h2>
          {recentLoading ? (
            <p className="px-3 py-2 text-sm text-sidebar-foreground/40">
              {t("chatReadingData")}
            </p>
          ) : recentError ? (
            <p className="px-3 py-2 text-sm text-sidebar-foreground/40">
              {t("chatError")}
            </p>
          ) : recentSessions.length > 0 ? (
            <div className="grid gap-0.5">
              {recentSessions.map((session) => (
                <Link
                  key={session.session_id}
                  className="truncate rounded-xl px-3 py-2 text-sm text-sidebar-foreground/65 no-underline transition-colors duration-150 hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground"
                  href={`/?chat=${encodeURIComponent(session.session_id)}`}
                  title={session.title}
                >
                  {session.title}
                </Link>
              ))}
            </div>
          ) : (
            <p className="px-3 py-2 text-sm text-sidebar-foreground/40">
              {t("navRecentEmpty")}
            </p>
          )}
        </div>
      </div>
    </aside>
  );
}
