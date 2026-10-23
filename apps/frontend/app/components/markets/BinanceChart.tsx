"use client";

/**
 * 币安 Original 风格主图：蜡烛 + 可开关 MA/BOLL/VOL + MACD 副图；OHLC 侧方浮层。
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
} from "react";
import { createPortal } from "react-dom";
import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type UTCTimestamp,
} from "lightweight-charts";
import {
  formatLocalDateTime,
  localToUtc,
  timeToLocal,
} from "../../../lib/time";
import {
  toBoll,
  toMaLine,
  toMacd,
  type Kline,
} from "./chartIndicators";

export type { Kline };

type OhlcInfo = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change: number;
  up: boolean;
};

type HoverTip = {
  ohlc: OhlcInfo;
  clientX: number;
  clientY: number;
};

type IndFlags = {
  ma: boolean;
  boll: boolean;
  vol: boolean;
  macd: boolean;
};

const IND_DEFAULT: IndFlags = {
  ma: true,
  boll: false,
  vol: true,
  macd: false,
};

const IND_STORAGE_KEY = "el:chart-ind:v1";

function loadInd(): IndFlags {
  try {
    const raw = localStorage.getItem(IND_STORAGE_KEY);
    if (!raw) return { ...IND_DEFAULT };
    const p = JSON.parse(raw) as Partial<IndFlags>;
    return {
      ma: p.ma ?? IND_DEFAULT.ma,
      boll: p.boll ?? IND_DEFAULT.boll,
      vol: p.vol ?? IND_DEFAULT.vol,
      macd: p.macd ?? IND_DEFAULT.macd,
    };
  } catch {
    return { ...IND_DEFAULT };
  }
}

function fmt(n: number, d = 2): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1000)
    return n.toLocaleString(undefined, { maximumFractionDigits: d });
  if (Math.abs(n) >= 1) return n.toFixed(d);
  return n.toPrecision(4);
}

function barLocalSec(k: Kline): number {
  return timeToLocal(Math.floor(Number(k[0]) / 1000));
}

function toCandle(k: Kline): CandlestickData {
  return {
    time: barLocalSec(k) as UTCTimestamp,
    open: Number(k[1]),
    high: Number(k[2]),
    low: Number(k[3]),
    close: Number(k[4]),
  };
}

export type ChartPalette = "wind" | "binance";

const PALETTE = {
  wind: {
    up: "#e53935",
    down: "#1b8f5a",
    upVol: "rgba(229, 57, 53, 0.45)",
    downVol: "rgba(27, 143, 90, 0.45)",
    macdUp: "rgba(229, 57, 53, 0.7)",
    macdDown: "rgba(27, 143, 90, 0.7)",
  },
  binance: {
    up: "#0ecb81",
    down: "#f6465d",
    upVol: "rgba(14, 203, 129, 0.45)",
    downVol: "rgba(246, 70, 93, 0.45)",
    macdUp: "rgba(14, 203, 129, 0.7)",
    macdDown: "rgba(246, 70, 93, 0.7)",
  },
} as const;

function toVolume(k: Kline, palette: ChartPalette = "wind"): HistogramData {
  const up = Number(k[4]) >= Number(k[1]);
  const p = PALETTE[palette];
  return {
    time: barLocalSec(k) as UTCTimestamp,
    value: Number(k[5]),
    color: up ? p.upVol : p.downVol,
  };
}

function infoFromKline(k: Kline): OhlcInfo {
  const o = Number(k[1]);
  const c = Number(k[4]);
  return {
    time: formatLocalDateTime(Number(k[0])),
    open: o,
    high: Number(k[2]),
    low: Number(k[3]),
    close: c,
    volume: Number(k[5]),
    change: o === 0 ? 0 : ((c - o) / o) * 100,
    up: c >= o,
  };
}

function findKline(rows: Kline[], localSec: number): Kline | null {
  if (!rows.length) return null;
  const utcSec = localToUtc(localSec);
  let best: Kline | null = null;
  let bestDist = Infinity;
  for (const k of rows) {
    const t = Math.floor(Number(k[0]) / 1000);
    const d = Math.abs(t - utcSec);
    if (d < bestDist) {
      bestDist = d;
      best = k;
    }
    if (d === 0) break;
  }
  return best;
}

type Props = {
  klines: Kline[];
  symbol: string;
  seriesKey?: string;
  onNeedHistory?: () => void;
  loading?: boolean;
  palette?: ChartPalette;
};

export function BinanceChart({
  klines,
  symbol,
  seriesKey,
  onNeedHistory,
  loading = false,
  palette = "wind",
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const macdWrapRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const macdChartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma7Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma25Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma99Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const bollMidRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bollUpRef = useRef<ISeriesApi<"Line"> | null>(null);
  const bollLowRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdDifRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdDeaRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const klinesRef = useRef(klines) as MutableRefObject<Kline[]>;
  const indRef = useRef<IndFlags>(IND_DEFAULT);
  const syncingRangeRef = useRef(false);
  const prevKeyRef = useRef<string | undefined>(undefined);
  const prevFirstTsRef = useRef<number | null>(null);
  const prevLastTsRef = useRef<number | null>(null);
  const prevLenRef = useRef(0);
  const historyBusyRef = useRef(false);
  const onNeedHistoryRef = useRef(onNeedHistory);
  const paletteRef = useRef(palette);
  const [tip, setTip] = useState<HoverTip | null>(null);
  const [ind, setInd] = useState<IndFlags>(IND_DEFAULT);

  klinesRef.current = klines;
  onNeedHistoryRef.current = onNeedHistory;
  paletteRef.current = palette;
  indRef.current = ind;

  useEffect(() => {
    setInd(loadInd());
  }, []);

  const toggleInd = useCallback((key: keyof IndFlags) => {
    setInd((prev) => {
      const next = { ...prev, [key]: !prev[key] };
      try {
        localStorage.setItem(IND_STORAGE_KEY, JSON.stringify(next));
      } catch {
        /* ignore */
      }
      return next;
    });
  }, []);

  const applyOverlays = useCallback((rows: Kline[], flags: IndFlags) => {
    const pal = paletteRef.current;
    if (flags.vol && volumeRef.current) {
      volumeRef.current.setData(rows.map((k) => toVolume(k, pal)));
    } else {
      volumeRef.current?.setData([]);
    }
    if (flags.ma) {
      ma7Ref.current?.setData(toMaLine(rows, 7));
      ma25Ref.current?.setData(toMaLine(rows, 25));
      ma99Ref.current?.setData(toMaLine(rows, 99));
    } else {
      ma7Ref.current?.setData([]);
      ma25Ref.current?.setData([]);
      ma99Ref.current?.setData([]);
    }
    if (flags.boll) {
      const b = toBoll(rows);
      bollMidRef.current?.setData(b.mid);
      bollUpRef.current?.setData(b.upper);
      bollLowRef.current?.setData(b.lower);
    } else {
      bollMidRef.current?.setData([]);
      bollUpRef.current?.setData([]);
      bollLowRef.current?.setData([]);
    }
    if (flags.macd && macdDifRef.current) {
      const p = PALETTE[pal];
      const m = toMacd(rows, 12, 26, 9, p.macdUp, p.macdDown);
      macdDifRef.current.setData(m.dif);
      macdDeaRef.current?.setData(m.dea);
      macdHistRef.current?.setData(m.hist);
    } else {
      macdDifRef.current?.setData([]);
      macdDeaRef.current?.setData([]);
      macdHistRef.current?.setData([]);
    }
  }, []);

  // 主图 + MACD 副图初始化
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;

    const chart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#161a1e" },
        textColor: "#848e9c",
        fontSize: 11,
        fontFamily:
          "BinancePlex, IBM Plex Mono, Segoe UI, PingFang SC, sans-serif",
      },
      grid: {
        vertLines: { color: "#1e2329" },
        horzLines: { color: "#1e2329" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "#848e9c",
          width: 1,
          style: LineStyle.Dashed,
          labelVisible: false,
        },
        horzLine: {
          color: "#848e9c",
          width: 1,
          style: LineStyle.Dashed,
          labelVisible: false,
        },
      },
      rightPriceScale: {
        borderColor: "#2b3139",
        scaleMargins: { top: 0.08, bottom: 0.22 },
      },
      timeScale: {
        borderColor: "#2b3139",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 8,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });

    const pal = PALETTE[paletteRef.current];
    const candles = chart.addCandlestickSeries({
      upColor: pal.up,
      downColor: pal.down,
      borderVisible: false,
      wickUpColor: pal.up,
      wickDownColor: pal.down,
      lastValueVisible: false,
      priceLineVisible: false,
    });

    const volume = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volume.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });

    const lineOpts = {
      lineWidth: 1 as const,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    };
    const ma7 = chart.addLineSeries({ color: "#f0b90b", ...lineOpts });
    const ma25 = chart.addLineSeries({ color: "#d94cff", ...lineOpts });
    const ma99 = chart.addLineSeries({ color: "#1e88e5", ...lineOpts });
    const bollMid = chart.addLineSeries({ color: "#f0b90b", ...lineOpts });
    const bollUp = chart.addLineSeries({
      color: "#848e9c",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      lineStyle: LineStyle.Dashed,
    });
    const bollLow = chart.addLineSeries({
      color: "#848e9c",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      lineStyle: LineStyle.Dashed,
    });

    const stage = stageRef.current;
    const onMouseMove = (ev: MouseEvent) => {
      if (!stage) return;
      const rows = klinesRef.current;
      if (!rows.length) {
        setTip(null);
        return;
      }
      const rect = stage.getBoundingClientRect();
      const x = ev.clientX - rect.left;
      const y = ev.clientY - rect.top;
      if (x < 0 || y < 0 || x > rect.width || y > rect.height) {
        setTip(null);
        return;
      }
      const t = chart.timeScale().coordinateToTime(x);
      if (t == null) {
        setTip(null);
        return;
      }
      const hit = findKline(rows, t as number);
      if (!hit) {
        setTip(null);
        return;
      }
      setTip({
        ohlc: infoFromKline(hit),
        clientX: ev.clientX,
        clientY: ev.clientY,
      });
    };
    const onMouseLeave = () => setTip(null);
    stage?.addEventListener("mousemove", onMouseMove);
    stage?.addEventListener("mouseleave", onMouseLeave);

    chartRef.current = chart;
    candleRef.current = candles;
    volumeRef.current = volume;
    ma7Ref.current = ma7;
    ma25Ref.current = ma25;
    ma99Ref.current = ma99;
    bollMidRef.current = bollMid;
    bollUpRef.current = bollUp;
    bollLowRef.current = bollLow;

    const onRange = () => {
      const range = chart.timeScale().getVisibleLogicalRange();
      if (!range || historyBusyRef.current) return;
      if (!syncingRangeRef.current && macdChartRef.current) {
        syncingRangeRef.current = true;
        try {
          macdChartRef.current.timeScale().setVisibleLogicalRange(range);
        } finally {
          syncingRangeRef.current = false;
        }
      }
      if (range.from > 8) return;
      if (klinesRef.current.length < 40) return;
      const cb = onNeedHistoryRef.current;
      if (!cb) return;
      historyBusyRef.current = true;
      cb();
      window.setTimeout(() => {
        historyBusyRef.current = false;
      }, 1200);
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);

    return () => {
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      stage?.removeEventListener("mousemove", onMouseMove);
      stage?.removeEventListener("mouseleave", onMouseLeave);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      ma7Ref.current = null;
      ma25Ref.current = null;
      ma99Ref.current = null;
      bollMidRef.current = null;
      bollUpRef.current = null;
      bollLowRef.current = null;
    };
  }, []);

  // MACD 副图（随 ind.macd 挂载）
  useEffect(() => {
    if (!ind.macd) {
      macdChartRef.current?.remove();
      macdChartRef.current = null;
      macdDifRef.current = null;
      macdDeaRef.current = null;
      macdHistRef.current = null;
      return;
    }
    const el = macdWrapRef.current;
    if (!el || macdChartRef.current) return;

    const macdChart = createChart(el, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#161a1e" },
        textColor: "#848e9c",
        fontSize: 10,
        fontFamily:
          "BinancePlex, IBM Plex Mono, Segoe UI, PingFang SC, sans-serif",
      },
      grid: {
        vertLines: { color: "#1e2329" },
        horzLines: { color: "#1e2329" },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: "#848e9c",
          width: 1,
          style: LineStyle.Dashed,
          labelVisible: false,
        },
        horzLine: {
          color: "#848e9c",
          width: 1,
          style: LineStyle.Dashed,
          labelVisible: false,
        },
      },
      rightPriceScale: {
        borderColor: "#2b3139",
        scaleMargins: { top: 0.12, bottom: 0.08 },
      },
      timeScale: {
        borderColor: "#2b3139",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 8,
        visible: false,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
    });

    const hist = macdChart.addHistogramSeries({
      priceFormat: { type: "price", precision: 4, minMove: 0.0001 },
      priceScaleId: "",
    });
    hist.priceScale().applyOptions({
      scaleMargins: { top: 0.2, bottom: 0 },
    });
    const dif = macdChart.addLineSeries({
      color: "#f0b90b",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const dea = macdChart.addLineSeries({
      color: "#1e88e5",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });

    macdChartRef.current = macdChart;
    macdHistRef.current = hist;
    macdDifRef.current = dif;
    macdDeaRef.current = dea;

    const onMacdRange = () => {
      if (syncingRangeRef.current || !chartRef.current) return;
      const range = macdChart.timeScale().getVisibleLogicalRange();
      if (!range) return;
      syncingRangeRef.current = true;
      try {
        chartRef.current.timeScale().setVisibleLogicalRange(range);
      } finally {
        syncingRangeRef.current = false;
      }
    };
    macdChart.timeScale().subscribeVisibleLogicalRangeChange(onMacdRange);

    const rows = klinesRef.current;
    if (rows.length) applyOverlays(rows, indRef.current);
    const mainRange = chartRef.current?.timeScale().getVisibleLogicalRange();
    if (mainRange) {
      macdChart.timeScale().setVisibleLogicalRange(mainRange);
    }

    return () => {
      macdChart.timeScale().unsubscribeVisibleLogicalRangeChange(onMacdRange);
      macdChart.remove();
      macdChartRef.current = null;
      macdDifRef.current = null;
      macdDeaRef.current = null;
      macdHistRef.current = null;
    };
  }, [ind.macd, applyOverlays]);

  // K 线增量 / 全量
  useEffect(() => {
    if (!candleRef.current || !volumeRef.current) return;
    if (!klines.length) {
      candleRef.current.setData([]);
      applyOverlays([], indRef.current);
      prevFirstTsRef.current = null;
      prevLastTsRef.current = null;
      prevLenRef.current = 0;
      setTip(null);
      return;
    }
    const key = seriesKey ?? symbol;
    const keyChanged = prevKeyRef.current !== key;
    const firstTs = Number(klines[0][0]);
    const lastTs = Number(klines[klines.length - 1][0]);
    const prevFirst = prevFirstTsRef.current;
    const prevLast = prevLastTsRef.current;
    const prevLen = prevLenRef.current;
    const prepended =
      !keyChanged &&
      prevFirst != null &&
      firstTs < prevFirst &&
      klines.length > 0;
    const canTailUpdate =
      !keyChanged &&
      !prepended &&
      prevFirst != null &&
      prevLast != null &&
      prevFirst === firstTs &&
      prevLen > 0 &&
      klines.length >= prevLen &&
      klines.length - prevLen <= 2 &&
      lastTs >= prevLast;

    const range = prepended
      ? chartRef.current?.timeScale().getVisibleLogicalRange()
      : null;
    const added =
      prepended && prevFirst != null
        ? klines.findIndex((k) => Number(k[0]) === prevFirst)
        : 0;

    const pal = paletteRef.current;
    const applyFull = () => {
      candleRef.current!.setData(klines.map(toCandle));
      applyOverlays(klines, indRef.current);
    };

    let usedTail = false;
    if (canTailUpdate) {
      const from = prevLen - 1;
      let cursorTs = prevLast;
      let ok = true;
      for (let i = from; i < klines.length; i++) {
        const ts = Number(klines[i][0]);
        if (i === from) {
          if (ts !== prevLast) {
            ok = false;
            break;
          }
        } else if (!(ts > cursorTs)) {
          ok = false;
          break;
        }
        cursorTs = ts;
      }
      if (ok) {
        try {
          for (let i = from; i < klines.length; i++) {
            candleRef.current.update(toCandle(klines[i]));
            if (indRef.current.vol) {
              volumeRef.current.update(toVolume(klines[i], pal));
            }
          }
          applyOverlays(klines, indRef.current);
          usedTail = true;
        } catch {
          usedTail = false;
        }
      }
    }
    if (!usedTail) applyFull();

    if (keyChanged) {
      chartRef.current?.timeScale().scrollToRealTime();
      macdChartRef.current?.timeScale().scrollToRealTime();
      prevKeyRef.current = key;
    } else if (prepended && range && added > 0) {
      const next = { from: range.from + added, to: range.to + added };
      chartRef.current?.timeScale().setVisibleLogicalRange(next);
      macdChartRef.current?.timeScale().setVisibleLogicalRange(next);
    }
    prevFirstTsRef.current = firstTs;
    prevLastTsRef.current = lastTs;
    prevLenRef.current = klines.length;
    setTip(null);
  }, [klines, seriesKey, symbol, applyOverlays]);

  // 开关变化时重刷 overlay（不必重建蜡烛）
  useEffect(() => {
    if (!candleRef.current) return;
    applyOverlays(klinesRef.current, ind);
    chartRef.current?.priceScale("right").applyOptions({
      scaleMargins: { top: 0.08, bottom: ind.vol ? 0.22 : 0.06 },
    });
  }, [ind, applyOverlays]);

  useEffect(() => {
    if (!tip) return;
    const tipEl = tipRef.current;
    if (!tipEl) return;
    const tw = tipEl.offsetWidth || 160;
    const th = tipEl.offsetHeight || 150;
    const gap = 18;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = tip.clientX + gap;
    if (left + tw > vw - 8) left = tip.clientX - gap - tw;
    if (left < 8) left = 8;
    let top = tip.clientY - th / 2;
    if (top < 8) top = 8;
    if (top + th > vh - 8) top = Math.max(8, vh - th - 8);
    tipEl.style.left = `${left}px`;
    tipEl.style.top = `${top}px`;
  }, [tip]);

  const pair = symbol.endsWith("USDT")
    ? `${symbol.slice(0, -4)}/USDT`
    : symbol;

  const tipNode =
    tip && typeof document !== "undefined"
      ? createPortal(
          <div ref={tipRef} className="bn-chart-tip" aria-hidden>
            <div className="bn-chart-tip-time">{tip.ohlc.time}</div>
            <div>
              O{" "}
              <b className={tip.ohlc.up ? "up" : "down"}>
                {fmt(tip.ohlc.open)}
              </b>
            </div>
            <div>
              H{" "}
              <b className={tip.ohlc.up ? "up" : "down"}>
                {fmt(tip.ohlc.high)}
              </b>
            </div>
            <div>
              L{" "}
              <b className={tip.ohlc.up ? "up" : "down"}>
                {fmt(tip.ohlc.low)}
              </b>
            </div>
            <div>
              C{" "}
              <b className={tip.ohlc.up ? "up" : "down"}>
                {fmt(tip.ohlc.close)}
              </b>
            </div>
            <div className={tip.ohlc.up ? "up" : "down"}>
              {tip.ohlc.up ? "+" : ""}
              {fmt(tip.ohlc.change, 2)}%
            </div>
            <div>
              Vol <b>{fmt(tip.ohlc.volume, 3)}</b>
            </div>
          </div>,
          document.body,
        )
      : null;

  return (
    <div className={`bn-chart-root${ind.macd ? " has-macd" : ""}`}>
      <div className="bn-ohlc-bar">
        <span className="bn-ohlc-pair">{pair}</span>
        <div className="bn-ind-bar" role="toolbar" aria-label="技术指标">
          <span className="bn-ind-group-label">主图</span>
          <button
            type="button"
            className={ind.ma ? "bn-ind-chip on" : "bn-ind-chip"}
            onClick={() => toggleInd("ma")}
          >
            MA
          </button>
          <button
            type="button"
            className={ind.boll ? "bn-ind-chip on" : "bn-ind-chip"}
            onClick={() => toggleInd("boll")}
          >
            BOLL
          </button>
          <span className="bn-ind-group-label">副图</span>
          <button
            type="button"
            className={ind.vol ? "bn-ind-chip on" : "bn-ind-chip"}
            onClick={() => toggleInd("vol")}
          >
            VOL
          </button>
          <button
            type="button"
            className={ind.macd ? "bn-ind-chip on" : "bn-ind-chip"}
            onClick={() => toggleInd("macd")}
          >
            MACD
          </button>
        </div>
        {ind.ma ? (
          <span className="bn-ma-legend">
            <i style={{ color: "#f0b90b" }}>MA(7)</i>
            <i style={{ color: "#d94cff" }}>MA(25)</i>
            <i style={{ color: "#1e88e5" }}>MA(99)</i>
          </span>
        ) : null}
        {ind.boll ? (
          <span className="bn-ma-legend">
            <i style={{ color: "#f0b90b" }}>BOLL(20)</i>
          </span>
        ) : null}
        {!klines.length ? (
          <span className="mk-muted">
            {loading ? "Loading chart…" : "No chart data"}
          </span>
        ) : null}
      </div>
      <div ref={stageRef} className="bn-chart-stage">
        <div ref={wrapRef} className="bn-chart-canvas" />
      </div>
      {ind.macd ? (
        <div className="bn-macd-pane">
          <div className="bn-macd-label">
            <span>MACD(12,26,9)</span>
            <i style={{ color: "#f0b90b" }}>DIF</i>
            <i style={{ color: "#1e88e5" }}>DEA</i>
          </div>
          <div ref={macdWrapRef} className="bn-macd-canvas" />
        </div>
      ) : null}
      {tipNode}
    </div>
  );
}
