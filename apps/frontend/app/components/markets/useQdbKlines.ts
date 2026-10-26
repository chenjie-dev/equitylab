"use client";

/**
 * 引擎 klines 订阅读（collector trades → 引擎 → SUBSCRIBE）。
 * 历史首屏仍读 docs（`binance:kline:*`，不进 WS）；本 hook 只推送原生 period 的尾部更新。
 * 折叠周期（3m/30m/…）无原生桶时由调用方继续 docs 轮询。
 *
 * 协议：一条 WS = 一条 SUBSCRIBE；切票须换连接。模块级复用 Client 配置，
 * 先建新订再关旧订，缩短空窗（仍各一条 WS，不复用同一 socket）。
 */

import { useEffect, useRef } from "react";
import { Client, unscale } from "@equitylab/qdb";
import type { Kline } from "./chartIndicators";

const sharedClient = new Client();

/** 与 market-data map_interval 一致：仅 1:1 原生周期可订 */
const NATIVE: Record<string, string> = {
  "1m": "1m",
  "5m": "5m",
  "15m": "15m",
  "1h": "1h",
  "4h": "4h",
  "1d": "1d",
};

export function nativeQdbPeriod(interval: string): string | null {
  return NATIVE[interval] ?? null;
}

function barFromColumns(
  columns: string[],
  values: string[],
): Kline | null {
  const idx = (name: string) =>
    columns.findIndex((c) => c.toLowerCase() === name);
  const tsI = idx("ts");
  const oI = idx("open");
  const hI = idx("high");
  const lI = idx("low");
  const cI = idx("close");
  const vI = idx("volume");
  if (tsI < 0 || oI < 0 || hI < 0 || lI < 0 || cI < 0) return null;
  const tsRaw = Number(values[tsI]);
  if (!Number.isFinite(tsRaw)) return null;
  // qdb ts 多为纳秒；毫秒级则 < 1e12*1000
  const openMs = tsRaw > 1e15 ? Math.floor(tsRaw / 1e6) : tsRaw;
  const o = unscale(values[oI]);
  const h = unscale(values[hI]);
  const l = unscale(values[lI]);
  const c = unscale(values[cI]);
  const vol = vI >= 0 ? Number(values[vI]) || 0 : 0;
  return [
    openMs,
    String(o),
    String(h),
    String(l),
    String(c),
    String(vol),
  ];
}

/**
 * @param qdbSymbol `BINANCE:BTCUSDT`；空则断开
 * @param interval 前端周期；非原生则 no-op
 */
export function useQdbKlines(
  qdbSymbol: string | null,
  interval: string,
  onBar: (bar: Kline) => void,
): void {
  const onBarRef = useRef(onBar);
  onBarRef.current = onBar;
  const period = nativeQdbPeriod(interval);

  useEffect(() => {
    const symbol = qdbSymbol?.trim();
    if (!symbol || !period) return;
    const safe = symbol.replace(/'/g, "");
    const sql =
      `SELECT ts, open, high, low, close, volume ` +
      `FROM klines WHERE symbol = '${safe}' AND period = '${period}' SUBSCRIBE`;

    return sharedClient.subscribe(sql, {
      onError: (message) => console.warn("qdb klines ws", safe, message),
      onSnapshot: (columns, rows) => {
        // 快照可能很长；只取最后一根作尾刷新，历史仍靠 docs
        if (!rows.length) return;
        const bar = barFromColumns(columns, rows[rows.length - 1]);
        if (bar) onBarRef.current(bar);
      },
      onRow: (columns, values) => {
        const cols =
          columns.length > 0
            ? columns
            : ["ts", "open", "high", "low", "close", "volume"];
        const bar = barFromColumns(cols, values);
        if (bar) onBarRef.current(bar);
      },
    });
  }, [qdbSymbol, period]);
}
