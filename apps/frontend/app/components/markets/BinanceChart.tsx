"use client";

/**
 * 币安风格主图：蜡烛 + 成交量 + MA(7/25/99)；OHLC 悬停在鼠标侧方浮层显示。
 */

import {
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
  type LineData,
  type UTCTimestamp,
} from "lightweight-charts";
import {
  formatLocalDateTime,
  localToUtc,
  timeToLocal,
} from "../../../lib/time";

export type Kline = [number, string, string, string, string, string, ...unknown[]];

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
  /** 视口坐标，fixed 浮层贴鼠标侧方 */
  clientX: number;
  clientY: number;
};

function fmt(n: number, d = 2): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: d });
  if (Math.abs(n) >= 1) return n.toFixed(d);
  return n.toPrecision(4);
}

/** K 线 openTime 为 UTC ms → 图表本地时区秒 */
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

/** Wind：红涨绿跌；binance：绿涨红跌 */
export type ChartPalette = "wind" | "binance";

const PALETTE = {
  wind: {
    up: "#e53935",
    down: "#1b8f5a",
    upVol: "rgba(229, 57, 53, 0.45)",
    downVol: "rgba(27, 143, 90, 0.45)",
  },
  binance: {
    up: "#0ecb81",
    down: "#f6465d",
    upVol: "rgba(14, 203, 129, 0.45)",
    downVol: "rgba(246, 70, 93, 0.45)",
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

function sma(closes: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < closes.length; i++) {
    sum += closes[i];
    if (i >= period) sum -= closes[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

function toMaLine(klines: Kline[], period: number): LineData[] {
  const closes = klines.map((k) => Number(k[4]));
  const vals = sma(closes, period);
  const rows: LineData[] = [];
  for (let i = 0; i < klines.length; i++) {
    const v = vals[i];
    if (v == null) continue;
    rows.push({
      time: barLocalSec(klines[i]) as UTCTimestamp,
      value: v,
    });
  }
  return rows;
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

/** 十字光标时间 → 最近一根 K 线（允许 ±1s 误差） */
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
  // 周期内任意位置悬停都应对上该根 K
  return best;
}

type Props = {
  klines: Kline[];
  symbol: string;
  /** 换标的/周期时变化，触发贴右；同 key 下左滑补历史不打断视口 */
  seriesKey?: string;
  /** 拖到左缘时请求更早窗口（主流台「滚动加载历史」） */
  onNeedHistory?: () => void;
  /** 首屏/切票拉取中；与空 klines 区分，避免永远停在 Loading */
  loading?: boolean;
  /** 默认 wind（红涨绿跌），对齐国内终端 */
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
  const stageRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma7Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma25Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma99Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const klinesRef = useRef(klines) as MutableRefObject<Kline[]>;
  const prevKeyRef = useRef<string | undefined>(undefined);
  const prevFirstTsRef = useRef<number | null>(null);
  /** 图上最后一根 openTime（UTC ms），供 update 单调性校验 */
  const prevLastTsRef = useRef<number | null>(null);
  const prevLenRef = useRef(0);
  const historyBusyRef = useRef(false);
  const onNeedHistoryRef = useRef(onNeedHistory);
  const paletteRef = useRef(palette);
  const [tip, setTip] = useState<HoverTip | null>(null);

  klinesRef.current = klines;
  onNeedHistoryRef.current = onNeedHistory;
  paletteRef.current = palette;

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

    const ma7 = chart.addLineSeries({
      color: "#f0b90b",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const ma25 = chart.addLineSeries({
      color: "#d94cff",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    const ma99 = chart.addLineSeries({
      color: "#1e88e5",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });

    // 用 stage 原生 mousemove 定位侧方提示（不依赖 LWC point 边界）
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

    // 左缘接近逻辑原点时补历史；数据过少时不触发（切票首屏会误触）
    const onRange = () => {
      const range = chart.timeScale().getVisibleLogicalRange();
      if (!range || historyBusyRef.current) return;
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
    };
  }, []);

  useEffect(() => {
    if (!candleRef.current || !volumeRef.current) return;
    if (!klines.length) {
      candleRef.current.setData([]);
      volumeRef.current.setData([]);
      ma7Ref.current?.setData([]);
      ma25Ref.current?.setData([]);
      ma99Ref.current?.setData([]);
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
    // LWC series.update 只能改「当前最后一根」或追加更新的一根；历史 prepend / 换票必须 setData
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
      volumeRef.current!.setData(klines.map((k) => toVolume(k, pal)));
      ma7Ref.current?.setData(toMaLine(klines, 7));
      ma25Ref.current?.setData(toMaLine(klines, 25));
      ma99Ref.current?.setData(toMaLine(klines, 99));
    };

    let usedTail = false;
    if (canTailUpdate) {
      // 只从「旧最后一根」起：同 time 覆盖 OHLC，再严格单调追加；禁止回写更早 bar
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
            volumeRef.current.update(toVolume(klines[i], pal));
          }
          ma7Ref.current?.setData(toMaLine(klines, 7));
          ma25Ref.current?.setData(toMaLine(klines, 25));
          ma99Ref.current?.setData(toMaLine(klines, 99));
          usedTail = true;
        } catch {
          usedTail = false;
        }
      }
    }
    if (!usedTail) applyFull();

    if (keyChanged) {
      chartRef.current?.timeScale().scrollToRealTime();
      prevKeyRef.current = key;
    } else if (prepended && range && added > 0) {
      chartRef.current?.timeScale().setVisibleLogicalRange({
        from: range.from + added,
        to: range.to + added,
      });
    }
    prevFirstTsRef.current = firstTs;
    prevLastTsRef.current = lastTs;
    prevLenRef.current = klines.length;
    setTip(null);
  }, [klines, seriesKey, symbol]);

  useEffect(() => {
    if (!tip) return;
    const tipEl = tipRef.current;
    if (!tipEl) return;
    const tw = tipEl.offsetWidth || 160;
    const th = tipEl.offsetHeight || 150;
    const gap = 18;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    // 侧方：默认鼠标右侧，贴边翻左侧；垂直居中光标
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
    <div className="bn-chart-root">
      <div className="bn-ohlc-bar">
        <span className="bn-ohlc-pair">{pair}</span>
        <span className="bn-ma-legend">
          <i style={{ color: "#f0b90b" }}>MA(7)</i>
          <i style={{ color: "#d94cff" }}>MA(25)</i>
          <i style={{ color: "#1e88e5" }}>MA(99)</i>
        </span>
        {!klines.length ? (
          <span className="mk-muted">
            {loading ? "Loading chart…" : "No chart data"}
          </span>
        ) : null}
      </div>
      <div ref={stageRef} className="bn-chart-stage">
        <div ref={wrapRef} className="bn-chart-canvas" />
      </div>
      {tipNode}
    </div>
  );
}
