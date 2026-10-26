"use client";

/**
 * 币安式顶部热门行情条：固定热门对。
 * 24h% 读 qdb ticker docs（经 market-data）；最新价 snapshots SUBSCRIBE。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  fetchSpotKlines,
  klineCacheKey,
  prefetchKlines,
} from "./klineCache";
import { flashClass, usePriceFlash } from "./usePriceFlash";
import { useQdbSnapshots } from "./useQdbSnapshots";
import { useVisibilityPolling } from "./useVisibilityPolling";

/** 与 spot 页默认周期一致，悬停预取首屏 K 线 */
const PREFETCH_INTERVAL = "15m";
const PREFETCH_LIMIT = 120;

export const HOT_SYMBOLS = [
  "BTCUSDT",
  "ETHUSDT",
  "BNBUSDT",
  "SOLUSDT",
  "XRPUSDT",
  "DOGEUSDT",
  "ADAUSDT",
  "AVAXUSDT",
  "DOTUSDT",
  "LINKUSDT",
] as const;

type HotRow = {
  symbol: string;
  lastPrice: string;
  priceChangePercent: string;
};

function pairLabel(sym: string): string {
  if (sym.endsWith("USDT")) return `${sym.slice(0, -4)}/USDT`;
  return sym;
}

function fmtPrice(n: string | number): string {
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "—";
  if (v >= 1000) return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (v >= 1) return v.toFixed(4);
  return v.toPrecision(4);
}

function HotChip({
  row,
  active,
  onPick,
  onPrefetch,
}: {
  row: HotRow;
  active: boolean;
  onPick: () => void;
  onPrefetch: () => void;
}) {
  const pct = Number(row.priceChangePercent);
  const up = pct >= 0;
  const flash = usePriceFlash(row.lastPrice);
  return (
    <button
      type="button"
      className={active ? "bn-hot-chip active" : "bn-hot-chip"}
      onClick={onPick}
      onMouseEnter={onPrefetch}
      onFocus={onPrefetch}
    >
      <span className="bn-hot-pair">{pairLabel(row.symbol)}</span>
      <span className={`bn-mono ${flashClass(flash)}`}>
        {fmtPrice(row.lastPrice)}
      </span>
      <span className={Number.isFinite(pct) ? (up ? "up" : "down") : ""}>
        {Number.isFinite(pct)
          ? `${up ? "+" : ""}${pct.toFixed(2)}%`
          : "—"}
      </span>
    </button>
  );
}

export function HotTickerStrip() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const onSpot = pathname === "/markets" || pathname === "/";
  const selected = searchParams.get("symbol") || "BTCUSDT";
  const [rows, setRows] = useState<HotRow[]>([]);
  const listTick = useVisibilityPolling(30_000);

  const snapSymbols = useMemo(
    () => (onSpot ? HOT_SYMBOLS.map((s) => `BINANCE:${s}`) : []),
    [onSpot],
  );

  const load = useCallback(async () => {
    const symbols = encodeURIComponent(JSON.stringify([...HOT_SYMBOLS]));
    const res = await fetch(
      `/api/market/binance/ticker/24hr?symbols=${symbols}`,
    );
    if (!res.ok) return;
    const all = (await res.json()) as HotRow[];
    if (!Array.isArray(all)) return;
    const order = new Map(HOT_SYMBOLS.map((s, i) => [s, i]));
    setRows((prev) => {
      const live = new Map(prev.map((t) => [t.symbol, t.lastPrice]));
      return [...all]
        .filter((t) => order.has(t.symbol as (typeof HOT_SYMBOLS)[number]))
        .sort(
          (a, b) =>
            (order.get(a.symbol as (typeof HOT_SYMBOLS)[number]) ?? 99) -
            (order.get(b.symbol as (typeof HOT_SYMBOLS)[number]) ?? 99),
        )
        .map((t) => ({
          ...t,
          lastPrice: live.get(t.symbol) || t.lastPrice,
        }));
    });
  }, []);

  useEffect(() => {
    if (!onSpot) return;
    void load();
  }, [onSpot, load]);

  useEffect(() => {
    if (!onSpot || listTick === 0) return;
    void load();
  }, [onSpot, listTick, load]);

  useQdbSnapshots(snapSymbols, (row) => {
    const code = row.symbol.includes(":")
      ? row.symbol.split(":").slice(1).join(":")
      : row.symbol;
    const last = String(row.last);
    setRows((prev) =>
      prev.map((t) => (t.symbol === code ? { ...t, lastPrice: last } : t)),
    );
  });

  const prefetch = useCallback((sym: string) => {
    const key = klineCacheKey("spot", sym, PREFETCH_INTERVAL);
    prefetchKlines(key, (signal) =>
      fetchSpotKlines(sym, PREFETCH_INTERVAL, PREFETCH_LIMIT, signal),
    );
  }, []);

  if (!onSpot) return null;

  const pick = (sym: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("symbol", sym);
    router.replace(`/markets?${params.toString()}`, { scroll: false });
  };

  return (
    <div className="bn-hot-strip wind" aria-label="热门行情">
      {(rows.length
        ? rows
        : HOT_SYMBOLS.map((symbol) => ({
            symbol,
            lastPrice: "",
            priceChangePercent: "",
          }))
      ).map((row) => (
        <HotChip
          key={row.symbol}
          row={row}
          active={row.symbol === selected}
          onPick={() => pick(row.symbol)}
          onPrefetch={() => prefetch(row.symbol)}
        />
      ))}
    </div>
  );
}
