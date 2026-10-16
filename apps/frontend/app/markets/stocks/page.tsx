"use client";

/**
 * 币安 Ondo 代币化美股只读行情台。
 * 数据：/api/market/binance/rwa/*（公开 bapi，非纽交所原生 feed）。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BinanceChart,
  type Kline,
} from "../../components/markets/BinanceChart";

const WATCH = [
  "AAPL",
  "NVDA",
  "TSLA",
  "MSFT",
  "AMZN",
  "GOOGL",
  "META",
  "SPY",
  "QQQ",
] as const;

const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "12h", "1d"] as const;
type Interval = (typeof INTERVALS)[number];

type StockToken = {
  chainId: string;
  contractAddress: string;
  symbol: string;
  ticker: string;
  multiplier?: string;
  type?: number;
};

type TokenInfo = {
  price?: string;
  priceChange24h?: string;
  priceChangePct24h?: string;
  totalHolders?: string;
  sharesMultiplier?: string;
  volume24h?: string;
  marketCap?: string;
  circulatingSupply?: string;
};

type StockInfo = {
  price?: string | null;
  priceHigh52w?: string;
  priceLow52w?: string;
  volume?: string;
  priceToEarnings?: string;
  dividendYield?: string;
  marketCap?: string;
};

type Dynamic = {
  symbol?: string;
  ticker?: string;
  tokenInfo?: TokenInfo;
  stockInfo?: StockInfo;
  statusInfo?: {
    openState?: boolean | null;
    marketStatus?: string | null;
    reasonCode?: string | null;
  };
};

type MarketStatus = {
  openState?: boolean;
  marketStatus?: string;
  reasonCode?: string | null;
  reasonMsg?: string | null;
  nextOpen?: string;
  nextClose?: string;
};

type QuoteRow = {
  token: StockToken;
  dynamic: Dynamic | null;
};

function fmt(n: string | number | null | undefined, digits = 2): string {
  if (n == null || n === "") return "—";
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(2)}M`;
  if (Math.abs(v) >= 1000)
    return v.toLocaleString(undefined, { maximumFractionDigits: digits });
  if (Math.abs(v) >= 1) return v.toFixed(digits);
  return v.toPrecision(4);
}

function refPrice(tokenPrice?: string, multiplier?: string): number | null {
  const p = Number(tokenPrice);
  const m = Number(multiplier || 1);
  if (!Number.isFinite(p) || !Number.isFinite(m) || m === 0) return null;
  return p / m;
}

export default function TokenizedStocksPage() {
  const [query, setQuery] = useState("");
  const [universe, setUniverse] = useState<StockToken[]>([]);
  const [rows, setRows] = useState<QuoteRow[]>([]);
  const [selected, setSelected] = useState<string>("AAPL");
  const [interval, setIntervalTf] = useState<Interval>("1h");
  const [klines, setKlines] = useState<Kline[]>([]);
  const [market, setMarket] = useState<MarketStatus | null>(null);
  const [detail, setDetail] = useState<Dynamic | null>(null);
  const [tokenMeta, setTokenMeta] = useState<StockToken | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const loadUniverse = useCallback(async () => {
    const res = await fetch(
      `/api/market/binance/rwa/stocks?type=1&preferChainId=56`,
    );
    if (!res.ok) throw new Error(`stocks ${res.status}`);
    const body = (await res.json()) as { data?: StockToken[] };
    setUniverse(body.data ?? []);
  }, []);

  const loadMarket = useCallback(async () => {
    const res = await fetch(`/api/market/binance/rwa/market/status`);
    if (!res.ok) return;
    const body = (await res.json()) as { data?: MarketStatus };
    setMarket(body.data ?? null);
  }, []);

  const loadWatchQuotes = useCallback(async () => {
    const list =
      universe.length > 0
        ? WATCH.map((t) => universe.find((u) => u.ticker === t)).filter(
            Boolean,
          ) as StockToken[]
        : [];
    if (!list.length) return;
    const quotes = await Promise.all(
      list.map(async (token) => {
        try {
          const res = await fetch(
            `/api/market/binance/rwa/dynamic?chainId=${token.chainId}&contractAddress=${token.contractAddress}`,
          );
          if (!res.ok) return { token, dynamic: null };
          const body = (await res.json()) as { data?: Dynamic };
          return { token, dynamic: body.data ?? null };
        } catch {
          return { token, dynamic: null };
        }
      }),
    );
    setRows(quotes);
  }, [universe]);

  const loadDetail = useCallback(async (ticker: string) => {
    const res = await fetch(
      `/api/market/binance/rwa/quote?ticker=${encodeURIComponent(ticker)}&preferChainId=56`,
    );
    if (!res.ok) throw new Error(`quote ${res.status}`);
    const body = (await res.json()) as {
      token: StockToken;
      dynamic: Dynamic;
      chainId: string;
      contractAddress: string;
    };
    setTokenMeta(body.token);
    setDetail(body.dynamic);
    return body;
  }, []);

  const loadKlines = useCallback(
    async (chainId: string, contract: string, tf: Interval) => {
      const res = await fetch(
        `/api/market/binance/rwa/klines?chainId=${chainId}&contractAddress=${contract}&interval=${tf}&limit=200`,
      );
      if (!res.ok) return;
      const body = (await res.json()) as {
        data?: { klineInfos?: unknown[][] };
      };
      const infos = body.data?.klineInfos ?? [];
      const mapped: Kline[] = infos.map((row) => [
        Number(row[0]),
        String(row[1]),
        String(row[2]),
        String(row[3]),
        String(row[4]),
        String(row[5] ?? "0"),
      ]);
      setKlines(mapped);
    },
    [],
  );

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([loadUniverse(), loadMarket()]);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [loadUniverse, loadMarket]);

  useEffect(() => {
    if (!universe.length) return;
    void loadWatchQuotes();
    const id = setInterval(() => setTick((n) => n + 1), 12_000);
    return () => clearInterval(id);
  }, [universe, loadWatchQuotes]);

  useEffect(() => {
    if (tick === 0) return;
    void loadWatchQuotes();
    void loadMarket();
  }, [tick, loadWatchQuotes, loadMarket]);

  useEffect(() => {
    void (async () => {
      try {
        const q = await loadDetail(selected);
        await loadKlines(q.chainId, q.contractAddress, interval);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [selected, interval, loadDetail, loadKlines]);

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    const base = rows.length
      ? rows
      : WATCH.map((t) => {
          const token = universe.find((u) => u.ticker === t);
          return token ? { token, dynamic: null } : null;
        }).filter(Boolean) as QuoteRow[];
    if (!q) return base;
    return base.filter(
      (r) =>
        r.token.ticker.includes(q) ||
        r.token.symbol.toUpperCase().includes(q),
    );
  }, [rows, universe, query]);

  const ti = detail?.tokenInfo;
  const si = detail?.stockInfo;
  const mult = ti?.sharesMultiplier || tokenMeta?.multiplier || "1";
  const tokenPx = Number(ti?.price);
  const ref = refPrice(ti?.price, mult);
  const chg = Number(ti?.priceChangePct24h ?? 0);
  const up = chg >= 0;
  const open = market?.openState === true;

  return (
    <div className="bn-page">
      <header className="bn-top">
        <div className="bn-top-pair">
          <div className="bn-top-name">
            <select
              className="bn-pair-select"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              aria-label="Stock ticker"
            >
              {WATCH.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <span className="bn-pill">Ondo · Tokenized</span>
            <span className={open ? "bn-pill bn-pill-open" : "bn-pill bn-pill-closed"}>
              {market?.marketStatus ?? (open ? "open" : "closed")}
            </span>
          </div>
          <div className={`bn-top-last ${up ? "up" : "down"}`}>
            {ti?.price ? fmt(ti.price, 2) : "—"}
            <span className="bn-top-unit"> token USD</span>
          </div>
        </div>
        <div className="bn-top-stats">
          <div>
            <span className="bn-label">24h Change</span>
            <span className={up ? "up" : "down"}>
              {ti
                ? `${up ? "+" : ""}${fmt(ti.priceChange24h, 2)} (${up ? "+" : ""}${fmt(chg, 2)}%)`
                : "—"}
            </span>
          </div>
          <div>
            <span className="bn-label">Ref / share</span>
            <span>{ref != null ? fmt(ref, 2) : "—"}</span>
          </div>
          <div>
            <span className="bn-label">Multiplier</span>
            <span>{fmt(mult, 6)}</span>
          </div>
          <div>
            <span className="bn-label">Stock P/E</span>
            <span>{si?.priceToEarnings ?? "—"}</span>
          </div>
          <div>
            <span className="bn-label">Div Yield</span>
            <span>
              {si?.dividendYield != null ? `${fmt(si.dividendYield, 2)}%` : "—"}
            </span>
          </div>
          <div>
            <span className="bn-label">52w Range</span>
            <span>
              {si?.priceLow52w && si?.priceHigh52w
                ? `${fmt(si.priceLow52w)} – ${fmt(si.priceHigh52w)}`
                : "—"}
            </span>
          </div>
        </div>
      </header>

      {error ? <pre className="error bn-error">{error}</pre> : null}

      <div className="bn-main bn-main-quotes">
        <aside className="bn-card bn-markets">
          <div className="bn-card-head">
            <span>Watchlist</span>
            <span className="bn-label">{universe.length} listed</span>
          </div>
          <input
            className="bn-search"
            placeholder="Search ticker"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="bn-mkt-head bn-mkt-head-stock">
            <span>Ticker</span>
            <span>Token</span>
            <span>24h%</span>
          </div>
          <div className="bn-mkt-body">
            {filtered.map((r) => {
              const pct = Number(r.dynamic?.tokenInfo?.priceChangePct24h ?? NaN);
              const active = r.token.ticker === selected;
              return (
                <button
                  key={r.token.ticker}
                  type="button"
                  className={
                    active ? "bn-mkt-row-stock active" : "bn-mkt-row-stock"
                  }
                  onClick={() => setSelected(r.token.ticker)}
                >
                  <span className="bn-mkt-pair">
                    {r.token.ticker}
                    <em>{r.token.symbol}</em>
                  </span>
                  <span className="bn-mono">
                    {fmt(r.dynamic?.tokenInfo?.price, 2)}
                  </span>
                  <span
                    className={
                      Number.isFinite(pct) ? (pct >= 0 ? "up" : "down") : ""
                    }
                  >
                    {Number.isFinite(pct)
                      ? `${pct >= 0 ? "+" : ""}${fmt(pct, 2)}%`
                      : "—"}
                  </span>
                </button>
              );
            })}
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
            <span className="bn-label">Token K-Line · read-only</span>
          </div>
          <BinanceChart
            klines={klines}
            symbol={`${selected}on`}
          />
        </section>

        <aside className="bn-right bn-right-quotes">
          <div className="bn-card bn-book bn-book-tall bn-fund">
            <div className="bn-card-head">
              <span>Fundamentals</span>
              <span className="bn-label">{detail?.symbol ?? "—"}</span>
            </div>
            <dl className="bn-fund-list">
              <div>
                <dt>Token price</dt>
                <dd>{fmt(ti?.price, 4)}</dd>
              </div>
              <div>
                <dt>Ref (price÷mult)</dt>
                <dd>{ref != null ? fmt(ref, 4) : "—"}</dd>
              </div>
              <div>
                <dt>US stock price</dt>
                <dd>{si?.price != null ? fmt(si.price, 2) : "—"}</dd>
              </div>
              <div>
                <dt>Holders</dt>
                <dd>{fmt(ti?.totalHolders, 0)}</dd>
              </div>
              <div>
                <dt>Token mcap</dt>
                <dd>{fmt(ti?.marketCap, 2)}</dd>
              </div>
              <div>
                <dt>Stock mcap</dt>
                <dd>{fmt(si?.marketCap, 2)}</dd>
              </div>
              <div>
                <dt>Stock volume</dt>
                <dd>{fmt(si?.volume, 0)}</dd>
              </div>
              <div>
                <dt>Token vol (USD)*</dt>
                <dd>{fmt(ti?.volume24h, 2)}</dd>
              </div>
              <div>
                <dt>Circulating</dt>
                <dd>{fmt(ti?.circulatingSupply, 2)}</dd>
              </div>
              <div>
                <dt>Asset status</dt>
                <dd>
                  {detail?.statusInfo?.marketStatus ??
                    detail?.statusInfo?.reasonCode ??
                    "—"}
                </dd>
              </div>
              <div>
                <dt>Chain</dt>
                <dd>
                  {tokenMeta?.chainId === "56"
                    ? "BSC"
                    : tokenMeta?.chainId === "1"
                      ? "ETH"
                      : tokenMeta?.chainId ?? "—"}
                </dd>
              </div>
              <div>
                <dt>Contract</dt>
                <dd className="bn-addr">
                  {tokenMeta?.contractAddress
                    ? `${tokenMeta.contractAddress.slice(0, 10)}…`
                    : "—"}
                </dd>
              </div>
            </dl>
            <p className="bn-demo-hint">
              *tokenInfo.volume24h 为底层美股成交额（USD），非链上 DEX 量。
              代币 ≠ 1 股：ref = token÷multiplier。
            </p>
          </div>
        </aside>
      </div>

      <footer className="bn-status">
        <span className="bn-status-dot" />
        <span>Binance Ondo RWA Public API</span>
        <span className="bn-label">·</span>
        <span className="bn-label">
          Tokenized stocks · Quotes only · EquityLab
        </span>
        <span className="bn-status-right">
          {selected}
          {Number.isFinite(tokenPx) ? ` · ${fmt(tokenPx, 2)}` : ""}
          {market?.nextClose ? ` · nextClose ${market.nextClose}` : ""}
        </span>
      </footer>
    </div>
  );
}
