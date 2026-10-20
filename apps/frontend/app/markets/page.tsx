"use client";

/**
 * 币安风格公开行情台：市场列表 · K 线 · 盘口 · 成交 · 深度。
 * 仅公开 REST，无下单 / 账户 / 挂单。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BinanceChart,
  type Kline,
} from "../components/markets/BinanceChart";
import { DepthChart } from "../components/markets/DepthChart";
import { useQdbSnapshot } from "../components/markets/useQdbSnapshot";
import { formatLocalTime } from "../../lib/time";

const WATCHLIST = [
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
  "POLUSDT",
  "LTCUSDT",
  "NEARUSDT",
  "UNIUSDT",
  "ATOMUSDT",
  "APTUSDT",
] as const;

const INTERVALS = [
  "1m",
  "3m",
  "5m",
  "15m",
  "30m",
  "1h",
  "2h",
  "4h",
  "6h",
  "12h",
  "1d",
  "3d",
  "1w",
  "1M",
] as const;
type Interval = (typeof INTERVALS)[number];

type Ticker = {
  symbol: string;
  lastPrice: string;
  priceChange: string;
  priceChangePercent: string;
  highPrice: string;
  lowPrice: string;
  volume: string;
  quoteVolume: string;
};

type Depth = {
  lastUpdateId?: number;
  bids: [string, string][];
  asks: [string, string][];
};

type Trade = {
  id: number;
  price: string;
  qty: string;
  time: number;
  isBuyerMaker: boolean;
};

type RightTab = "book" | "trades";

function fmt(n: string | number, digits = 2): string {
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (Math.abs(v) >= 1000)
    return v.toLocaleString(undefined, { maximumFractionDigits: digits });
  if (Math.abs(v) >= 1) return v.toFixed(digits);
  return v.toPrecision(4);
}

function priceDigits(price: string | number): number {
  const v = typeof price === "string" ? Number(price) : price;
  if (!Number.isFinite(v) || v === 0) return 2;
  if (v >= 1000) return 2;
  if (v >= 1) return 4;
  return 6;
}

function pairLabel(sym: string): string {
  if (sym.endsWith("USDT")) return `${sym.slice(0, -4)}/USDT`;
  return sym;
}

function baseAsset(sym: string): string {
  return sym.endsWith("USDT") ? sym.slice(0, -4) : sym;
}

export default function MarketsPage() {
  const [symbol, setSymbol] = useState<string>("BTCUSDT");
  const [interval, setIntervalTf] = useState<Interval>("15m");
  const [ticker, setTicker] = useState<Ticker | null>(null);
  const [list, setList] = useState<Ticker[]>([]);
  const [depth, setDepth] = useState<Depth | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [klines, setKlines] = useState<Kline[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [favs, setFavs] = useState<Set<string>>(
    () => new Set(["BTCUSDT", "ETHUSDT"]),
  );
  const [mktTab, setMktTab] = useState<"fav" | "usdt">("usdt");
  const [tick, setTick] = useState(0);
  const [rightTab, setRightTab] = useState<RightTab>("book");
  const [bookLimit, setBookLimit] = useState(16);

  const loadList = useCallback(async () => {
    const symbols = encodeURIComponent(JSON.stringify([...WATCHLIST]));
    const res = await fetch(
      `/api/market/binance/ticker/24hr?symbols=${symbols}`,
    );
    if (!res.ok) return;
    const all = (await res.json()) as Ticker[];
    if (!Array.isArray(all)) return;
    const order = new Map(WATCHLIST.map((s, i) => [s, i]));
    const rows = [...all].sort(
      (a, b) =>
        (order.get(a.symbol as (typeof WATCHLIST)[number]) ?? 99) -
        (order.get(b.symbol as (typeof WATCHLIST)[number]) ?? 99),
    );
    setList(rows);
  }, []);

  // REST 列表只补涨跌/量；lastPrice 以 WS 为准，避免 20s 轮询盖掉实时价
  useEffect(() => {
    const cur = list.find((t) => t.symbol === symbol);
    if (!cur) return;
    setTicker((prev) => {
      if (prev && prev.symbol === symbol) {
        return {
          ...cur,
          lastPrice: prev.lastPrice || cur.lastPrice,
        };
      }
      return cur;
    });
  }, [list, symbol]);

  // 当前标的：qdb snapshots 订阅覆盖 last；24hr 涨跌仍来自 REST ticker docs
  useQdbSnapshot(symbol ? `BINANCE:${symbol}` : null, (row) => {
    const last = String(row.last);
    setTicker((prev) =>
      prev && prev.symbol === symbol
        ? { ...prev, lastPrice: last }
        : {
            symbol,
            lastPrice: last,
            priceChange: "0",
            priceChangePercent: "0",
            highPrice: last,
            lowPrice: last,
            volume: "0",
            quoteVolume: "0",
          },
    );
    setList((prev) =>
      prev.map((t) => (t.symbol === symbol ? { ...t, lastPrice: last } : t)),
    );
  });

  const loadBook = useCallback(async (sym: string) => {
    try {
      const [dRes, trRes] = await Promise.all([
        fetch(`/api/market/binance/depth?symbol=${sym}&limit=50`),
        fetch(`/api/market/binance/trades?symbol=${sym}&limit=50`),
      ]);
      if (!dRes.ok) throw new Error(`depth ${dRes.status}`);
      if (!trRes.ok) throw new Error(`trades ${trRes.status}`);
      setDepth((await dRes.json()) as Depth);
      setTrades((await trRes.json()) as Trade[]);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const loadKlines = useCallback(async (sym: string, tf: Interval) => {
    const kRes = await fetch(
      `/api/market/binance/klines?symbol=${sym}&interval=${tf}&limit=500`,
    );
    if (kRes.ok) setKlines((await kRes.json()) as Kline[]);
  }, []);

  useEffect(() => {
    void loadList();
    const id = setInterval(() => void loadList(), 20_000);
    return () => clearInterval(id);
  }, [loadList]);

  // 盘口/成交跟 docs（collector 约 1s/标的轮询）；K 线更慢
  useEffect(() => {
    void loadBook(symbol);
    void loadKlines(symbol, interval);
    const id = setInterval(() => setTick((n) => n + 1), 2_000);
    return () => clearInterval(id);
  }, [symbol, interval, loadBook, loadKlines]);

  useEffect(() => {
    if (tick === 0) return;
    void loadBook(symbol);
    if (tick % 15 === 0) void loadKlines(symbol, interval);
  }, [tick, symbol, interval, loadBook, loadKlines]);

  const change = Number(ticker?.priceChangePercent ?? 0);
  const changeUp = change >= 0;
  const digits = priceDigits(ticker?.lastPrice ?? "0");

  const filteredList = useMemo(() => {
    let rows = list;
    if (mktTab === "fav") rows = rows.filter((t) => favs.has(t.symbol));
    const q = query.trim().toUpperCase();
    if (q) rows = rows.filter((t) => t.symbol.includes(q));
    return rows;
  }, [list, query, mktTab, favs]);

  const book = useMemo(() => {
    const asksRaw = [...(depth?.asks ?? [])].slice(0, bookLimit).reverse();
    const bidsRaw = (depth?.bids ?? []).slice(0, bookLimit);
    let askAcc = 0;
    const askRows = asksRaw.map(([price, qty]) => {
      askAcc += Number(qty);
      return { price, qty, total: askAcc };
    });
    let bidAcc = 0;
    const bidRows = bidsRaw.map(([price, qty]) => {
      bidAcc += Number(qty);
      return { price, qty, total: bidAcc };
    });
    const maxTotal = Math.max(
      ...askRows.map((r) => r.total),
      ...bidRows.map((r) => r.total),
      1e-12,
    );
    const bestAsk = depth?.asks?.[0] ? Number(depth.asks[0][0]) : NaN;
    const bestBid = depth?.bids?.[0] ? Number(depth.bids[0][0]) : NaN;
    const spread =
      Number.isFinite(bestAsk) && Number.isFinite(bestBid)
        ? bestAsk - bestBid
        : NaN;
    const spreadPct =
      Number.isFinite(spread) && bestBid > 0 ? (spread / bestBid) * 100 : NaN;
    return { askRows, bidRows, maxTotal, spread, spreadPct };
  }, [depth, bookLimit]);

  const toggleFav = (sym: string) => {
    setFavs((prev) => {
      const next = new Set(prev);
      if (next.has(sym)) next.delete(sym);
      else next.add(sym);
      return next;
    });
  };

  return (
    <div className="bn-page">
      <header className="bn-top">
        <div className="bn-top-pair">
          <div className="bn-top-name">
            <select
              className="bn-pair-select"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              aria-label="Trading pair"
            >
              {WATCHLIST.map((s) => (
                <option key={s} value={s}>
                  {pairLabel(s)}
                </option>
              ))}
            </select>
            <button
              type="button"
              className={favs.has(symbol) ? "bn-star on" : "bn-star"}
              onClick={() => toggleFav(symbol)}
              title="Favorite"
              aria-label="Favorite"
            >
              ★
            </button>
            <span className="bn-pill">Spot</span>
          </div>
          <div className={`bn-top-last ${changeUp ? "up" : "down"}`}>
            {ticker ? fmt(ticker.lastPrice, digits) : "—"}
          </div>
        </div>
        <div className="bn-top-stats">
          <div>
            <span className="bn-label">24h Change</span>
            <span className={changeUp ? "up" : "down"}>
              {ticker
                ? `${changeUp ? "+" : ""}${fmt(ticker.priceChange, digits)} (${changeUp ? "+" : ""}${fmt(change, 2)}%)`
                : "—"}
            </span>
          </div>
          <div>
            <span className="bn-label">24h High</span>
            <span>{ticker ? fmt(ticker.highPrice, digits) : "—"}</span>
          </div>
          <div>
            <span className="bn-label">24h Low</span>
            <span>{ticker ? fmt(ticker.lowPrice, digits) : "—"}</span>
          </div>
          <div>
            <span className="bn-label">24h Volume({baseAsset(symbol)})</span>
            <span>{ticker ? fmt(ticker.volume, 2) : "—"}</span>
          </div>
          <div>
            <span className="bn-label">24h Volume(USDT)</span>
            <span>{ticker ? fmt(ticker.quoteVolume, 2) : "—"}</span>
          </div>
        </div>
      </header>

      {error ? <pre className="error bn-error">{error}</pre> : null}

      <div className="bn-main bn-main-quotes">
        <aside className="bn-card bn-markets">
          <div className="bn-card-head bn-mkt-tabs">
            <button
              type="button"
              className={mktTab === "fav" ? "bn-tab active" : "bn-tab"}
              onClick={() => setMktTab("fav")}
            >
              Favorites
            </button>
            <button
              type="button"
              className={mktTab === "usdt" ? "bn-tab active" : "bn-tab"}
              onClick={() => setMktTab("usdt")}
            >
              USDT
            </button>
          </div>
          <input
            className="bn-search"
            placeholder="Search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="bn-mkt-head">
            <span>Pair</span>
            <span>Price</span>
            <span>Change</span>
          </div>
          <div className="bn-mkt-body">
            {filteredList.map((t) => {
              const pct = Number(t.priceChangePercent);
              const active = t.symbol === symbol;
              return (
                <div
                  key={t.symbol}
                  className={active ? "bn-mkt-row active" : "bn-mkt-row"}
                >
                  <button
                    type="button"
                    className={
                      favs.has(t.symbol) ? "bn-star-sm on" : "bn-star-sm"
                    }
                    onClick={() => toggleFav(t.symbol)}
                    aria-label="Favorite"
                  >
                    ★
                  </button>
                  <button
                    type="button"
                    className="bn-mkt-pick"
                    onClick={() => setSymbol(t.symbol)}
                  >
                    <span className="bn-mkt-pair">{pairLabel(t.symbol)}</span>
                    <span className="bn-mono">
                      {fmt(t.lastPrice, priceDigits(t.lastPrice))}
                    </span>
                    <span className={pct >= 0 ? "up" : "down"}>
                      {pct >= 0 ? "+" : ""}
                      {fmt(pct, 2)}%
                    </span>
                  </button>
                </div>
              );
            })}
            {!filteredList.length ? (
              <p className="bn-empty">No markets</p>
            ) : null}
          </div>
        </aside>

        <section className="bn-card bn-chart-panel">
          <div className="bn-tf-row">
            <div className="bn-tf-group">
              <span className="bn-tf-label">Time</span>
              {INTERVALS.map((tf) => (
                <button
                  key={tf}
                  type="button"
                  className={tf === interval ? "bn-tf active" : "bn-tf"}
                  onClick={() => setIntervalTf(tf)}
                >
                  {tf}
                </button>
              ))}
            </div>
            <span className="bn-label">Public · read-only</span>
          </div>
          <BinanceChart klines={klines} symbol={symbol} />
        </section>

        <aside className="bn-right bn-right-quotes">
          <div className="bn-card bn-book bn-book-tall">
            <div className="bn-card-head bn-right-tabs">
              <button
                type="button"
                className={rightTab === "book" ? "bn-tab active" : "bn-tab"}
                onClick={() => setRightTab("book")}
              >
                Order Book
              </button>
              <button
                type="button"
                className={rightTab === "trades" ? "bn-tab active" : "bn-tab"}
                onClick={() => setRightTab("trades")}
              >
                Market Trades
              </button>
              {rightTab === "book" ? (
                <div className="bn-book-depth-btns">
                  {[8, 16, 24].map((n) => (
                    <button
                      key={n}
                      type="button"
                      className={bookLimit === n ? "active" : ""}
                      onClick={() => setBookLimit(n)}
                    >
                      {n}
                    </button>
                  ))}
                </div>
              ) : null}
            </div>

            {rightTab === "book" ? (
              <>
                <div className="bn-book-head">
                  <span>Price(USDT)</span>
                  <span>Amount({baseAsset(symbol)})</span>
                  <span>Total</span>
                </div>
                <div className="bn-asks bn-asks-tall">
                  {book.askRows.map((r) => (
                    <div key={`a-${r.price}`} className="bn-book-row ask">
                      <span className="down">{fmt(r.price, digits)}</span>
                      <span>{fmt(r.qty, 4)}</span>
                      <span>{fmt(r.total, 4)}</span>
                      <i
                        className="bn-book-bar ask"
                        style={{ width: `${(r.total / book.maxTotal) * 100}%` }}
                      />
                    </div>
                  ))}
                </div>
                <div className={`bn-book-mid ${changeUp ? "up" : "down"}`}>
                  <strong>
                    {ticker ? fmt(ticker.lastPrice, digits) : "—"}
                  </strong>
                  <span className="bn-label">
                    Spread{" "}
                    {Number.isFinite(book.spread)
                      ? `${fmt(book.spread, digits)} (${fmt(book.spreadPct, 4)}%)`
                      : "—"}
                  </span>
                </div>
                <div className="bn-bids bn-bids-tall">
                  {book.bidRows.map((r) => (
                    <div key={`b-${r.price}`} className="bn-book-row bid">
                      <span className="up">{fmt(r.price, digits)}</span>
                      <span>{fmt(r.qty, 4)}</span>
                      <span>{fmt(r.total, 4)}</span>
                      <i
                        className="bn-book-bar bid"
                        style={{ width: `${(r.total / book.maxTotal) * 100}%` }}
                      />
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <>
                <div className="bn-trades-head">
                  <span>Price(USDT)</span>
                  <span>Amount({baseAsset(symbol)})</span>
                  <span>Time</span>
                </div>
                <div className="bn-trades-body bn-trades-side bn-trades-tall">
                  {trades.map((t) => {
                    const buy = !t.isBuyerMaker;
                    return (
                      <div key={t.id} className="bn-trade-row">
                        <span className={buy ? "up" : "down"}>
                          {fmt(t.price, digits)}
                        </span>
                        <span>{fmt(t.qty, 5)}</span>
                        <span className="bn-label">
                          {formatLocalTime(t.time)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        </aside>
      </div>

      <section className="bn-card bn-bottom">
        <div className="bn-card-head">
          <span>Market Depth</span>
          <span className="bn-label">
            Spread{" "}
            {Number.isFinite(book.spread)
              ? `${fmt(book.spread, digits)} USDT`
              : "—"}
          </span>
        </div>
        <div className="bn-depth-panel">
          <DepthChart
            bids={depth?.bids ?? []}
            asks={depth?.asks ?? []}
            height={180}
          />
        </div>
      </section>

      <footer className="bn-status">
        <span className="bn-status-dot" />
        <span>Binance Public API</span>
        <span className="bn-label">·</span>
        <span className="bn-label">Quotes only · EquityLab Research</span>
        <span className="bn-status-right">
          {ticker ? pairLabel(symbol) : "—"} ·{" "}
          {ticker ? fmt(ticker.lastPrice, digits) : "—"}
        </span>
      </footer>
    </div>
  );
}
