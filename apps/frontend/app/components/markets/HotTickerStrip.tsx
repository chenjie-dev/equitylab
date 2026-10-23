"use client";

/**
 * 币安式顶部热门行情条：固定一小撮交易对，24hr REST + 选中标的 qdb 推送覆盖最新价。
 * 仅在现货 `/markets` 挂载；切票写 `?symbol=`。
 */

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { flashClass, usePriceFlash } from "./usePriceFlash";
import { useQdbSnapshot } from "./useQdbSnapshot";
import { useVisibilityPolling } from "./useVisibilityPolling";

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
}: {
  row: HotRow;
  active: boolean;
  onPick: () => void;
}) {
  const pct = Number(row.priceChangePercent);
  const up = pct >= 0;
  const flash = usePriceFlash(row.lastPrice);
  return (
    <button
      type="button"
      className={active ? "bn-hot-chip active" : "bn-hot-chip"}
      onClick={onPick}
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

  const load = useCallback(async () => {
    const symbols = encodeURIComponent(JSON.stringify([...HOT_SYMBOLS]));
    const res = await fetch(
      `/api/market/binance/ticker/24hr?symbols=${symbols}`,
    );
    if (!res.ok) return;
    const all = (await res.json()) as HotRow[];
    if (!Array.isArray(all)) return;
    const order = new Map(HOT_SYMBOLS.map((s, i) => [s, i]));
    setRows(
      [...all]
        .filter((t) => order.has(t.symbol as (typeof HOT_SYMBOLS)[number]))
        .sort(
          (a, b) =>
            (order.get(a.symbol as (typeof HOT_SYMBOLS)[number]) ?? 99) -
            (order.get(b.symbol as (typeof HOT_SYMBOLS)[number]) ?? 99),
        ),
    );
  }, []);

  useEffect(() => {
    if (!onSpot) return;
    void load();
  }, [onSpot, load]);

  useEffect(() => {
    if (!onSpot || listTick === 0) return;
    void load();
  }, [onSpot, listTick, load]);

  useQdbSnapshot(onSpot ? `BINANCE:${selected}` : null, (row) => {
    const last = String(row.last);
    setRows((prev) =>
      prev.map((t) =>
        t.symbol === selected ? { ...t, lastPrice: last } : t,
      ),
    );
  });

  if (!onSpot) return null;

  const pick = (sym: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set("symbol", sym);
    router.replace(`/markets?${params.toString()}`, { scroll: false });
  };

  return (
    <div className="bn-hot-strip wind" aria-label="热门行情">
      {(rows.length ? rows : HOT_SYMBOLS.map((symbol) => ({
        symbol,
        lastPrice: "",
        priceChangePercent: "",
      }))).map((row) => (
        <HotChip
          key={row.symbol}
          row={row}
          active={row.symbol === selected}
          onPick={() => pick(row.symbol)}
        />
      ))}
    </div>
  );
}
