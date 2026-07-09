/**
 * @fileoverview Root layout for the Margin research workspace.
 * Provides the application shell, sidebar navigation, top bar,
 * typography, plus shared metadata.
 */

import type { Metadata } from "next";

import { AppProviders } from "@/components/app-providers";
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
      <body className="min-h-screen font-sans antialiased">
        <LanguageProvider>
          <AppProviders>
            <div className="grid min-h-screen grid-cols-1 md:grid-cols-[15.5rem_minmax(0,1fr)]">
              <Sidebar />
              <div className="grid min-h-screen grid-rows-[auto_minmax(0,1fr)] bg-background">
                <header className="sticky top-0 z-20 flex min-h-14 min-w-0 items-center justify-between gap-4 border-b border-border/80 bg-background/75 px-4 py-3 backdrop-blur-md md:justify-end md:px-8 md:py-3">
                  <MobileNavigation />
                  <div className="hidden items-center gap-3 md:inline-flex">
                    <kbd className="hidden rounded-lg border border-border/80 bg-card px-2 py-1 text-[10px] font-medium tracking-wide text-muted-foreground lg:inline">
                      ⌘K
                    </kbd>
                    <LanguageToggle />
                  </div>
                </header>
                <main className="min-h-0">{children}</main>
              </div>
            </div>
          </AppProviders>
        </LanguageProvider>
      </body>
    </html>
  );
}
