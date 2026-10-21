"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/markets", label: "Spot" },
  { href: "/chat", label: "Chat" },
  { href: "/markets/stocks", label: "Stocks" },
  { href: "/markets/ashare", label: "A股" },
  { href: "/backtest", label: "Backtest" },
];

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link href="/" className="brand">
          <img className="brand-mark" src="/icon.svg" alt="" width={22} height={22} />
          <span className="brand-name">EquityLab</span>
        </Link>
        <nav className="site-nav" aria-label="主导航">
          {NAV.map((item) => {
            const active =
              item.href === "/markets"
                ? pathname === "/" || pathname === "/markets"
                : pathname === item.href || pathname.startsWith(`${item.href}/`);
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
        <span className="header-tag">Quotes · Public</span>
      </div>
    </header>
  );
}
