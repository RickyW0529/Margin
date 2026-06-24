"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Database,
  KeyRound,
  Layers,
  LayoutGrid,
  LineChart,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";

import { cn } from "@/lib/utils";

type NavItem = {
  href: string;
  label: string;
  icon: React.ElementType;
};

type NavGroup = {
  heading: string;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    heading: "研究主线",
    items: [
      { href: "/", label: "工作台", icon: LayoutGrid },
      { href: "/research", label: "研究候选", icon: LineChart },
      { href: "/research/universe", label: "公司池", icon: Layers },
      { href: "/research/runs", label: "刷新记录", icon: ShieldCheck },
    ],
  },
  {
    heading: "策略配置",
    items: [
      { href: "/strategies", label: "策略模板", icon: SlidersHorizontal },
    ],
  },
  {
    heading: "设置",
    items: [
      { href: "/settings/providers", label: "Provider 密钥", icon: KeyRound },
      { href: "/settings/data", label: "数据策略", icon: Database },
      { href: "/settings/scope", label: "Scope", icon: Layers },
      { href: "/settings/strategy", label: "Strategy", icon: SlidersHorizontal },
    ],
  },
];

/** Dark application sidebar with active-route highlighting. */
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
            安全边际 · v0.2
          </span>
        </span>
      </Link>

      <nav className="grid flex-1 gap-5" aria-label="主导航分组">
        {NAV_GROUPS.map((group) => (
          <section key={group.heading}>
            <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/50">
              {group.heading}
            </p>
            <ul className="grid gap-0.5">
              {group.items.map((item) => {
                const active = pathname === item.href;
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-3 rounded-md px-3 py-2 text-sm no-underline transition-colors",
                        active
                          ? "bg-sidebar-accent text-sidebar-accent-foreground"
                          : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
                      )}
                    >
                      <Icon
                        className={cn(
                          "size-4 shrink-0",
                          active
                            ? "text-accent"
                            : "text-sidebar-foreground/60",
                        )}
                      />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </nav>

      <div className="border-t border-sidebar-border px-3 py-4">
        <p className="text-xs leading-relaxed text-sidebar-foreground/60">
          本地优先 · 证据驱动 · 用户保留最终决策权
        </p>
      </div>
    </aside>
  );
}
