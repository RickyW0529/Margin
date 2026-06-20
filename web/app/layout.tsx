/**
 * @fileoverview Root layout for the Margin research workspace.
 * Provides the application shell, global navigation, and metadata shared by every route.
 */

import type { Metadata } from "next";
import Link from "next/link";

import "./globals.css";

export const metadata: Metadata = {
  title: "Margin",
  description: "Evidence-driven portfolio research workspace",
};

/**
 * Root layout that wraps the entire application.
 * @param children - The current page content.
 * @returns The wrapped HTML document with navigation and page content.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const portfolioId = process.env.MARGIN_DEFAULT_PORTFOLIO_ID ?? "demo";

  return (
    <html lang="zh-CN">
      <body>
        <div className="app-frame">
          <header className="app-topbar">
            <Link className="brand-mark" href="/">
              <span className="brand-dot" aria-hidden="true" />
              <span>
                <strong>Margin</strong>
                <small>Evidence Research OS</small>
              </span>
            </Link>
            <nav className="main-nav" aria-label="主导航">
              <Link href="/">工作台</Link>
              <Link href={`/portfolios/${portfolioId}`}>组合</Link>
              <Link href="/research">研究</Link>
            </nav>
            <div className="topbar-meta">
              <span>v0.1</span>
              <span>真实 API</span>
            </div>
          </header>
          <div className="app-main">{children}</div>
        </div>
      </body>
    </html>
  );
}
