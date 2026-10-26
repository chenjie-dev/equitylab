"use client";

/**
 * Wind 式公开行情台：红涨绿跌 · 推送最新价 · 闪烁 · ↑↓ 切票。
 * 币安式壳：顶栏热门条（SiteHeader）+ `?symbol=` 切票；仅公开数据。
 */

import {
  startTransition,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  BinanceChart,
  type Kline,
} from "../components/markets/BinanceChart";
import { DepthChart } from "../components/markets/DepthChart";
import { HOT_SYMBOLS } from "../components/markets/HotTickerStrip";
import { useListKeyboard } from "../components/markets/useListKeyboard";
import { flashClass, usePriceFlash } from "../components/markets/usePriceFlash";
import {
  fetchSpotKlines,
  getCachedKlines,
  klineCacheKey,
  prefetchKlines,
  setCachedKlines,
} from "../components/markets/klineCache";
import { useQdbKlines } from "../components/markets/useQdbKlines";
import { useQdbSnapshots } from "../components/markets/useQdbSnapshots";
import { useVisibilityPolling } from "../components/markets/useVisibilityPolling";
import { formatLocalTime } from "../../lib/time";

const WATCHLIST = [
  ...HOT_SYMBOLS,
  "POLUSDT",
  "LTCUSDT",
  "NEARUSDT",
  "UNIUSDT",
  "ATOMUSDT",
  "APTUSDT",
] as const;

function isWatchSymbol(s: string): s is (typeof WATCHLIST)[number] {
  return (WATCHLIST as readonly string[]).includes(s);
}

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

/** 首屏根数：偏小以加快切票首屏；左滑再补 */
const KLINE_PAGE = 120;
/** 浏览器侧最多保留根数（与 collector docs 硬顶一致），超出丢最旧 */
const KLINE_MAX_BARS = 500;
/** 盘中只刷最近几根，合并进已有序列 */
const KLINE_TAIL = 5;

function retainKlines(rows: Kline[]): Kline[] {
  if (rows.length <= KLINE_MAX_BARS) return rows;
  return rows.slice(rows.length - KLINE_MAX_BARS);
}

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
  return (
    <Suspense
      fallback={
        <div className="bn-page wind">
          <p className="bn-empty">加载行情…</p>
        </div>
      }
    >
      <MarketsPageInner />
    </Suspense>
  );
}

function MarketsPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawSymbol = searchParams.get("symbol") || "BTCUSDT";
  const symbol = isWatchSymbol(rawSymbol) ? rawSymbol : "BTCUSDT";

  const setSymbol = useCallback(
    (next: string) => {
      const sym = isWatchSymbol(next) ? next : "BTCUSDT";
      const params = new URLSearchParams(searchParams.toString());
      if (params.get("symbol") === sym) return;
      params.set("symbol", sym);
      router.replace(`/markets?${params.toString()}`, { scroll: false });
    },
    [router, searchParams],
  );

  useEffect(() => {
    if (rawSymbol !== symbol) setSymbol(symbol);
  }, [rawSymbol, symbol, setSymbol]);

  const [interval, setIntervalTf] = useState<Interval>("15m");
  const [ticker, setTicker] = useState<Ticker | null>(null);
  const [list, setList] = useState<Ticker[]>([]);
  const [depth, setDepth] = useState<Depth | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [klines, setKlines] = useState<Kline[]>([]);
  /** 图表实际展示的 seriesKey；切票未到新数据前保持旧 key，避免错图/闪白 */
  const [chartKey, setChartKey] = useState(() => `${symbol}:15m`);
  const [bid, setBid] = useState<number | null>(null);
  const [ask, setAsk] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [favs, setFavs] = useState<Set<string>>(
    () => new Set(["BTCUSDT", "ETHUSDT"]),
  );
  const [mktTab, setMktTab] = useState<"fav" | "usdt">("usdt");
  const [rightTab, setRightTab] = useState<RightTab>("book");
  const [bookLimit, setBookLimit] = useState(16);
  const [historyDone, setHistoryDone] = useState(false);
  const [klineLoading, setKlineLoading] = useState(false);
  const historyLoadingRef = useRef(false);
  const klineAbortRef = useRef<AbortController | null>(null);
  const bookAbortRef = useRef<AbortController | null>(null);
  const switchGenRef = useRef(0);
  const chartKeyRef = useRef(chartKey);
  chartKeyRef.current = chartKey;
  const wantKeyRef = useRef(`${symbol}:${interval}`);
  wantKeyRef.current = `${symbol}:${interval}`;
  // 盘口/24h 字段读 qdb docs（经 market-data）；最新价走 snapshots 订阅。不可见停表
  const bookTick = useVisibilityPolling(5_000);
  const listTick = useVisibilityPolling(30_000);
  /** 折叠周期或引擎无 trade 时 docs 尾刷；原生周期优先 klines SUBSCRIBE */
  const klineTick = useVisibilityPolling(30_000);

  const snapSymbols = useMemo(
    () => WATCHLIST.map((s) => `BINANCE:${s}`),
    [],
  );

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
    // 保留订阅覆盖的 lastPrice，避免 docs 轮询盖掉推送价
    setList((prev) => {
      const live = new Map(prev.map((t) => [t.symbol, t.lastPrice]));
      return rows.map((t) => ({
        ...t,
        lastPrice: live.get(t.symbol) || t.lastPrice,
      }));
    });
  }, []);

  // docs 列表只补涨跌/量；last 以 snapshots 为准
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

  // collector → quotes → snapshots SUBSCRIBE（全 watchlist）
  useQdbSnapshots(snapSymbols, (row) => {
    const code = row.symbol.includes(":")
      ? row.symbol.split(":").slice(1).join(":")
      : row.symbol;
    if (!isWatchSymbol(code)) return;
    const last = String(row.last);
    startTransition(() => {
      setList((prev) =>
        prev.map((t) => (t.symbol === code ? { ...t, lastPrice: last } : t)),
      );
      if (code !== symbol) return;
      if (row.bid != null && row.bid > 0) setBid(row.bid);
      if (row.ask != null && row.ask > 0) setAsk(row.ask);
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
    });
  });

  // 原生周期：引擎 klines 订阅尾刷（依赖 BINANCE_WS_WRITE_TRADES）；历史仍 docs
  useQdbKlines(
    symbol ? `BINANCE:${symbol}` : null,
    interval,
    (bar) => {
      // 切票未换上新图时忽略，避免把新标的尾部并进旧图
      if (chartKeyRef.current !== wantKeyRef.current) return;
      startTransition(() => {
        setKlines((prev) => {
          if (!prev.length) return prev;
          const last = prev[prev.length - 1];
          const t = Number(bar[0]);
          const lt = Number(last[0]);
          if (t === lt) {
            const next = prev.slice();
            next[next.length - 1] = bar;
            return next;
          }
          if (t > lt) return retainKlines([...prev, bar]);
          return prev;
        });
      });
    },
  );

  const loadBook = useCallback(async (sym: string) => {
    bookAbortRef.current?.abort();
    const ac = new AbortController();
    bookAbortRef.current = ac;
    try {
      const [dRes, trRes] = await Promise.all([
        fetch(`/api/market/binance/depth?symbol=${sym}&limit=20`, {
          signal: ac.signal,
        }),
        fetch(`/api/market/binance/trades?symbol=${sym}&limit=40`, {
          signal: ac.signal,
        }),
      ]);
      if (!dRes.ok) throw new Error(`depth ${dRes.status}`);
      if (!trRes.ok) throw new Error(`trades ${trRes.status}`);
      const [depthBody, tradesBody] = await Promise.all([
        dRes.json() as Promise<Depth>,
        trRes.json() as Promise<Trade[]>,
      ]);
      if (ac.signal.aborted) return;
      startTransition(() => {
        setDepth(depthBody);
        setTrades(tradesBody);
        setError(null);
      });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const fetchKlines = useCallback(
    (
      sym: string,
      tf: Interval,
      limit: number,
      endTime?: number,
      signal?: AbortSignal,
    ) => fetchSpotKlines(sym, tf, limit, signal, endTime),
    [],
  );

  const prefetchSymbol = useCallback(
    (sym: string) => {
      if (!isWatchSymbol(sym)) return;
      const key = klineCacheKey("spot", sym, interval);
      prefetchKlines(key, (signal) =>
        fetchSpotKlines(sym, interval, KLINE_PAGE, signal),
      );
    },
    [interval],
  );

  /**
   * 换标的/周期：缓存命中立刻上图；未命中保留旧图（stale）直至新数据到达。
   * 取消 inflight，只拉最近一页。
   */
  const loadKlines = useCallback(
    async (sym: string, tf: Interval) => {
      klineAbortRef.current?.abort();
      const ac = new AbortController();
      klineAbortRef.current = ac;
      const gen = ++switchGenRef.current;
      const wantKey = `${sym}:${tf}`;
      const cacheKey = klineCacheKey("spot", sym, tf);
      setHistoryDone(false);

      const cached = getCachedKlines(cacheKey);
      if (cached?.length) {
        setKlines(cached);
        setChartKey(wantKey);
      }
      setKlineLoading(true);

      try {
        const rows = await fetchKlines(
          sym,
          tf,
          KLINE_PAGE,
          undefined,
          ac.signal,
        );
        if (gen !== switchGenRef.current) return;
        const retained = retainKlines(rows);
        if (retained.length) setCachedKlines(cacheKey, retained);
        setKlines(retained);
        setChartKey(wantKey);
        if (rows.length < KLINE_PAGE) setHistoryDone(true);
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
      } finally {
        if (gen === switchGenRef.current) setKlineLoading(false);
      }
    },
    [fetchKlines],
  );

  /** 左滑：以当前最老一根为 endTime，向前再取一页并前置合并 */
  const loadOlderKlines = useCallback(async () => {
    if (historyDone || historyLoadingRef.current || klineLoading) return;
    if (klines.length >= KLINE_MAX_BARS) {
      setHistoryDone(true);
      return;
    }
    if (klines.length < 40) return; // 首屏未稳，避免切票瞬间误触发翻页
    const oldest = klines[0];
    if (!oldest) return;
    historyLoadingRef.current = true;
    const gen = switchGenRef.current;
    try {
      const endTime = Number(oldest[0]) - 1;
      const older = await fetchKlines(symbol, interval, KLINE_PAGE, endTime);
      if (gen !== switchGenRef.current) return;
      if (!older.length) {
        setHistoryDone(true);
        return;
      }
      setKlines((prev) => {
        const seen = new Set(prev.map((k) => Number(k[0])));
        const merged = retainKlines([
          ...older.filter((k) => !seen.has(Number(k[0]))),
          ...prev,
        ]);
        if (merged.length >= KLINE_MAX_BARS) setHistoryDone(true);
        // 只缓存尾部一页，避免左滑历史撑爆 LRU
        const tail = merged.slice(Math.max(0, merged.length - KLINE_PAGE));
        setCachedKlines(klineCacheKey("spot", symbol, interval), tail);
        return merged;
      });
      if (older.length < KLINE_PAGE) setHistoryDone(true);
    } finally {
      historyLoadingRef.current = false;
    }
  }, [historyDone, klineLoading, klines, symbol, interval, fetchKlines]);

  /** 盘中：只刷尾部几根，原地合并（不整表重载） */
  const refreshKlineTail = useCallback(async () => {
    if (klineLoading) return;
    const gen = switchGenRef.current;
    const tail = await fetchKlines(symbol, interval, KLINE_TAIL);
    if (gen !== switchGenRef.current || !tail.length) return;
    setKlines((prev) => {
      if (!prev.length) return retainKlines(tail);
      const byTs = new Map(prev.map((k) => [Number(k[0]), k]));
      for (const row of tail) byTs.set(Number(row[0]), row);
      return retainKlines(
        [...byTs.entries()]
          .sort((a, b) => a[0] - b[0])
          .map(([, row]) => row),
      );
    });
  }, [symbol, interval, fetchKlines, klineLoading]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (listTick === 0) return;
    void loadList();
  }, [listTick, loadList]);

  // 切票/周期：立刻拉盘口 + 首屏 K 线
  useEffect(() => {
    void loadBook(symbol);
    void loadKlines(symbol, interval);
  }, [symbol, interval, loadBook, loadKlines]);

  useEffect(() => {
    if (bookTick === 0) return;
    void loadBook(symbol);
  }, [bookTick, symbol, loadBook]);

  useEffect(() => {
    if (klineTick === 0) return;
    void refreshKlineTail();
  }, [klineTick, refreshKlineTail]);

  const change = Number(ticker?.priceChangePercent ?? 0);
  const changeUp = change >= 0;
  const digits = priceDigits(ticker?.lastPrice ?? "0");
  const lastFlash = usePriceFlash(ticker?.lastPrice);

  const filteredList = useMemo(() => {
    let rows = list;
    if (mktTab === "fav") rows = rows.filter((t) => favs.has(t.symbol));
    const q = query.trim().toUpperCase();
    if (q) rows = rows.filter((t) => t.symbol.includes(q));
    return rows;
  }, [list, query, mktTab, favs]);

  const listIds = useMemo(
    () => filteredList.map((t) => t.symbol),
    [filteredList],
  );
  useListKeyboard(listIds, symbol, setSymbol);

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
    <div className="bn-page wind">
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
              title="自选"
              aria-label="自选"
            >
              ★
            </button>
            <span className="bn-pill">现货</span>
          </div>
          <div
            className={`bn-top-last ${changeUp ? "up" : "down"} ${flashClass(lastFlash)}`}
          >
            {ticker ? fmt(ticker.lastPrice, digits) : "—"}
          </div>
        </div>
        <div className="bn-top-stats">
          <div>
            <span className="bn-label">涨跌幅</span>
            <span className={changeUp ? "up" : "down"}>
              {ticker
                ? `${changeUp ? "+" : ""}${fmt(ticker.priceChange, digits)} (${changeUp ? "+" : ""}${fmt(change, 2)}%)`
                : "—"}
            </span>
          </div>
          <div>
            <span className="bn-label">最高</span>
            <span className="up">
              {ticker ? fmt(ticker.highPrice, digits) : "—"}
            </span>
          </div>
          <div>
            <span className="bn-label">最低</span>
            <span className="down">
              {ticker ? fmt(ticker.lowPrice, digits) : "—"}
            </span>
          </div>
          <div>
            <span className="bn-label">成交量({baseAsset(symbol)})</span>
            <span>{ticker ? fmt(ticker.volume, 2) : "—"}</span>
          </div>
          <div>
            <span className="bn-label">成交额(USDT)</span>
            <span>{ticker ? fmt(ticker.quoteVolume, 2) : "—"}</span>
          </div>
        </div>
      </header>
      <div className="bn-quote-strip" aria-label="五档摘要">
        <div>
          <span className="bn-label">最新</span>
          <span className={changeUp ? "up" : "down"}>
            {ticker ? fmt(ticker.lastPrice, digits) : "—"}
          </span>
        </div>
        <div>
          <span className="bn-label">买一</span>
          <span className="up">
            {bid != null ? fmt(bid, digits) : "—"}
          </span>
        </div>
        <div>
          <span className="bn-label">卖一</span>
          <span className="down">
            {ask != null ? fmt(ask, digits) : "—"}
          </span>
        </div>
        <div>
          <span className="bn-label">价差</span>
          <span>
            {bid != null && ask != null ? fmt(ask - bid, digits) : "—"}
          </span>
        </div>
        <span className="bn-label">↑↓ 切换标的</span>
      </div>

      {error ? <pre className="error bn-error">{error}</pre> : null}

      <div className="bn-main bn-main-quotes">
        <aside className="bn-card bn-markets">
          <div className="bn-card-head bn-mkt-tabs">
            <button
              type="button"
              className={mktTab === "fav" ? "bn-tab active" : "bn-tab"}
              onClick={() => setMktTab("fav")}
            >
              自选
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
            placeholder="搜索代码"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="bn-mkt-head">
            <span>名称</span>
            <span>最新</span>
            <span>涨幅</span>
          </div>
          <div className="bn-mkt-body">
            {filteredList.map((t) => (
              <SpotMktRow
                key={t.symbol}
                t={t}
                active={t.symbol === symbol}
                fav={favs.has(t.symbol)}
                onFav={() => toggleFav(t.symbol)}
                onPick={() => setSymbol(t.symbol)}
                onPrefetch={() => prefetchSymbol(t.symbol)}
              />
            ))}
            {!filteredList.length ? (
              <p className="bn-empty">无标的</p>
            ) : null}
          </div>
        </aside>

        <section className="bn-card bn-chart-panel">
          <div className="bn-tf-row">
            <div className="bn-tf-group">
              <span className="bn-tf-label">周期</span>
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
            <span className="bn-label">只读 · 推送最新价</span>
          </div>
          <BinanceChart
            klines={klines}
            symbol={symbol}
            seriesKey={chartKey}
            loading={klineLoading}
            stale={klineLoading && chartKey !== `${symbol}:${interval}`}
            palette="wind"
            onNeedHistory={historyDone ? undefined : () => void loadOlderKlines()}
          />
        </section>

        <aside className="bn-right bn-right-quotes">
          <div className="bn-card bn-book bn-book-tall">
            <div className="bn-card-head bn-right-tabs">
              <button
                type="button"
                className={rightTab === "book" ? "bn-tab active" : "bn-tab"}
                onClick={() => setRightTab("book")}
              >
                买卖盘
              </button>
              <button
                type="button"
                className={rightTab === "trades" ? "bn-tab active" : "bn-tab"}
                onClick={() => setRightTab("trades")}
              >
                成交明细
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
                  <span>价格(USDT)</span>
                  <span>数量({baseAsset(symbol)})</span>
                  <span>累计</span>
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
                    价差{" "}
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
                  <span>价格</span>
                  <span>数量</span>
                  <span>时间</span>
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
          <span>深度图</span>
          <span className="bn-label">
            价差{" "}
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
        <span>Wind 式行情 · 红涨绿跌</span>
        <span className="bn-label">·</span>
        <span className="bn-label">只读报价 · EquityLab</span>
        <span className="bn-status-right">
          {ticker ? pairLabel(symbol) : "—"} ·{" "}
          {ticker ? fmt(ticker.lastPrice, digits) : "—"}
        </span>
      </footer>
    </div>
  );
}

function SpotMktRow({
  t,
  active,
  fav,
  onFav,
  onPick,
  onPrefetch,
}: {
  t: Ticker;
  active: boolean;
  fav: boolean;
  onFav: () => void;
  onPick: () => void;
  onPrefetch: () => void;
}) {
  const pct = Number(t.priceChangePercent);
  const flash = usePriceFlash(t.lastPrice);
  return (
    <div
      className={active ? "bn-mkt-row active" : "bn-mkt-row"}
      onMouseEnter={onPrefetch}
      onFocus={onPrefetch}
    >
      <button
        type="button"
        className={fav ? "bn-star-sm on" : "bn-star-sm"}
        onClick={onFav}
        aria-label="自选"
      >
        ★
      </button>
      <button type="button" className="bn-mkt-pick" onClick={onPick}>
        <span className="bn-mkt-pair">{pairLabel(t.symbol)}</span>
        <span className={`bn-mono ${flashClass(flash)}`}>
          {fmt(t.lastPrice, priceDigits(t.lastPrice))}
        </span>
        <span className={pct >= 0 ? "up" : "down"}>
          {pct >= 0 ? "+" : ""}
          {fmt(pct, 2)}%
        </span>
      </button>
    </div>
  );
}
