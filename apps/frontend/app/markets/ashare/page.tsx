"use client";

/**
 * A 股只读行情台（adata）。
 * BFF：/api/ashare/* → Gateway /api/research/ashare/*
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BinanceChart,
  type Kline,
} from "../../components/markets/BinanceChart";

const PRIORITY = [
  "600519",
  "000001",
  "300750",
  "601318",
  "000858",
  "002594",
  "600036",
  "601012",
  "688981",
  "510300",
  "000568",
  "600900",
  "601899",
  "300059",
  "002475",
] as const;

const INTERVALS = [
  { id: "1d", label: "日K" },
  { id: "1w", label: "周K" },
  { id: "1M", label: "月K" },
  { id: "60m", label: "60分" },
  { id: "30m", label: "30分" },
  { id: "15m", label: "15分" },
  { id: "5m", label: "5分" },
] as const;

type CodeRow = {
  stock_code: string;
  short_name: string;
  exchange: string;
  symbol: string;
};

type Quote = {
  stock_code: string;
  short_name: string;
  price?: number | string;
  change?: number | string;
  change_pct?: number | string;
  volume?: number | string;
  amount?: number | string;
};

type FiveRow = Record<string, unknown>;

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

export default function AsharePage() {
  const [query, setQuery] = useState("");
  const [codes, setCodes] = useState<CodeRow[]>([]);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [selected, setSelected] = useState("600519");
  const [kType, setKType] = useState<string>("1d");
  const [klines, setKlines] = useState<Kline[]>([]);
  const [five, setFive] = useState<FiveRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [loadingCodes, setLoadingCodes] = useState(true);

  const loadCodes = useCallback(async () => {
    setLoadingCodes(true);
    // 先用热门种子占位，避免 all_code 慢导致空白
    setCodes(
      PRIORITY.map((stock_code) => ({
        stock_code,
        short_name: "",
        exchange: stock_code.startsWith("6") || stock_code.startsWith("5") ? "SH" : "SZ",
        symbol: `${stock_code}.CN`,
      })),
    );
    try {
      const res = await fetch(`/api/ashare/codes?limit=8000`);
      if (!res.ok) throw new Error(`codes ${res.status}`);
      const body = (await res.json()) as { data?: CodeRow[] };
      if (body.data?.length) setCodes(body.data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingCodes(false);
    }
  }, []);

  const loadQuotes = useCallback(async (list: string[]) => {
    if (!list.length) return;
    const res = await fetch(
      `/api/ashare/quotes?codes=${encodeURIComponent(list.join(","))}`,
    );
    if (!res.ok) return;
    const body = (await res.json()) as { data?: Quote[] };
    setQuotes((prev) => {
      const next = { ...prev };
      for (const q of body.data ?? []) {
        next[q.stock_code] = q;
      }
      return next;
    });
  }, []);

  const loadKlines = useCallback(async (code: string, kt: string) => {
    const res = await fetch(
      `/api/ashare/klines/${code}?k_type=${encodeURIComponent(kt)}&limit=300&adjust_type=1`,
    );
    if (!res.ok) throw new Error(`klines ${res.status}`);
    const body = (await res.json()) as {
      data?: {
        time?: number | null;
        open?: number;
        high?: number;
        low?: number;
        close?: number;
        volume?: number;
      }[];
    };
    const mapped: Kline[] = (body.data ?? [])
      .filter((r) => r.time != null)
      .map((r) => [
        Number(r.time),
        String(r.open ?? 0),
        String(r.high ?? 0),
        String(r.low ?? 0),
        String(r.close ?? 0),
        String(r.volume ?? 0),
      ]);
    setKlines(mapped);
  }, []);

  const loadFive = useCallback(async (code: string) => {
    try {
      const res = await fetch(`/api/ashare/five/${code}`);
      if (!res.ok) {
        setFive([]);
        return;
      }
      const body = (await res.json()) as { data?: FiveRow[] };
      setFive(body.data ?? []);
    } catch {
      setFive([]);
    }
  }, []);

  useEffect(() => {
    void loadCodes();
  }, [loadCodes]);

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    const priorityIdx = new Map(PRIORITY.map((c, i) => [c, i]));
    let list = [...codes];
    if (q) {
      list = list.filter(
        (c) =>
          c.stock_code.includes(q) ||
          c.short_name.toUpperCase().includes(q) ||
          c.symbol.includes(q),
      );
    }
    list.sort((a, b) => {
      const pa = priorityIdx.get(a.stock_code as (typeof PRIORITY)[number]) ?? 999;
      const pb = priorityIdx.get(b.stock_code as (typeof PRIORITY)[number]) ?? 999;
      if (pa !== pb) return pa - pb;
      return a.stock_code.localeCompare(b.stock_code);
    });
    return list;
  }, [codes, query]);

  useEffect(() => {
    if (!codes.length) return;
    const want = new Set<string>([...PRIORITY, selected]);
    if (query.trim()) {
      for (const c of filtered.slice(0, 40)) want.add(c.stock_code);
    }
    void loadQuotes([...want]);
    const id = setInterval(() => setTick((n) => n + 1), 15_000);
    return () => clearInterval(id);
  }, [codes, selected, query, filtered, loadQuotes]);

  useEffect(() => {
    if (tick === 0) return;
    const want = new Set<string>([...PRIORITY, selected]);
    if (query.trim()) {
      for (const c of filtered.slice(0, 40)) want.add(c.stock_code);
    }
    void loadQuotes([...want]);
  }, [tick, selected, query, filtered, loadQuotes]);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([loadKlines(selected, kType), loadFive(selected)]);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, [selected, kType, loadKlines, loadFive]);

  const q = quotes[selected];
  const meta = codes.find((c) => c.stock_code === selected);
  const name = q?.short_name || meta?.short_name || selected;
  const chg = Number(q?.change_pct ?? 0);
  const up = chg >= 0;
  const displayList = filtered.slice(0, query.trim() ? 500 : 800);

  return (
    <div className="bn-page">
      <header className="bn-top">
        <div className="bn-top-pair">
          <div className="bn-top-name">
            <select
              className="bn-pair-select"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              aria-label="A-share code"
            >
              {displayList.slice(0, 300).map((c) => (
                <option key={c.stock_code} value={c.stock_code}>
                  {c.stock_code} {c.short_name}
                </option>
              ))}
              {!displayList.some((c) => c.stock_code === selected) ? (
                <option value={selected}>{selected}</option>
              ) : null}
            </select>
            <span className="bn-pill">A-Share · adata</span>
          </div>
          <div className={`bn-top-last ${up ? "up" : "down"}`}>
            {q?.price != null ? fmt(q.price, 2) : "—"}
            <span className="bn-top-unit"> CNY</span>
          </div>
        </div>
        <div className="bn-top-stats">
          <div>
            <span className="bn-label">名称</span>
            <span>{name}</span>
          </div>
          <div>
            <span className="bn-label">涨跌幅</span>
            <span className={up ? "up" : "down"}>
              {q
                ? `${up ? "+" : ""}${fmt(q.change, 2)} (${up ? "+" : ""}${fmt(chg, 2)}%)`
                : "—"}
            </span>
          </div>
          <div>
            <span className="bn-label">成交量</span>
            <span>{fmt(q?.volume, 0)}</span>
          </div>
          <div>
            <span className="bn-label">成交额</span>
            <span>{fmt(q?.amount, 2)}</span>
          </div>
          <div>
            <span className="bn-label">市场</span>
            <span>{meta?.exchange ?? "—"}</span>
          </div>
        </div>
      </header>

      {error ? <pre className="error bn-error">{error}</pre> : null}

      <div className="bn-main bn-main-quotes">
        <aside className="bn-card bn-markets">
          <div className="bn-card-head">
            <span>Markets</span>
            <span className="bn-label">
              {loadingCodes
                ? "loading…"
                : `${displayList.length}${query ? ` / ${codes.length}` : ""}`}
            </span>
          </div>
          <input
            className="bn-search"
            placeholder="搜索代码 / 名称"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="bn-mkt-head bn-mkt-head-stock">
            <span>代码</span>
            <span>现价</span>
            <span>涨跌%</span>
          </div>
          <div className="bn-mkt-body">
            {displayList.map((c) => {
              const qq = quotes[c.stock_code];
              const pct = Number(qq?.change_pct ?? NaN);
              const active = c.stock_code === selected;
              return (
                <button
                  key={c.stock_code}
                  type="button"
                  className={
                    active ? "bn-mkt-row-stock active" : "bn-mkt-row-stock"
                  }
                  onClick={() => setSelected(c.stock_code)}
                >
                  <span className="bn-mkt-pair">
                    {c.stock_code}
                    <em>{c.short_name}</em>
                  </span>
                  <span className="bn-mono">{fmt(qq?.price, 2)}</span>
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
            {!loadingCodes && !displayList.length ? (
              <p className="bn-empty">无匹配标的</p>
            ) : null}
          </div>
        </aside>

        <section className="bn-card bn-chart-panel">
          <div className="bn-tf-row">
            <div className="bn-tf-group">
              <span className="bn-tf-label">周期</span>
              {INTERVALS.map((tf) => (
                <button
                  key={tf.id}
                  type="button"
                  className={tf.id === kType ? "bn-tf active" : "bn-tf"}
                  onClick={() => setKType(tf.id)}
                >
                  {tf.label}
                </button>
              ))}
            </div>
            <span className="bn-label">adata · 前复权 · 只读</span>
          </div>
          <BinanceChart klines={klines} symbol={`${selected}.CN`} />
        </section>

        <aside className="bn-right bn-right-quotes">
          <div className="bn-card bn-book bn-book-tall bn-fund">
            <div className="bn-card-head">
              <span>五档 / 快照</span>
              <span className="bn-label">{selected}</span>
            </div>
            {five.length ? (
              <div className="bn-ashare-five">
                <pre className="bn-ashare-five-pre">
                  {JSON.stringify(five.slice(0, 12), null, 2)}
                </pre>
              </div>
            ) : (
              <dl className="bn-fund-list">
                <div>
                  <dt>现价</dt>
                  <dd>{fmt(q?.price, 2)}</dd>
                </div>
                <div>
                  <dt>涨跌</dt>
                  <dd className={up ? "up" : "down"}>{fmt(q?.change, 2)}</dd>
                </div>
                <div>
                  <dt>涨跌幅</dt>
                  <dd className={up ? "up" : "down"}>{fmt(chg, 2)}%</dd>
                </div>
                <div>
                  <dt>成交量</dt>
                  <dd>{fmt(q?.volume, 0)}</dd>
                </div>
                <div>
                  <dt>成交额</dt>
                  <dd>{fmt(q?.amount, 2)}</dd>
                </div>
              </dl>
            )}
            <p className="bn-demo-hint">
              数据来自开源库{" "}
              <a
                href="https://github.com/1nchaos/adata"
                target="_blank"
                rel="noreferrer"
              >
                1nchaos/adata
              </a>
              ；多源公开行情，非券商实盘。列表默认展示前 800，搜索可筛全库。
            </p>
          </div>
        </aside>
      </div>

      <footer className="bn-status">
        <span className="bn-status-dot" />
        <span>adata A-Share</span>
        <span className="bn-label">·</span>
        <span className="bn-label">Quotes only · EquityLab Research</span>
        <span className="bn-status-right">
          {selected} {name}
          {q?.price != null ? ` · ${fmt(q.price, 2)}` : ""}
        </span>
      </footer>
    </div>
  );
}
