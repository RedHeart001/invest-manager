import type { Metadata } from "next";
import "./globals.css";

import Nav from "./components/Nav";

export const metadata: Metadata = {
  title: "Invest Manager",
  description: "个人投资理财助手",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen bg-zinc-50 text-zinc-900 antialiased">
        <header className="border-b border-zinc-200 bg-white">
          <Nav />
        </header>
        {children}
      </body>
    </html>
  );
}
