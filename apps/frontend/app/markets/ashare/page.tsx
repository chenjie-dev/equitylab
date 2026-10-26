"use client";

/**
 * A 股行情台（同花顺启发布局）：左列表 | 右报价+分时/K线+五档。
 * 只读 qdb；BFF `/api/ashare/*` → Gateway `/api/research/ashare/*`。
 */

import {
  startTransition,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  BinanceChart,
  type Kline,
} from "../../components/markets/BinanceChart";
import { useListKeyboard } from "../../components/markets/useListKeyboard";
import {
  flashClass,
  usePriceFlash,
} from "../../components/markets/usePriceFlash";
import { VirtualMktList } from "../../components/markets/VirtualMktList";
import { useQdbSnapshot } from "../../components/markets/useQdbSnapshot";

/** 与 research/collector 一致：北交所 4/8/92 → BSE；须先于「9→SSE」。 */
function ashareQdbSymbol(code: string): string {
  const c = code.replace(/\D/g, "").slice(-6).padStart(6, "0");
  let ex = "SZSE";
  if (c.startsWith("4") || c.startsWith("8") || c.startsWith("92")) {
    ex = "BSE";
  } else if (c.startsWith("5") || c.startsWith("6") || c.startsWith("9")) {
    ex = "SSE";
  }
  return `${ex}:${c}`;
}

/**
 * 热门置顶（与 collector seed / K 线回填集对齐）。
 * 全市场代码来自 qdb `ashare:codes`（数千）；列表报价 round-robin 有滞后。
 * K 线历史默认仅 seed/priority 有回填，其余可能只有盘中快照合成。
 */
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
  "830879",
  "835185",
  "000568",
  "600900",
  "601899",
  "300059",
  "002475",
  "600276",
  "000333",
  "601166",
  "600030",
  "002415",
] as const;

/** research `/ashare/quotes` 单次最多约 80；分块拉全列表。 */
const QUOTE_CHUNK = 60;

/** 主 Tab：分时 | 日K | 其他周期 */
type ChartTab = "intraday" | "1d" | "other";

const OTHER_INTERVALS = [
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
  open?: number | string;
  high?: number | string;
  low?: number | string;
  pre_close?: number | string;
  change?: number | string;
  change_pct?: number | string;
  volume?: number | string;
  amount?: number | string;
  bid?: number | string;
  ask?: number | string;
};

type BookLevel = { price: number; volume: number | null };

