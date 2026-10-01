import type { Metadata } from "next";
import { Suspense } from "react";
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
        {/* CR8-4：一级导航固定在顶部——长卡片流下不再丢失入口。
            实测前置干净：全仓 web/app 无其它 sticky/fixed/z-*（无层叠冲突），
            header 祖先（html/body）无 overflow。
            连带回归已由 ResearchPanel 的 scroll-mt-24 补偿（#research 锚点跳转）。
            阴影先用 always-on shadow-sm：要"只在滚动后出阴影"得把 header 挪进客户端组件。 */}
        <header className="sticky top-0 z-40 border-b border-zinc-200 bg-white shadow-sm">
          {/* Nav 现在读 `useSearchParams`（来路驱动高亮）⇒ 必须有 Suspense 边界，
              否则整棵布局树退出静态渲染。 */}
          <Suspense fallback={null}>
            <Nav />
          </Suspense>
        </header>
        {children}
      </body>
    </html>
  );
}
