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

function toVolume(k: Kline): HistogramData {
  const up = Number(k[4]) >= Number(k[1]);
  return {
    time: barLocalSec(k) as UTCTimestamp,
    value: Number(k[5]),
    color: up ? "rgba(14, 203, 129, 0.45)" : "rgba(246, 70, 93, 0.45)",
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
};

export function BinanceChart({ klines, symbol }: Props) {
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
  const [tip, setTip] = useState<HoverTip | null>(null);

  klinesRef.current = klines;

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

    const candles = chart.addCandlestickSeries({
      upColor: "#0ecb81",
      downColor: "#f6465d",
      borderVisible: false,
      wickUpColor: "#0ecb81",
      wickDownColor: "#f6465d",
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

    return () => {
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
    if (!candleRef.current || !volumeRef.current || !klines.length) return;
    candleRef.current.setData(klines.map(toCandle));
    volumeRef.current.setData(klines.map(toVolume));
    ma7Ref.current?.setData(toMaLine(klines, 7));
    ma25Ref.current?.setData(toMaLine(klines, 25));
    ma99Ref.current?.setData(toMaLine(klines, 99));
    chartRef.current?.timeScale().scrollToRealTime();
    setTip(null);
  }, [klines]);

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
          <span className="mk-muted">Loading chart…</span>
        ) : null}
      </div>
      <div ref={stageRef} className="bn-chart-stage">
        <div ref={wrapRef} className="bn-chart-canvas" />
      </div>
      {tipNode}
    </div>
  );
}
