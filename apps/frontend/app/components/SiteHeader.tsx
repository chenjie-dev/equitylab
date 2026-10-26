"use client";

import Link from "next/link";
import { Suspense } from "react";
import { usePathname } from "next/navigation";
import { HotTickerStrip } from "./markets/HotTickerStrip";

const NAV = [
  { href: "/markets", label: "现货" },
  { href: "/markets/stocks", label: "代币化美股" },
  { href: "/markets/cn", label: "A股" },
  { href: "/chat", label: "对话" },
  { href: "/backtest", label: "回测" },
];

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link href="/" className="brand">
          <img
            className="brand-mark"
            src="/icon.svg"
            alt=""
            width={22}
            height={22}
          />
          <span className="brand-name">EquityLab</span>
        </Link>
        <nav className="site-nav" aria-label="主导航">
          {NAV.map((item) => {
            const active =
              item.href === "/markets"
                ? pathname === "/" || pathname === "/markets"
                : pathname === item.href ||
                  pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={active ? "nav-item active" : "nav-item"}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <span className="header-tag">只读报价</span>
      </div>
      <Suspense fallback={null}>
        <HotTickerStrip />
      </Suspense>
    </header>
  );
}