type FiveBook = {
  bids: BookLevel[];
  asks: BookLevel[];
  levels: number;
  note: string;
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

function fmtVol(n: string | number | null | undefined): string {
  if (n == null || n === "") return "—";
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "—";
  // A 股量常为股；展示手数（÷100）更贴近终端习惯
  const hands = v / 100;
  if (hands >= 10_000) return `${(hands / 10_000).toFixed(2)}万`;
  if (hands >= 1) return hands.toFixed(0);
  return fmt(v, 0);
}

function mapCandles(
  rows: {
    time?: number | null;
    open?: number;
    high?: number;
    low?: number;
    close?: number;
    volume?: number;
  }[],
): Kline[] {
  return rows
    .filter((r) => r.time != null)
    .map((r) => [
      Number(r.time),
      String(r.open ?? 0),
      String(r.high ?? 0),
      String(r.low ?? 0),
      String(r.close ?? 0),
      String(r.volume ?? 0),
    ]);
}

export default function AsharePage() {
  const [query, setQuery] = useState("");
  const [codes, setCodes] = useState<CodeRow[]>([]);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [selected, setSelected] = useState("600519");
  const [chartTab, setChartTab] = useState<ChartTab>("intraday");
  const [otherK, setOtherK] = useState<string>("60m");
  const [klines, setKlines] = useState<Kline[]>([]);
  const [five, setFive] = useState<FiveBook>({
    bids: [],
    asks: [],
    levels: 0,
    note: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [loadingCodes, setLoadingCodes] = useState(true);
  const [catalogNote, setCatalogNote] = useState<string | null>(null);
  const [kMeta, setKMeta] = useState<{
    session?: string;
    historyCount?: number;
    hasRealtime?: boolean;
    view?: string;
  }>({});

  const activeKType = chartTab === "1d" ? "1d" : chartTab === "intraday" ? "intraday" : otherK;

  const loadCodes = useCallback(async () => {
    setLoadingCodes(true);
    setCodes(
      PRIORITY.map((stock_code) => ({
        stock_code,
        short_name: "",
        exchange:
          stock_code.startsWith("6") || stock_code.startsWith("5") ? "SH" : "SZ",
        symbol: `${stock_code}.CN`,
      })),
    );
    try {
      const res = await fetch(`/api/ashare/codes?limit=10000`);
      if (!res.ok) throw new Error(`codes ${res.status}`);
      const body = (await res.json()) as {
        data?: CodeRow[];
        meta?: { note?: string; universe?: string; catalog_count?: number };
      };
      if (body.data?.length) setCodes(body.data);
      if (body.meta?.note) {
        setCatalogNote(
          body.meta.universe === "full"
            ? `全市场 ${body.meta.catalog_count ?? body.data?.length ?? "—"} 只；报价分批刷新（有滞后）；K 线完整回填仅热门 seed`
            : body.meta.note,
        );
      } else {
        setCatalogNote(null);
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingCodes(false);
    }
  }, []);

  const loadQuotes = useCallback(async (list: string[]) => {
    const unique = [...new Set(list.map((c) => c.replace(/\D/g, "").slice(-6)).filter(Boolean))];
    if (!unique.length) return;
    for (let i = 0; i < unique.length; i += QUOTE_CHUNK) {
      const chunk = unique.slice(i, i + QUOTE_CHUNK);
      const res = await fetch(
        `/api/ashare/quotes?codes=${encodeURIComponent(chunk.join(","))}`,
      );
      if (!res.ok) continue;
      const body = (await res.json()) as { data?: Quote[] };
      setQuotes((prev) => {
        const next = { ...prev };
        for (const q of body.data ?? []) {
          next[q.stock_code] = { ...prev[q.stock_code], ...q };
        }
        return next;
      });
    }
  }, []);

  const loadKlines = useCallback(async (code: string, kt: string) => {
    if (kt === "intraday") {
      const res = await fetch(`/api/ashare/intraday/${code}`);
      if (!res.ok) throw new Error(`intraday ${res.status}`);
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
      setKlines(mapCandles(body.data ?? []));
      setKMeta({
        session: undefined,
        historyCount: body.data?.length,
        hasRealtime: false,
        view: "intraday-5m",
      });
      return;
    }
    const res = await fetch(
      `/api/ashare/klines/${code}?k_type=${encodeURIComponent(kt)}&limit=300&adjust_type=1&view=merged`,
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
      session?: { status?: string };
      history?: { count?: number };
      realtime?: { bar?: unknown } | null;
      view?: string;
    };
    setKlines(mapCandles(body.data ?? []));
    setKMeta({
      session: body.session?.status,
      historyCount: body.history?.count,
      hasRealtime: Boolean(body.realtime?.bar),
      view: body.view ?? "merged",
    });
  }, []);

  const loadFive = useCallback(async (code: string) => {
    try {
      const res = await fetch(`/api/ashare/five/${code}`);
      if (!res.ok) {
        setFive({ bids: [], asks: [], levels: 0, note: `五档 ${res.status}` });
        return;
      }
      const body = (await res.json()) as {
        bids?: BookLevel[];
        asks?: BookLevel[];
        levels?: number;
        note?: string;
        quote?: Quote;
        data?: Quote[];
      };
      const quote = body.quote ?? body.data?.[0];
      if (quote) {
        setQuotes((prev) => ({
          ...prev,
          [code]: { ...prev[code], ...quote, stock_code: code },
        }));
      }
      setFive({
        bids: body.bids ?? [],
        asks: body.asks ?? [],
        levels: body.levels ?? 0,
        note: body.note ?? "",
      });
    } catch {
      setFive({ bids: [], asks: [], levels: 0, note: "五档不可用" });
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

  const displayList = useMemo(
    () => filtered.slice(0, query.trim() ? 500 : 800),
    [filtered, query],
  );
  const listIds = useMemo(
    () => displayList.map((c) => c.stock_code),
    [displayList],
  );
  useListKeyboard(listIds, selected, setSelected, Boolean(listIds.length));

  // 拉取当前展示列表全部报价（分块），不只 PRIORITY / 前几行
  useEffect(() => {
    if (!displayList.length) return;
    const want = displayList.map((c) => c.stock_code);
    if (selected && !want.includes(selected)) want.push(selected);
    void loadQuotes(want);
    const id = setInterval(() => setTick((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, [displayList, selected, loadQuotes]);

  useEffect(() => {
    if (tick === 0) return;
    const want = displayList.map((c) => c.stock_code);
    if (selected && !want.includes(selected)) want.push(selected);
    void loadQuotes(want);
  }, [tick, displayList, selected, loadQuotes]);

  useQdbSnapshot(selected ? ashareQdbSymbol(selected) : null, (row) => {
    const price = row.last;
    setQuotes((prev) => {
      const cur = prev[selected];
      const pre = Number(cur?.pre_close);
      let change = cur?.change;
      let changePct = cur?.change_pct;
      if (Number.isFinite(price) && Number.isFinite(pre) && pre !== 0) {
        change = Math.round((price - pre) * 10000) / 10000;
        changePct = Math.round(((price - pre) / pre) * 10000) / 100;
      }
      return {
        ...prev,
        [selected]: {
          ...cur,
          stock_code: selected,
          short_name: cur?.short_name ?? "",
          price,
          change,
          change_pct: changePct,
          bid: row.bid ?? cur?.bid,
          ask: row.ask ?? cur?.ask,
        },
      };
    });
  });

  useEffect(() => {
    // 先清空，避免 seriesKey 已换、K 线仍是上只票时被图表尾巴 update 粘住
    setKlines([]);
    setKMeta({});
    void (async () => {
      try {
        await Promise.all([loadKlines(selected, activeKType), loadFive(selected)]);
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
    const id = setInterval(() => {
      void loadKlines(selected, activeKType).catch(() => undefined);
      void loadFive(selected);
    }, 15_000);
    return () => clearInterval(id);
  }, [selected, activeKType, loadKlines, loadFive]);

  const q = quotes[selected];
  const meta = codes.find((c) => c.stock_code === selected);
  const name = q?.short_name || meta?.short_name || selected;
  const chg = Number(q?.change_pct ?? 0);
  const up = Number.isFinite(chg) ? chg >= 0 : true;
  const lastFlash = usePriceFlash(q?.price);

  // 五档展示：卖五→卖一（上），买一→买五（下）；缺档补空行到 5
  const askRows = useMemo(() => {
    const rows = [...five.asks].slice(0, 5);
    while (rows.length < 5) rows.push({ price: NaN, volume: null });
    return rows.reverse();
  }, [five.asks]);
  const bidRows = useMemo(() => {
    const rows = [...five.bids].slice(0, 5);
    while (rows.length < 5) rows.push({ price: NaN, volume: null });
    return rows;
  }, [five.bids]);

  const maxBookVol = useMemo(() => {
    const vols = [...five.bids, ...five.asks]
      .map((l) => Number(l.volume ?? 0))
      .filter((v) => Number.isFinite(v) && v > 0);
    return vols.length ? Math.max(...vols) : 1;
  }, [five.bids, five.asks]);

  return (
    <div className="bn-page wind ths">
      <header className="bn-top ths-top">
        <div className="bn-top-pair">
          <div className="bn-top-name">
            <span className="ths-code">{selected}</span>
            <span className="ths-name">{name}</span>
            <span className="bn-pill">A股</span>
            {kMeta.session ? (
              <span
                className={
                  kMeta.session === "trading"
                    ? "bn-pill bn-pill-open"
                    : "bn-pill bn-pill-closed"
                }
              >
                {kMeta.session}
              </span>
            ) : null}
          </div>
          <div
            className={`bn-top-last ${up ? "up" : "down"} ${flashClass(lastFlash)}`}
          >
            {q?.price != null ? fmt(q.price, 2) : "—"}
            <span className="bn-top-unit">CNY</span>
          </div>
        </div>
        <div className="bn-top-stats ths-stats">
          <div>
            <span className="bn-label">涨跌</span>
            <span className={up ? "up" : "down"}>
              {q
                ? `${up ? "+" : ""}${fmt(q.change, 2)}`
                : "—"}
            </span>
          </div>
          <div>
            <span className="bn-label">涨跌幅</span>
            <span className={up ? "up" : "down"}>
              {q ? `${up ? "+" : ""}${fmt(chg, 2)}%` : "—"}
            </span>
          </div>
          <div>
            <span className="bn-label">今开</span>
            <span>{fmt(q?.open, 2)}</span>
          </div>
          <div>
            <span className="bn-label">最高</span>
            <span className="up">{fmt(q?.high, 2)}</span>
          </div>
          <div>
            <span className="bn-label">最低</span>
            <span className="down">{fmt(q?.low, 2)}</span>
          </div>
          <div>
            <span className="bn-label">昨收</span>
            <span>{fmt(q?.pre_close, 2)}</span>
          </div>
          <div>
            <span className="bn-label">成交量</span>
            <span>{fmtVol(q?.volume)}</span>
          </div>
          <div>
            <span className="bn-label">成交额</span>
            <span>{fmt(q?.amount, 2)}</span>
          </div>
        </div>
      </header>

      <div className="bn-quote-strip ths-strip">
        <span className="bn-label">↑↓ / j k 切换标的</span>
        <span className="bn-label">·</span>
        <span className="bn-label">
          {meta?.exchange ?? "—"} · 只读 qdb
        </span>
        {catalogNote ? (
          <>
            <span className="bn-label">·</span>
            <span className="bn-label" title={catalogNote}>
              {catalogNote}
            </span>
          </>
        ) : null}
      </div>

      {error ? <pre className="error bn-error">{error}</pre> : null}

      <div className="bn-main bn-main-quotes ths-main">
        <aside className="bn-card bn-markets ths-list">
          <div className="bn-card-head">
            <span>行情列表</span>
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
            aria-label="搜索 A 股"
          />
          <div className="bn-mkt-head bn-mkt-head-stock">
            <span>代码</span>
            <span>现价</span>
            <span>涨跌%</span>
          </div>
          <VirtualMktList
            className="bn-mkt-body"
            items={displayList}
            rowHeight={40}
            height={560}
            keyOf={(c) => c.stock_code}
            empty={<p className="bn-empty">无匹配标的</p>}
            renderRow={(c) => (
              <AshareMktRow
                row={c}
                quote={quotes[c.stock_code]}
                active={c.stock_code === selected}
                onPick={() => {
                  startTransition(() => setSelected(c.stock_code));
                }}
              />
            )}
          />
        </aside>

        <section className="bn-card bn-chart-panel ths-chart">
          <div className="bn-tf-row ths-tabs">
            <div className="bn-tf-group">
              <button
                type="button"
                className={chartTab === "intraday" ? "bn-tf active" : "bn-tf"}
                onClick={() => setChartTab("intraday")}
              >
                分时
              </button>
              <button
                type="button"
                className={chartTab === "1d" ? "bn-tf active" : "bn-tf"}
                onClick={() => setChartTab("1d")}
              >
                日K
              </button>
              <button
                type="button"
                className={chartTab === "other" ? "bn-tf active" : "bn-tf"}
                onClick={() => setChartTab("other")}
              >
                其他周期
              </button>
            </div>
            {chartTab === "other" ? (
              <div className="bn-tf-group ths-other">
                {OTHER_INTERVALS.map((tf) => (
                  <button
                    key={tf.id}
                    type="button"
                    className={tf.id === otherK ? "bn-tf active" : "bn-tf"}
                    onClick={() => setOtherK(tf.id)}
                  >
                    {tf.label}
                  </button>
                ))}
              </div>
            ) : null}
            <span className="bn-label">
              {chartTab === "intraday"
                ? `分时 · 5 分钟合成 · ${kMeta.historyCount ?? klines.length} 根`
                : kMeta.hasRealtime
                  ? `历史 ${kMeta.historyCount ?? "—"} + 实时 · ${kMeta.session ?? "—"}`
                  : `纯历史 ${kMeta.historyCount ?? klines.length} · ${kMeta.session ?? "closed"}`}
              {chartTab !== "intraday" ? " · 前复权" : ""}
            </span>
          </div>
          <BinanceChart
            klines={klines}
            symbol={`${selected}.CN`}
            seriesKey={`${selected}:${activeKType}`}
            palette="wind"
          />
        </section>

        <aside className="bn-right bn-right-quotes ths-book">
          <div className="bn-card bn-book bn-book-tall">
            <div className="bn-card-head">
              <span>五档买卖</span>
              <span className="bn-label">
                {five.levels > 0 ? `${five.levels} 档` : "—"}
              </span>
            </div>
            <div className="ths-five-head">
              <span>卖盘</span>
              <span>价格</span>
              <span>量(手)</span>
            </div>
            <div className="ths-five-body">
              {askRows.map((lv, i) => {
                const rank = 5 - i;
                const ok = Number.isFinite(lv.price);
                const bar = ok
                  ? Math.min(100, (Number(lv.volume ?? 0) / maxBookVol) * 100)
                  : 0;
                return (
                  <div key={`a${rank}`} className="ths-five-row ask">
                    <span className="ths-five-side">卖{rank}</span>
                    <span className="down">
                      {ok ? fmt(lv.price, 2) : "—"}
                    </span>
                    <span className="ths-five-vol">
                      <i style={{ width: `${bar}%` }} />
                      {ok ? fmtVol(lv.volume) : "—"}
                    </span>
                  </div>
                );
              })}
              <div className="ths-five-mid">
                <span className={up ? "up" : "down"}>
                  {q?.price != null ? fmt(q.price, 2) : "—"}
                </span>
                <span className="bn-label">最新</span>
              </div>
              {bidRows.map((lv, i) => {
                const rank = i + 1;
                const ok = Number.isFinite(lv.price);
                const bar = ok
                  ? Math.min(100, (Number(lv.volume ?? 0) / maxBookVol) * 100)
                  : 0;
                return (
                  <div key={`b${rank}`} className="ths-five-row bid">
                    <span className="ths-five-side">买{rank}</span>
                    <span className="up">
                      {ok ? fmt(lv.price, 2) : "—"}
                    </span>
                    <span className="ths-five-vol">
                      <i style={{ width: `${bar}%` }} />
                      {ok ? fmtVol(lv.volume) : "—"}
                    </span>
                  </div>
                );
              })}
            </div>
            <p className="bn-demo-hint ths-five-note">
              {five.note ||
                "盘口来自 qdb；完整五档依赖 collector 写入 ashare:depth。"}
            </p>
          </div>
        </aside>
      </div>

      <footer className="bn-status">
        <span className="bn-status-dot" />
        <span>A股 · 同花顺启发布局</span>
        <span className="bn-label">·</span>
        <span className="bn-label">红涨绿跌 · Quotes only</span>
        <span className="bn-status-right">
          {selected} {name}
          {q?.price != null ? ` · ${fmt(q.price, 2)}` : ""}
        </span>
      </footer>
    </div>
  );
}

function AshareMktRow({
  row,
  quote,
  active,
  onPick,
}: {
  row: CodeRow;
  quote?: Quote;
  active: boolean;
  onPick: () => void;
}) {
  const pct = Number(quote?.change_pct ?? NaN);
  const flash = usePriceFlash(quote?.price);
  return (
    <button
      type="button"
      className={active ? "bn-mkt-row-stock active" : "bn-mkt-row-stock"}
      onClick={onPick}
    >
      <span className="bn-mkt-pair">
        {row.stock_code}
        <em>{row.short_name || quote?.short_name || "—"}</em>
      </span>
      <span className={`bn-mono ${flashClass(flash)}`}>
        {fmt(quote?.price, 2)}
      </span>
      <span className={Number.isFinite(pct) ? (pct >= 0 ? "up" : "down") : ""}>
        {Number.isFinite(pct)
          ? `${pct >= 0 ? "+" : ""}${fmt(pct, 2)}%`
          : "—"}
      </span>
    </button>
  );
}
