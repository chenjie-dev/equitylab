"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "对话" },
  { href: "/backtest", label: "回测" },
];

export function SiteHeader() {
  const pathname = usePathname();

  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link href="/" className="brand">
          <span className="brand-mark" aria-hidden />
          <span className="brand-name">EquityLab</span>
        </Link>
        <nav className="site-nav" aria-label="主导航">
          {NAV.map((item) => {
            const active =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
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
        <span className="header-tag">Research · Demo</span>
      </div>
    </header>
  );
}
