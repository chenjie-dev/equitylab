/**
 * 币安 Original 常用指标计算（主图 MA/BOLL，副图 MACD）。
 */

import type { HistogramData, LineData, UTCTimestamp } from "lightweight-charts";
import { timeToLocal } from "../../../lib/time";

/** Binance kline row: openTime, o, h, l, c, volume, … */
export type Kline = [number, string, string, string, string, string, ...unknown[]];

function barLocalSec(k: Kline): number {
  return timeToLocal(Math.floor(Number(k[0]) / 1000));
}

export function sma(closes: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < closes.length; i++) {
    sum += closes[i];
    if (i >= period) sum -= closes[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

/** EMA；seed 用前 period 根 SMA */
export function ema(closes: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  if (closes.length < period) {
    return closes.map(() => null);
  }
  let sum = 0;
  for (let i = 0; i < period; i++) sum += closes[i];
  let prev = sum / period;
  for (let i = 0; i < period - 1; i++) out.push(null);
  out.push(prev);
  const k = 2 / (period + 1);
  for (let i = period; i < closes.length; i++) {
    prev = closes[i] * k + prev * (1 - k);
    out.push(prev);
  }
  return out;
}

export function toMaLine(klines: Kline[], period: number): LineData[] {
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

/** 布林带：中轨 SMA(20)，上下轨 ±2σ（币安默认） */
export function toBoll(
  klines: Kline[],
  period = 20,
  mult = 2,
): { mid: LineData[]; upper: LineData[]; lower: LineData[] } {
  const closes = klines.map((k) => Number(k[4]));
  const mid: LineData[] = [];
  const upper: LineData[] = [];
  const lower: LineData[] = [];
  for (let i = 0; i < closes.length; i++) {
    if (i < period - 1) continue;
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += closes[j];
    const mean = sum / period;
    let varSum = 0;
    for (let j = i - period + 1; j <= i; j++) {
      const d = closes[j] - mean;
      varSum += d * d;
    }
    const std = Math.sqrt(varSum / period);
    const t = barLocalSec(klines[i]) as UTCTimestamp;
    mid.push({ time: t, value: mean });
    upper.push({ time: t, value: mean + mult * std });
    lower.push({ time: t, value: mean - mult * std });
  }
  return { mid, upper, lower };
}

export type MacdSeries = {
  dif: LineData[];
  dea: LineData[];
  hist: HistogramData[];
};

/** MACD(12,26,9)：DIF / DEA / 柱 */
export function toMacd(
  klines: Kline[],
  fast = 12,
  slow = 26,
  signal = 9,
  histUp = "rgba(229, 57, 53, 0.7)",
  histDown = "rgba(27, 143, 90, 0.7)",
): MacdSeries {
  const closes = klines.map((k) => Number(k[4]));
  const emaFast = ema(closes, fast);
  const emaSlow = ema(closes, slow);
  const difRaw: (number | null)[] = closes.map((_, i) => {
    const a = emaFast[i];
    const b = emaSlow[i];
    if (a == null || b == null) return null;
    return a - b;
  });
  const difVals = difRaw.map((v) => (v == null ? 0 : v));
  // DEA = EMA(DIF)；仅对已有 DIF 的区间有意义，用完整序列但前端跳过 null
  const firstDif = difRaw.findIndex((v) => v != null);
  const deaAll: (number | null)[] = difRaw.map(() => null);
  if (firstDif >= 0) {
    const slice = difVals.slice(firstDif);
    const deaSlice = ema(slice, signal);
    for (let i = 0; i < deaSlice.length; i++) {
      deaAll[firstDif + i] = deaSlice[i];
    }
  }

  const dif: LineData[] = [];
  const dea: LineData[] = [];
  const hist: HistogramData[] = [];
  for (let i = 0; i < klines.length; i++) {
    const d = difRaw[i];
    const e = deaAll[i];
    if (d == null || e == null) continue;
    const t = barLocalSec(klines[i]) as UTCTimestamp;
    const h = d - e;
    dif.push({ time: t, value: d });
    dea.push({ time: t, value: e });
    hist.push({
      time: t,
      value: h,
      color: h >= 0 ? histUp : histDown,
    });
  }
  return { dif, dea, hist };
}
