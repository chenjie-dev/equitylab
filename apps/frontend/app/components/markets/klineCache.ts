/**
 * 切票用的模块级 K 线 LRU：命中则首屏即时画图，后台再校验。
 * 仅缓存 REST docs 首屏页（不含左滑历史整段）。
 */

import type { Kline } from "./chartIndicators";

const MAX_ENTRIES = 16;

type Entry = { rows: Kline[]; at: number };

const store = new Map<string, Entry>();
const inflight = new Map<string, Promise<Kline[]>>();

export function klineCacheKey(
  market: string,
  symbol: string,
  interval: string,
): string {
  return `${market}:${symbol}:${interval}`;
}

export function getCachedKlines(key: string): Kline[] | null {
  const hit = store.get(key);
  if (!hit) return null;
  // 刷新 LRU 顺序
  store.delete(key);
  store.set(key, hit);
  return hit.rows;
}

export function setCachedKlines(key: string, rows: Kline[]): void {
  if (store.has(key)) store.delete(key);
  store.set(key, { rows, at: Date.now() });
  while (store.size > MAX_ENTRIES) {
    const oldest = store.keys().next().value;
    if (oldest == null) break;
    store.delete(oldest);
  }
}

/** 后台预取；已缓存或进行中则跳过。失败静默。 */
export function prefetchKlines(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<Kline[]>,
): void {
  if (store.has(key) || inflight.has(key)) return;
  const ac = new AbortController();
  const p = fetcher(ac.signal)
    .then((rows) => {
      if (rows.length) setCachedKlines(key, rows);
      return rows;
    })
    .catch(() => [] as Kline[])
    .finally(() => {
      inflight.delete(key);
    });
  inflight.set(key, p);
}

export async function fetchSpotKlines(
  symbol: string,
  interval: string,
  limit: number,
  signal?: AbortSignal,
  endTime?: number,
): Promise<Kline[]> {
  const q = new URLSearchParams({
    symbol,
    interval,
    limit: String(limit),
  });
  if (endTime != null) q.set("endTime", String(endTime));
  try {
    const res = await fetch(`/api/market/binance/klines?${q}`, { signal });
    if (!res.ok) return [];
    const body = (await res.json()) as unknown;
    return Array.isArray(body) ? (body as Kline[]) : [];
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    return [];
  }
}
