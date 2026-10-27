"use client";

/**
 * A 股行情台（同花顺启发布局）：左列表 | 中图 | 右五档/资金/财务/热榜。
 * 只读 qdb / Postgres 冷库；BFF `/api/cn-equity/*` → Gateway `/api/research/cn-equity/*`。
 */

import {
  startTransition,
  useCallback,
  useEffect,
  useMemo,
  useRef,
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
import {
  CN_ASSET_CLASSES,
  CN_EQUITY_BOARDS,
  type CnAssetClass,
  type CnEquityBoardId,
  matchesCnEquityBoard,
  uiToQdbExchange,
} from "../../components/markets/cnEquityBoards";
import {
  CnIndexStrip,
  type IndexStripItem,
} from "../../components/markets/CnIndexStrip";
import { VirtualMktList } from "../../components/markets/VirtualMktList";
import { useQdbSnapshot } from "../../components/markets/useQdbSnapshot";

/** 与 research/collector 一致：北交所 4/8/92 → BSE；须先于「9→SSE」。 */
function cnEquityQdbSymbol(code: string, exchange?: string): string {
  const c = code.replace(/\D/g, "").slice(-6).padStart(6, "0");
  if (exchange) return `${uiToQdbExchange(exchange)}:${c}`;
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
 * 全市场代码来自 qdb `cn-equity:codes`（数千）；列表报价 round-robin 有滞后。
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

/** research `/cn-equity/quotes` 单次最多约 80；分块拉可视窗口。 */
const QUOTE_CHUNK = 60;
/** 报价窗口在可视区外再多拉若干行，滚动时少闪「—」。 */
const QUOTE_BUFFER = 24;

/** 主 Tab：分时 | 日K | 其他周期 */
type ChartTab = "intraday" | "1d" | "other";

/** 右侧：五档 | 资金 | 财务 | 热榜 */
type SideTab = "book" | "fund" | "finance" | "hot";

type FundFlowRow = {
  trading_day?: string;
  main_net?: number | null;
  super_large_net?: number | null;
  large_net?: number | null;
  medium_net?: number | null;
  small_net?: number | null;
};

type FinanceRow = {
  report_date?: string;
  indicator_code?: string;
  indicator_name?: string;
  value?: number | null;
};

type Fundamentals = {
  capital_flow?: FundFlowRow[];
  finance?: FinanceRow[];
  share_capital?: {
    change_date?: string;
    total_shares?: number | null;
    float_shares_a?: number | null;
    change_reason?: string;
  } | null;
  industries?: { industry_code?: string; name?: string; level?: number }[];
  lifting?: {
    lift_date?: string;
    shares?: number | null;
    ratio?: number | null;
    holder_type?: string;
  }[];
  source?: string;
};

type HotRow = {
  rank_no?: number;
  stock_code?: string;
  stock_name?: string;
  name?: string;
  score?: number | null;
  plate_code?: string;
};

type SentimentSummary = {
  margin?: {
    trading_day?: string;
    financing_balance?: number | null;
    margin_balance?: number | null;
  }[];
  hot_stock?: HotRow[];
  hot_concept?: HotRow[];
  note?: string;
};

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
  category?: string;
  qdb_exchange?: string;
};

const INDEX_PRIORITY = [
  "000001",
  "399001",
  "399006",
  "000300",
  "000016",
  "000852",
] as const;

const ETF_PRIORITY = ["510300", "159915", "512880", "159919"] as const;

function defaultSelected(asset: CnAssetClass): string {
  if (asset === "index") return "000001";
  if (asset === "etf") return "510300";
  if (asset === "convertible") return "";
  return "600519";
}

function quoteToken(row: Pick<CodeRow, "stock_code" | "exchange" | "category" | "qdb_exchange">): string {
  const cat = row.category || "stock";
  if (cat !== "stock") {
    const ex = row.qdb_exchange || uiToQdbExchange(row.exchange);
    return `${ex}:${row.stock_code}`;
  }
  return row.stock_code;
}

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

/** 资金流金额：按「亿」展示（上游多为元） */
function fmtYi(n: string | number | null | undefined): string {
  if (n == null || n === "") return "—";
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "—";
  const yi = v / 1e8;
  if (Math.abs(yi) >= 100) return `${yi.toFixed(0)}亿`;
  if (Math.abs(yi) >= 1) return `${yi.toFixed(2)}亿`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(1)}万`;
  return v.toFixed(0);
}

function fmtYiShares(n: string | number | null | undefined): string {
  if (n == null || n === "") return "—";
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)}亿股`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(0)}万股`;
  return `${v.toFixed(0)}股`;
}

function fmtNum(n: string | number | null | undefined): string {
  if (n == null || n === "") return "—";
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  if (Math.abs(v) >= 100) return v.toFixed(2);
  return v.toPrecision(4);
}

function netCls(n: string | number | null | undefined): string | undefined {
  if (n == null || n === "") return undefined;
  const v = typeof n === "string" ? Number(n) : n;
  if (!Number.isFinite(v) || v === 0) return undefined;
  return v > 0 ? "up" : "down";
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

export default function CnEquityPage() {
  const [query, setQuery] = useState("");
  const [asset, setAsset] = useState<CnAssetClass>("stock");
  const [board, setBoard] = useState<CnEquityBoardId>("all");
  const [codes, setCodes] = useState<CodeRow[]>([]);
  const [quotes, setQuotes] = useState<Record<string, Quote>>({});
  const [selected, setSelected] = useState("600519");
  const [selectedEx, setSelectedEx] = useState("SH");
  const [chartTab, setChartTab] = useState<ChartTab>("intraday");
  const [otherK, setOtherK] = useState<string>("60m");
  const [klines, setKlines] = useState<Kline[]>([]);
  const [five, setFive] = useState<FiveBook>({
    bids: [],
    asks: [],
    levels: 0,
    note: "",
  });
  const [sideTab, setSideTab] = useState<SideTab>("book");
  const [fundamentals, setFundamentals] = useState<Fundamentals | null>(null);
  const [sentiment, setSentiment] = useState<SentimentSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [loadingCodes, setLoadingCodes] = useState(true);
  const [catalogNote, setCatalogNote] = useState<string | null>(null);
  const [visibleRange, setVisibleRange] = useState({ start: 0, end: 40 });
  const [kMeta, setKMeta] = useState<{
    session?: string;
    historyCount?: number;
    hasRealtime?: boolean;
    view?: string;
  }>({});

  const activeKType = chartTab === "1d" ? "1d" : chartTab === "intraday" ? "intraday" : otherK;

  // 滚动会高频回调；合并到 rAF，减少 quotes 分块打爆网关（cn-equity 虽已豁免限流，仍降抖）
  const rangeRaf = useRef<number | null>(null);
  const onVisibleRange = useCallback((start: number, end: number) => {
    if (rangeRaf.current != null) cancelAnimationFrame(rangeRaf.current);
    rangeRaf.current = requestAnimationFrame(() => {
      rangeRaf.current = null;
      setVisibleRange((prev) =>
        prev.start === start && prev.end === end ? prev : { start, end },
      );
    });
  }, []);

  // 搜索/板块/资产类变更后列表 remount，窗口先回到顶部
  useEffect(() => {
    setVisibleRange({ start: 0, end: 40 });
  }, [query, board, asset]);

  const loadCodes = useCallback(async (assetClass: CnAssetClass) => {
    setLoadingCodes(true);
    const seed =
      assetClass === "index"
        ? INDEX_PRIORITY
        : assetClass === "etf"
          ? ETF_PRIORITY
          : PRIORITY;
    setCodes(
      seed.map((stock_code) => ({
        stock_code,
        short_name: "",
        exchange:
          stock_code.startsWith("6") ||
          stock_code.startsWith("5") ||
          (assetClass === "index" && stock_code.startsWith("000"))
            ? "SH"
            : "SZ",
        symbol: `${stock_code}.CN`,
        category: assetClass,
      })),
    );
    try {
      const res = await fetch(
        `/api/cn-equity/codes?limit=10000&category=${encodeURIComponent(assetClass)}`,
      );
      if (!res.ok) throw new Error(`codes ${res.status}`);
      const body = (await res.json()) as {
        data?: CodeRow[];
        count?: number;
        meta?: { note?: string; universe?: string; catalog_count?: number };
        category?: string;
      };
      if (body.data?.length) setCodes(body.data);
      const n = body.meta?.catalog_count ?? body.count ?? body.data?.length;
      if (assetClass !== "stock") {
        setCatalogNote(
          body.meta?.note ||
            `${assetClass} ${n ?? "—"} 只 · 目录 Postgres · 报价 qdb/日线`,
        );
      } else if (body.meta?.universe === "full" || (typeof n === "number" && n > 100)) {
        setCatalogNote(
          `全市场 ${n ?? "—"} 只；列表可滚动；报价按可视窗口分批（有滞后）；K 线完整回填仅热门 seed`,
        );
      } else if (body.meta?.note) {
        setCatalogNote(body.meta.note);
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

  const loadQuotes = useCallback(
    async (tokens: string[], assetClass: CnAssetClass) => {
      const unique = [...new Set(tokens.filter(Boolean))];
      if (!unique.length) return;
      const catQ =
        assetClass !== "stock"
          ? `&category=${encodeURIComponent(assetClass)}`
          : "";
      for (let i = 0; i < unique.length; i += QUOTE_CHUNK) {
        const chunk = unique.slice(i, i + QUOTE_CHUNK);
        const res = await fetch(
          `/api/cn-equity/quotes?codes=${encodeURIComponent(chunk.join(","))}${catQ}`,
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
    },
    [],
  );

  const loadKlines = useCallback(
    async (code: string, kt: string, exchange: string, assetClass: CnAssetClass) => {
      if (kt === "intraday") {
        const qs = new URLSearchParams({
          exchange: uiToQdbExchange(exchange),
          category: assetClass,
        });
        const res = await fetch(`/api/cn-equity/intraday/${code}?${qs}`);
        if (res.status === 429) return;
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
          note?: string;
          source?: string;
        };
        setKlines(mapCandles(body.data ?? []));
        setKMeta({
          session: undefined,
          historyCount: body.data?.length,
          hasRealtime: false,
          view: body.note?.includes("占位")
            ? "intraday-fallback"
            : "intraday-5m",
        });
        return;
      }
      const ex = uiToQdbExchange(exchange);
      const qs = new URLSearchParams({
        k_type: kt,
        limit: "300",
        adjust_type: "1",
        view: "merged",
        exchange: ex,
        category: assetClass,
      });
      const res = await fetch(`/api/cn-equity/klines/${code}?${qs}`);
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
    },
    [],
  );

  const loadFive = useCallback(
    async (code: string, exchange: string, assetClass: CnAssetClass) => {
      try {
        const qs = new URLSearchParams({
          exchange: uiToQdbExchange(exchange),
          category: assetClass,
        });
        const res = await fetch(`/api/cn-equity/five/${code}?${qs}`);
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
    },
    [],
  );

  const loadFundamentals = useCallback(async (code: string) => {
    try {
      const res = await fetch(
        `/api/cn-equity/fundamentals/${encodeURIComponent(code)}?flow_limit=10&finance_reports=4`,
      );
      if (!res.ok) {
        setFundamentals(null);
        return;
      }
      setFundamentals((await res.json()) as Fundamentals);
    } catch {
      setFundamentals(null);
    }
  }, []);

  const loadSentiment = useCallback(async () => {
    try {
      const res = await fetch("/api/cn-equity/sentiment/summary?hot_limit=20");
      if (!res.ok) {
        setSentiment(null);
        return;
      }
      setSentiment((await res.json()) as SentimentSummary);
    } catch {
      setSentiment(null);
    }
  }, []);

  useEffect(() => {
    void loadCodes(asset);
  }, [asset, loadCodes]);

  useEffect(() => {
    void loadSentiment();
    const id = setInterval(() => void loadSentiment(), 120_000);
    return () => clearInterval(id);
  }, [loadSentiment]);

  useEffect(() => {
    if (!selected || asset !== "stock") {
      setFundamentals(null);
      return;
    }
    void loadFundamentals(selected);
  }, [selected, asset, loadFundamentals]);

  // 切换资产类时重置选中与默认图周期（指数/ETF 默认日K）
  useEffect(() => {
    const next = defaultSelected(asset);
    if (next) {
      setSelected(next);
      const sh =
        next.startsWith("6") ||
        next.startsWith("5") ||
        (asset === "index" && next.startsWith("000"));
      setSelectedEx(sh ? "SH" : "SZ");
    }
    // 指数/ETF 也默认分时（有 5m 则盘中；否则日线占位）
    setChartTab("intraday");
    setBoard("all");
    setQuery("");
  }, [asset]);

  const filtered = useMemo(() => {
    const q = query.trim().toUpperCase();
    const pri =
      asset === "index"
        ? INDEX_PRIORITY
        : asset === "etf"
          ? ETF_PRIORITY
          : PRIORITY;
    const priorityIdx = new Map<string, number>(
      [...pri].map((c, i) => [c, i]),
    );
    let list =
      asset === "stock"
        ? codes.filter((c) =>
            matchesCnEquityBoard(c.stock_code, c.exchange, board),
          )
        : [...codes];
    if (q) {
      list = list.filter(
        (c) =>
          c.stock_code.includes(q) ||
          c.short_name.toUpperCase().includes(q) ||
          c.symbol.includes(q),
      );
    }
    list.sort((a, b) => {
      const pa = priorityIdx.get(a.stock_code) ?? 999;
      const pb = priorityIdx.get(b.stock_code) ?? 999;
      if (pa !== pb) return pa - pb;
      return a.stock_code.localeCompare(b.stock_code);
    });
    return list;
  }, [codes, query, board, asset]);

  // 目录到齐后：可转债等无默认码时选第一只；并同步交易所
  useEffect(() => {
    if (!filtered.length) return;
    const hit = filtered.find((c) => c.stock_code === selected);
    if (hit) {
      setSelectedEx(hit.exchange);
      return;
    }
    const first = filtered[0];
    setSelected(first.stock_code);
    setSelectedEx(first.exchange);
  }, [filtered, selected]);

  const displayList = filtered;
  const listIds = useMemo(
    () => displayList.map((c) => c.stock_code),
    [displayList],
  );
  useListKeyboard(listIds, selected, setSelected, Boolean(listIds.length));

  const quoteCodes = useMemo(() => {
    if (!displayList.length) {
      return selected
        ? [quoteToken({ stock_code: selected, exchange: selectedEx, category: asset })]
        : [];
    }
    const from = Math.max(0, visibleRange.start - QUOTE_BUFFER);
    const to = Math.min(
      displayList.length,
      Math.max(visibleRange.end, visibleRange.start + 1) + QUOTE_BUFFER,
    );
    const want = displayList.slice(from, to).map((c) => quoteToken(c));
    const selTok = quoteToken({
      stock_code: selected,
      exchange: selectedEx,
      category: asset,
    });
    if (selected && !want.includes(selTok)) want.push(selTok);
    return want;
  }, [displayList, visibleRange, selected, selectedEx, asset]);

  useEffect(() => {
    if (!quoteCodes.length) return;
    void loadQuotes(quoteCodes, asset);
    const id = setInterval(() => setTick((n) => n + 1), 30_000);
    return () => clearInterval(id);
  }, [quoteCodes, loadQuotes, asset]);

  useEffect(() => {
    if (tick === 0) return;
    void loadQuotes(quoteCodes, asset);
  }, [tick, quoteCodes, loadQuotes, asset]);

  useQdbSnapshot(
    selected ? cnEquityQdbSymbol(selected, selectedEx) : null,
    (row) => {
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
    },
  );

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    void (async () => {
      try {
        await Promise.all([
          loadKlines(selected, activeKType, selectedEx, asset),
          loadFive(selected, selectedEx, asset),
        ]);
        if (!cancelled) setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    const id = setInterval(() => {
      void loadKlines(selected, activeKType, selectedEx, asset).catch(
        () => undefined,
      );
      void loadFive(selected, selectedEx, asset);
    }, 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [selected, selectedEx, asset, activeKType, loadKlines, loadFive]);

  const pickRow = useCallback((row: CodeRow) => {
    startTransition(() => {
      setSelected(row.stock_code);
      setSelectedEx(row.exchange);
    });
  }, []);

  const onIndexStripPick = useCallback((item: IndexStripItem) => {
    startTransition(() => {
      setAsset("index");
      setSelected(item.stock_code);
      setSelectedEx(item.exchange);
      setChartTab("1d");
    });
  }, []);

  const q = quotes[selected];
  const meta = codes.find(
    (c) => c.stock_code === selected && c.exchange === selectedEx,
  ) ?? codes.find((c) => c.stock_code === selected);
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
      <CnIndexStrip selectedCode={selected} onPick={onIndexStripPick} />
      <header className="bn-top ths-top">
        <div className="bn-top-pair">
          <div className="bn-top-name">
            <span className="ths-code">{selected || "—"}</span>
            <span className="ths-name">{name}</span>
            <span className="bn-pill">
              {asset === "stock"
                ? "A股"
                : asset === "index"
                  ? "指数"
                  : asset === "etf"
                    ? "ETF"
                    : "转债"}
            </span>
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
          {meta?.exchange ?? selectedEx} ·{" "}
          {asset === "stock" ? "只读 qdb" : "Postgres/qdb"}
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
                : `${displayList.length}${
                    board !== "all" || query.trim()
                      ? ` / ${codes.length}`
                      : ""
                  } 只`}
            </span>
          </div>
          <div className="ths-asset-tabs" role="tablist" aria-label="资产类别">
            {CN_ASSET_CLASSES.map((a) => (
              <button
                key={a.id}
                type="button"
                role="tab"
                aria-selected={asset === a.id}
                className={
                  asset === a.id ? "ths-asset-tab active" : "ths-asset-tab"
                }
                onClick={() => setAsset(a.id)}
              >
                {a.label}
              </button>
            ))}
          </div>
          {asset === "stock" ? (
            <div className="ths-board-tabs" role="tablist" aria-label="A股板块">
              {CN_EQUITY_BOARDS.map((b) => (
                <button
                  key={b.id}
                  type="button"
                  role="tab"
                  aria-selected={board === b.id}
                  className={
                    board === b.id ? "ths-board-tab active" : "ths-board-tab"
                  }
                  onClick={() => setBoard(b.id)}
                >
                  {b.label}
                </button>
              ))}
            </div>
          ) : null}
          <input
            className="bn-search"
            placeholder="搜索代码 / 名称"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            aria-label="搜索标的"
          />
          <div className="bn-mkt-head bn-mkt-head-stock">
            <span>代码</span>
            <span>现价</span>
            <span>涨跌%</span>
          </div>
          <VirtualMktList
            key={`${asset}:${board}:${query.trim() || "all"}`}
            className="bn-mkt-body"
            items={displayList}
            rowHeight={40}
            height="fill"
            keyOf={(c) => `${c.exchange}:${c.stock_code}`}
            onVisibleRange={onVisibleRange}
            empty={<p className="bn-empty">无匹配标的</p>}
            renderRow={(c) => (
              <CnEquityMktRow
                row={c}
                quote={quotes[c.stock_code]}
                active={
                  c.stock_code === selected && c.exchange === selectedEx
                }
                onPick={() => pickRow(c)}
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
            symbol={`${selected}.${selectedEx}`}
            seriesKey={`${selectedEx}:${selected}:${activeKType}:${asset}`}
            palette="wind"
          />
        </section>

        <aside className="bn-right bn-right-quotes ths-book">
          <div className="bn-card bn-book bn-book-tall">
            <div className="bn-card-head ths-side-tabs">
              {(
                [
                  ["book", "五档"],
                  ["fund", "资金"],
                  ["finance", "财务"],
                  ["hot", "热榜"],
                ] as const
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  className={sideTab === id ? "active" : undefined}
                  onClick={() => setSideTab(id)}
                >
                  {label}
                </button>
              ))}
            </div>

            {sideTab === "book" ? (
              <>
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
                    "盘口来自 qdb；完整五档依赖 collector 写入 cn-equity:depth。"}
                </p>
              </>
            ) : null}

            {sideTab === "fund" ? (
              <div className="ths-side-panel">
                {asset !== "stock" ? (
                  <p className="bn-demo-hint">资金流仅个股冷库</p>
                ) : !(fundamentals?.capital_flow?.length) ? (
                  <p className="bn-demo-hint">暂无资金流（等 adata-ingest）</p>
                ) : (
                  <table className="ths-side-table">
                    <thead>
                      <tr>
                        <th>日</th>
                        <th>主力</th>
                        <th>超大</th>
                        <th>大单</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fundamentals.capital_flow.slice(0, 8).map((r) => (
                        <tr key={String(r.trading_day)}>
                          <td>{String(r.trading_day ?? "").slice(5)}</td>
                          <td className={netCls(r.main_net)}>
                            {fmtYi(r.main_net)}
                          </td>
                          <td className={netCls(r.super_large_net)}>
                            {fmtYi(r.super_large_net)}
                          </td>
                          <td className={netCls(r.large_net)}>
                            {fmtYi(r.large_net)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {fundamentals?.industries?.length ? (
                  <p className="bn-demo-hint ths-five-note">
                    行业{" "}
                    {fundamentals.industries
                      .map((x) => x.name)
                      .filter(Boolean)
                      .join(" / ")}
                  </p>
                ) : null}
              </div>
            ) : null}

            {sideTab === "finance" ? (
              <div className="ths-side-panel">
                {asset !== "stock" ? (
                  <p className="bn-demo-hint">财务仅个股冷库</p>
                ) : (
                  <>
                    {fundamentals?.share_capital ? (
                      <p className="bn-demo-hint">
                        总股本{" "}
                        {fmtYiShares(fundamentals.share_capital.total_shares)} ·
                        流通A{" "}
                        {fmtYiShares(fundamentals.share_capital.float_shares_a)}
                      </p>
                    ) : null}
                    {!(fundamentals?.finance?.length) ? (
                      <p className="bn-demo-hint">暂无财务核心指标</p>
                    ) : (
                      <table className="ths-side-table">
                        <thead>
                          <tr>
                            <th>报告期</th>
                            <th>指标</th>
                            <th>值</th>
                          </tr>
                        </thead>
                        <tbody>
                          {fundamentals.finance.slice(0, 12).map((r, i) => (
                            <tr
                              key={`${r.report_date}-${r.indicator_code}-${i}`}
                            >
                              <td>{String(r.report_date ?? "").slice(0, 10)}</td>
                              <td>
                                {r.indicator_name || r.indicator_code || "—"}
                              </td>
                              <td>{fmtNum(r.value)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                    {fundamentals?.lifting?.length ? (
                      <p className="bn-demo-hint ths-five-note">
                        近解禁{" "}
                        {String(fundamentals.lifting[0]?.lift_date ?? "").slice(
                          0,
                          10,
                        )}{" "}
                        · {fmtYiShares(fundamentals.lifting[0]?.shares)}
                      </p>
                    ) : null}
                  </>
                )}
              </div>
            ) : null}

            {sideTab === "hot" ? (
              <div className="ths-side-panel">
                {sentiment?.margin?.[0] ? (
                  <p className="bn-demo-hint">
                    两融 {String(sentiment.margin[0].trading_day ?? "").slice(5)}{" "}
                    融资余额{" "}
                    {fmtYi(sentiment.margin[0].financing_balance)}
                  </p>
                ) : null}
                {!(sentiment?.hot_stock?.length) ? (
                  <p className="bn-demo-hint">
                    {sentiment?.note || "暂无热榜快照"}
                  </p>
                ) : (
                  <table className="ths-side-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>代码</th>
                        <th>名称</th>
                        <th>热度</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sentiment.hot_stock.slice(0, 15).map((r) => (
                        <tr key={`${r.rank_no}-${r.stock_code}`}>
                          <td>{r.rank_no ?? "—"}</td>
                          <td>{r.stock_code ?? "—"}</td>
                          <td>{r.stock_name || r.name || "—"}</td>
                          <td>{fmtNum(r.score)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                {sentiment?.note ? (
                  <p className="bn-demo-hint ths-five-note">{sentiment.note}</p>
                ) : null}
              </div>
            ) : null}
          </div>
        </aside>
      </div>

      <footer className="bn-status">
        <span className="bn-status-dot" />
        <span>A股 · 同花顺布局</span>
        <span className="bn-label">·</span>
        <span className="bn-label">红涨绿跌 · 指数/ETF/转债已接冷库</span>
        <span className="bn-status-right">
          {selected} {name}
          {q?.price != null ? ` · ${fmt(q.price, 2)}` : ""}
        </span>
      </footer>
    </div>
  );
}

function CnEquityMktRow({
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
