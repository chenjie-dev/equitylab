"use client";

/**
 * 顶栏主流指数条（同花顺/东财常见：上证·深成·创业板·沪深300…）。
 */

import { useCallback, useEffect, useState } from "react";
import { flashClass, usePriceFlash } from "./usePriceFlash";

export type IndexStripItem = {
  stock_code: string;
  short_name: string;
  exchange: string;
  price?: number | string | null;
  change?: number | string | null;
  change_pct?: number | string | null;
};

function fmt(n: string | number | null | undefined, digits = 2): string {
  if (n == null || n === "") return "—";
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "—";
  return v.toFixed(digits);
}

function StripCell({
  item,
  active,
  onPick,
}: {
  item: IndexStripItem;
  active: boolean;
  onPick: () => void;
}) {
  const pct = Number(item.change_pct ?? NaN);
  const up = Number.isFinite(pct) ? pct >= 0 : true;
  const flash = usePriceFlash(item.price);
  return (
    <button
      type="button"
      className={`ths-index-cell ${active ? "active" : ""} ${up ? "up" : "down"}`}
      onClick={onPick}
    >
      <span className="ths-index-name">{item.short_name || item.stock_code}</span>
      <span className={`ths-index-px ${flashClass(flash)}`}>
        {fmt(item.price, 2)}
      </span>
      <span className="ths-index-chg">
        {Number.isFinite(pct)
          ? `${pct >= 0 ? "+" : ""}${fmt(pct, 2)}%`
          : "—"}
      </span>
    </button>
  );
}

export function CnIndexStrip({
  selectedCode,
  onPick,
}: {
  selectedCode?: string;
  onPick: (item: IndexStripItem) => void;
}) {
  const [items, setItems] = useState<IndexStripItem[]>([]);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/cn-equity/index-strip");
      if (!res.ok) return;
      const body = (await res.json()) as { data?: IndexStripItem[] };
      if (body.data?.length) setItems(body.data);
    } catch {
      /* 顶栏失败不阻断主台 */
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 30_000);
    return () => clearInterval(id);
  }, [load]);

  if (!items.length) return null;

  return (
    <div className="ths-index-strip" aria-label="主流指数">
      {items.map((it) => (
        <StripCell
          key={`${it.exchange}:${it.stock_code}`}
          item={it}
          active={it.stock_code === selectedCode}
          onPick={() => onPick(it)}
        />
      ))}
    </div>
  );
}
