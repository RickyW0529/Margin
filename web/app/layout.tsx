/**
 * @fileoverview Root layout for the Margin research workspace.
 * Provides the application shell, left sidebar navigation, top bar with
 * breadcrumbs and the admin unlock gate, plus metadata shared by every route.
 */

import type { Metadata } from "next";
import Link from "next/link";

import { AdminGate } from "@/components/admin-gate";

import "./globals.css";

export const metadata: Metadata = {
  title: "Margin",
  description: "Evidence-driven valuation research workspace",
};

type NavItem = {
  href: string;
  label: string;
};

type NavGroup = {
  heading: string;
  items: NavItem[];
};

const NAV_GROUPS: NavGroup[] = [
  {
    heading: "研究",
    items: [
      { href: "/", label: "工作台" },
      { href: "/research", label: "研究候选" },
      { href: "/research/universe", label: "公司池" },
      { href: "/research/runs", label: "运行记录" },
    ],
  },
  {
    heading: "策略",
    items: [{ href: "/strategies", label: "策略模板" }],
  },
  {
    heading: "设置",
    items: [
      { href: "/settings/providers", label: "Provider 密钥" },
      { href: "/settings/scope", label: "Scope" },
      { href: "/settings/strategy", label: "Strategy" },
    ],
  },
];

/**
 * Root layout that wraps the entire application.
 * @param children - The current page content.
 * @returns The wrapped HTML document with sidebar navigation and page content.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="app-frame">
          <aside className="app-sidebar" aria-label="主导航">
            <Link className="brand-mark" href="/">
              <span className="brand-dot" aria-hidden="true" />
              <span>
                <strong>Margin</strong>
                <small>Evidence Research OS</small>
              </span>
            </Link>
            <nav className="sidebar-nav" aria-label="主导航分组">
              {NAV_GROUPS.map((group) => (
                <section className="sidebar-group" key={group.heading}>
                  <p className="sidebar-heading">{group.heading}</p>
                  <ul>
                    {group.items.map((item) => (
                      <li key={item.href}>
                        <Link href={item.href}>{item.label}</Link>
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </nav>
            <div className="sidebar-footer">
              <span>v0.2</span>
              <span>真实 API</span>
            </div>
          </aside>
          <div className="app-content">
            <header className="app-topbar">
              <AdminGate />
            </header>
            <main className="app-main">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}