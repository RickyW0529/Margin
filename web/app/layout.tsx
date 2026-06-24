/**
 * @fileoverview Root layout for the Margin research workspace.
 * Provides the application shell, dark sidebar navigation, top bar with
 * system guardrails and the admin unlock gate, plus shared metadata.
 */

import type { Metadata } from "next";

import { AdminGate } from "@/components/admin-gate";
import { Sidebar } from "@/components/sidebar";

import "./globals.css";

export const metadata: Metadata = {
  title: "Margin",
  description: "Evidence-driven valuation research workspace",
};

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
        <div className="grid min-h-screen grid-cols-[15rem_minmax(0,1fr)]">
          <Sidebar />
          <div className="grid min-h-screen grid-rows-[auto_minmax(0,1fr)]">
            <header className="sticky top-0 z-20 flex min-h-14 items-center justify-between gap-3 border-b border-border bg-background/80 px-6 py-2.5 backdrop-blur">
              <div className="flex flex-wrap gap-2">
                <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  只读优先
                </span>
                <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  无持仓 / 无交易
                </span>
                <span className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  Provider fail-closed
                </span>
              </div>
              <AdminGate />
            </header>
            <main className="min-h-0">{children}</main>
          </div>
        </div>
      </body>
    </html>
  );
}
