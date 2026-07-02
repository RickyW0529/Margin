/**
 * @fileoverview Settings hub page.
 */

import Link from "next/link";
import {
  Database,
  KeyRound,
  Layers,
  SlidersHorizontal,
} from "lucide-react";

const SETTINGS = [
  {
    href: "/settings/providers",
    title: "密钥配置",
    description: "模型、搜索、数据源密钥",
    icon: KeyRound,
  },
  {
    href: "/settings/data",
    title: "数据配置",
    description: "采集窗口与滚动策略",
    icon: Database,
  },
  {
    href: "/settings/scope",
    title: "研究范围",
    description: "股票池、指数池与指标视图",
    icon: Layers,
  },
  {
    href: "/settings/strategy",
    title: "策略配置",
    description: "评分规则、阈值与提示词",
    icon: SlidersHorizontal,
  },
];

/** Renders a compact settings hub for advanced configuration. */
export default function SettingsPage() {
  return (
    <main className="mx-auto max-w-5xl space-y-6 px-6 py-8 md:px-10">
      <header>
        <p className="text-sm text-muted-foreground">Settings</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-foreground">
          设置
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
                <strong className="text-base text-foreground">{item.title}</strong>
                <span className="text-sm text-muted-foreground">
                  {item.description}
                </span>
              </span>
            </Link>
          );
        })}
      </section>
    </main>
  );
}
