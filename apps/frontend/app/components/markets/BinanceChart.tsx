"use client";

/**
 * 币安风格主图：蜡烛 + 成交量 + MA(7/25/99) + 十字光标 OHLC。
 */

import {
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
} from "react";
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
  type MouseEventParams,
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

type Props = {
  klines: Kline[];
  symbol: string;
};

export function BinanceChart({ klines, symbol }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const ma7Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma25Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const ma99Ref = useRef<ISeriesApi<"Line"> | null>(null);
  const klinesRef = useRef(klines) as MutableRefObject<Kline[]>;
  const [ohlc, setOhlc] = useState<OhlcInfo | null>(null);

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
          labelBackgroundColor: "#2b3139",
        },
        horzLine: {
          color: "#848e9c",
          width: 1,
          style: LineStyle.Dashed,
          labelBackgroundColor: "#2b3139",
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

    chart.subscribeCrosshairMove((param: MouseEventParams) => {
      const rows = klinesRef.current;
      if (!param.time || !rows.length) {
        if (rows.length) setOhlc(infoFromKline(rows[rows.length - 1]));
        return;
      }
      // 轴上是 timeToLocal 后的秒，反查真实 UTC 秒再对原始 K 线
      const utcSec = localToUtc(param.time as number);
      const hit = rows.find((k) => Math.floor(Number(k[0]) / 1000) === utcSec);
      if (hit) setOhlc(infoFromKline(hit));
    });

    chartRef.current = chart;
    candleRef.current = candles;
    volumeRef.current = volume;
    ma7Ref.current = ma7;
    ma25Ref.current = ma25;
    ma99Ref.current = ma99;

    return () => {
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
    setOhlc(infoFromKline(klines[klines.length - 1]));
  }, [klines]);

  const pair = symbol.endsWith("USDT")
    ? `${symbol.slice(0, -4)}/USDT`
    : symbol;

  return (
    <div className="bn-chart-root">
      <div className="bn-ohlc-bar">
        {ohlc ? (
          <>
            <span className="bn-ohlc-pair">{pair}</span>
            <span className="bn-ohlc-time">{ohlc.time}</span>
            <span>
              O <b className={ohlc.up ? "up" : "down"}>{fmt(ohlc.open)}</b>
            </span>
            <span>
              H <b className={ohlc.up ? "up" : "down"}>{fmt(ohlc.high)}</b>
            </span>
            <span>
              L <b className={ohlc.up ? "up" : "down"}>{fmt(ohlc.low)}</b>
            </span>
            <span>
              C <b className={ohlc.up ? "up" : "down"}>{fmt(ohlc.close)}</b>
            </span>
            <span className={ohlc.up ? "up" : "down"}>
              {ohlc.up ? "+" : ""}
              {fmt(ohlc.change, 2)}%
            </span>
            <span>
              Vol <b>{fmt(ohlc.volume, 3)}</b>
            </span>
            <span className="bn-ma-legend">
              <i style={{ color: "#f0b90b" }}>MA(7)</i>
              <i style={{ color: "#d94cff" }}>MA(25)</i>
              <i style={{ color: "#1e88e5" }}>MA(99)</i>
            </span>
          </>
        ) : (
          <span className="mk-muted">Loading chart…</span>
        )}
      </div>
      <div ref={wrapRef} className="bn-chart-canvas" />
    </div>
  );
}
