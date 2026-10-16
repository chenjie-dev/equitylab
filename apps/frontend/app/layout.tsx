/**
 * 根布局：全局 metadata 与基础 HTML 壳。
 * 样式见 globals.css；页面内容由各 route 注入 children。
 */
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EquityLab",
  description: "AI 驱动的量化研究与投资分析工作台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
