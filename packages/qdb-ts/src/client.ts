/**
 * qdb HTTP 客户端（浏览器 / Node）。
 * 浏览器订阅读默认走 **gateway** `/api/market/qdb/ws`（同源），勿直连 market-data 端口。
 */

import { PRICE_SCALE } from "./scale";

export type SnapshotRow = Record<string, unknown> & {
  symbol?: string;
  exchange?: string;
  code?: string;
  price?: number;
  seq?: number;
};

export type QdbClientOptions = {
  /** HTTP 基址，默认 `QDB_URL` / `http://127.0.0.1:9090`（浏览器勿直连容器内网名） */
  baseUrl?: string;
  /** WS 代理，默认同源 gateway `/api/market/qdb/ws`，或 `NEXT_PUBLIC_MARKET_WS_URL` */
  wsProxyUrl?: string;
  timeoutMs?: number;
};

function defaultHttpBase(): string {
  if (typeof process !== "undefined" && process.env?.QDB_URL) {
    return process.env.QDB_URL.replace(/\/$/, "");
  }
  return "http://127.0.0.1:9090";
}

function defaultWsProxy(): string {
  if (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_MARKET_WS_URL) {
    const b = process.env.NEXT_PUBLIC_MARKET_WS_URL.replace(/\/$/, "");
    if (b.endsWith("/qdb/ws")) return b;
    return `${b}/api/market/qdb/ws`;
  }
  if (typeof process !== "undefined" && process.env?.QDB_WS_PROXY) {
    return process.env.QDB_WS_PROXY.replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host || "localhost:3000";
    return `${proto}//${host}/api/market/qdb/ws`;
  }
  return "ws://127.0.0.1:3000/api/market/qdb/ws";
}

export class Client {
  readonly baseUrl: string;
  readonly wsProxyUrl: string;
  readonly timeoutMs: number;
  readonly priceScale = PRICE_SCALE;

  constructor(opts: QdbClientOptions = {}) {
    this.baseUrl = (opts.baseUrl ?? defaultHttpBase()).replace(/\/$/, "");
    this.wsProxyUrl = (opts.wsProxyUrl ?? defaultWsProxy()).replace(/\/$/, "");
    this.timeoutMs = opts.timeoutMs ?? 10_000;
  }

  async waitReady(timeoutMs = 60_000): Promise<boolean> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      try {
        const r = await fetch(`${this.baseUrl}/v1/snapshots`, {
          signal: AbortSignal.timeout(2_000),
        });
        if (r.ok) return true;
      } catch {
        /* retry */
      }
      await new Promise((r) => setTimeout(r, 1_000));
    }
    return false;
  }

  async snapshots(symbols?: string[]): Promise<SnapshotRow[]> {
    const q =
      symbols && symbols.length
        ? `?symbols=${encodeURIComponent(symbols.join(","))}`
        : "";
    const r = await fetch(`${this.baseUrl}/v1/snapshots${q}`, {
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!r.ok) throw new Error(`snapshots ${r.status}`);
    const body = (await r.json()) as { data?: SnapshotRow[] };
    return body.data ?? [];
  }

  async klines(
    symbol: string,
    period: string,
    opts?: { limit?: number; endTimeMs?: number },
  ): Promise<Record<string, unknown>[]> {
    const q = new URLSearchParams({ symbol, period });
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    if (opts?.endTimeMs != null) q.set("endTime", String(opts.endTimeMs));
    const r = await fetch(`${this.baseUrl}/v1/klines?${q}`, {
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (r.status === 404) return [];
    if (!r.ok) throw new Error(`klines ${r.status}`);
    const body = (await r.json()) as { data?: Record<string, unknown>[] };
    return body.data ?? [];
  }

  async getDoc(key: string): Promise<unknown | null> {
    const r = await fetch(
      `${this.baseUrl}/v1/docs?key=${encodeURIComponent(key)}`,
      { signal: AbortSignal.timeout(this.timeoutMs) },
    );
    if (r.status === 404) return null;
    if (!r.ok) return null;
    return r.json();
  }

  async putDocs(items: { key: string; value: unknown }[]): Promise<number> {
    if (!items.length) return 0;
    const r = await fetch(`${this.baseUrl}/v1/docs`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ items }),
      signal: AbortSignal.timeout(Math.max(this.timeoutMs, 30_000)),
    });
    if (!r.ok) throw new Error(`docs ${r.status}`);
    const body = (await r.json()) as { written?: number };
    return body.written ?? 0;
  }

  async postQuotes(items: Record<string, unknown>[]): Promise<number> {
    if (!items.length) return 0;
    const r = await fetch(`${this.baseUrl}/v1/quotes`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ items }),
      signal: AbortSignal.timeout(Math.max(this.timeoutMs, 60_000)),
    });
    if (!r.ok) throw new Error(`quotes ${r.status}`);
    const body = (await r.json()) as { written?: number };
    return body.written ?? 0;
  }

  async postTrades(items: Record<string, unknown>[]): Promise<number> {
    if (!items.length) return 0;
    const r = await fetch(`${this.baseUrl}/v1/trades`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ items }),
      signal: AbortSignal.timeout(Math.max(this.timeoutMs, 120_000)),
    });
    if (!r.ok) throw new Error(`trades ${r.status}`);
    const body = (await r.json()) as { written?: number };
    return body.written ?? 0;
  }

  /**
   * 浏览器/Node WebSocket 订阅读。浏览器应连 `wsProxyUrl`（market-data）。
   * 返回 `close()`。
   */
  subscribe(
    sql: string,
    handlers: {
      onSnapshot?: (columns: string[], rows: string[][]) => void;
      onRow?: (columns: string[], values: string[]) => void;
      onError?: (message: string) => void;
      onWaiting?: () => void;
    },
  ): () => void {
    const url = this.wsProxyUrl;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let columns: string[] = [];

    const connect = () => {
      if (closed || typeof WebSocket === "undefined") return;
      ws = new WebSocket(url);
      ws.onopen = () => ws?.send(sql);
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(String(ev.data)) as {
            type?: string;
            columns?: string[];
            rows?: string[][];
            values?: string[];
            message?: string;
          };
          if (msg.type === "error") {
            handlers.onError?.(msg.message ?? "error");
            return;
          }
          if (msg.type === "waiting") {
            handlers.onWaiting?.();
            return;
          }
          if (msg.type === "snapshot" && msg.columns && msg.rows) {
            columns = msg.columns;
            handlers.onSnapshot?.(msg.columns, msg.rows);
            return;
          }
          if (msg.type === "row" && msg.values) {
            const cols = msg.columns ?? columns;
            handlers.onRow?.(cols, msg.values);
          }
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        if (!closed) retry = setTimeout(connect, 2000);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }
}
