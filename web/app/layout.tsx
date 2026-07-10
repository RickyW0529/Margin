/**
 * @fileoverview Root layout for the Margin research workspace.
 * Provides the application shell, sidebar navigation, top bar,
 * typography, plus shared metadata.
 */

import type { Metadata } from "next";
import { DM_Sans, JetBrains_Mono } from "next/font/google";

import { AppProviders } from "@/components/app-providers";
import { LanguageToggle } from "@/components/language-toggle";
import { MobileNavigation, Sidebar } from "@/components/sidebar";
import { LanguageProvider } from "@/lib/i18n";

import "./globals.css";

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-dm-sans",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

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
    <html lang="zh-CN" className={`${dmSans.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <LanguageProvider>
          <AppProviders>
            <div className="grid min-h-screen grid-cols-1 md:grid-cols-[17rem_minmax(0,1fr)]">
              <Sidebar />
              <div className="grid min-h-screen grid-rows-[auto_minmax(0,1fr)]">
                <header className="sticky top-0 z-20 flex min-h-14 min-w-0 items-center justify-between gap-4 border-b border-border bg-background/90 px-5 py-3 backdrop-blur-sm md:justify-end md:px-8">
                  <MobileNavigation />
                  <div className="hidden items-center gap-2 md:inline-flex">
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
