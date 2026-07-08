/**
 * @fileoverview Root layout for the Margin research workspace.
 * Provides the application shell, dark sidebar navigation, top bar with
 * system guardrails, plus shared metadata.
 */

import type { Metadata } from "next";

import { LanguageToggle } from "@/components/language-toggle";
import { MobileNavigation, Sidebar } from "@/components/sidebar";
import { LanguageProvider } from "@/lib/i18n";

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
        <LanguageProvider>
          <div className="grid min-h-screen grid-cols-1 md:grid-cols-[15rem_minmax(0,1fr)]">
            <Sidebar />
            <div className="grid min-h-screen grid-rows-[auto_minmax(0,1fr)]">
              <header className="sticky top-0 z-20 flex min-h-14 min-w-0 items-center justify-between gap-4 border-b border-border bg-background/80 px-4 py-3 backdrop-blur md:justify-end md:px-6 md:py-2.5">
                <MobileNavigation />
                <div className="hidden items-center gap-2 md:inline-flex">
                  <LanguageToggle />
                </div>
              </header>
              <main className="min-h-0">{children}</main>
            </div>
          </div>
        </LanguageProvider>
      </body>
    </html>
  );
}
