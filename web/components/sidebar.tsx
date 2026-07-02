"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageCircle,
  MonitorUp,
  Settings,
  ShieldCheck,
} from "lucide-react";

import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: React.ElementType;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "问答", icon: MessageCircle },
  { href: "/dashboard", label: "今日推荐", icon: MonitorUp },
  { href: "/settings", label: "设置", icon: Settings },
];

/** Minimal application sidebar for the user-facing workspace. */
export function Sidebar() {
  const pathname = usePathname() ?? "/";

  return (
    <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col gap-6 self-start overflow-y-auto border-r border-sidebar-border bg-sidebar p-4 text-sidebar-foreground">
      <Link href="/" className="inline-flex items-center gap-2.5 no-underline">
        <span className="grid size-8 place-items-center rounded-md bg-sidebar-primary text-sidebar-primary-foreground">
          <ShieldCheck className="size-4" />
        </span>
        <span className="leading-tight">
          <span className="block text-base font-semibold text-sidebar-accent-foreground">
            Margin
          </span>
          <span className="block text-xs text-sidebar-foreground/70">
            安全边际
          </span>
        </span>
      </Link>

      <nav className="grid flex-1 content-start gap-1" aria-label="主导航分组">
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
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-sidebar-border px-3 py-4">
        <p className="text-xs leading-relaxed text-sidebar-foreground/60">
          证据驱动 · 只读优先
        </p>
      </div>
    </aside>
  );
}
