import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Margin",
  description: "Evidence-driven portfolio research workspace",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
