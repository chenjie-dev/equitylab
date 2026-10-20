"use client";

/**
 * 经 market-data `/qdb/ws` 订阅 qdb snapshots；协议层用 `@equitylab/qdb`。
 */

import { useEffect, useRef } from "react";
import { Client, unscale } from "@equitylab/qdb";

export type QdbSnapshotRow = {
  symbol: string;
  last: number;
  bid?: number;
  ask?: number;
  seq?: number;
};

function rowFromColumns(
  columns: string[],
  values: string[],
): QdbSnapshotRow | null {
  const idx = (name: string) =>
    columns.findIndex((c) => c.toLowerCase() === name);
  const symbolI = idx("symbol");
  const lastI = idx("last");
  if (lastI < 0) return null;
  const bidI = idx("bid_px1");
  const askI = idx("ask_px1");
  const seqI = idx("seq");
  return {
    symbol: symbolI >= 0 ? (values[symbolI] ?? "") : "",
    last: unscale(values[lastI]),
    bid: bidI >= 0 ? unscale(values[bidI]) : undefined,
    ask: askI >= 0 ? unscale(values[askI]) : undefined,
    seq: seqI >= 0 ? Number(values[seqI]) || undefined : undefined,
  };
}

/** @param qdbSymbol 如 `BINANCE:BTCUSDT` / `SSE:600519`；空则断开 */
export function useQdbSnapshot(
  qdbSymbol: string | null,
  onRow: (row: QdbSnapshotRow) => void,
): void {
  const onRowRef = useRef(onRow);
  onRowRef.current = onRow;

  useEffect(() => {
    const symbol = qdbSymbol?.trim();
    if (!symbol) return;

    const client = new Client();
    const sql =
      `SELECT symbol, last, bid_px1, ask_px1, seq ` +
      `FROM snapshots WHERE symbol = '${symbol.replace(/'/g, "")}' SUBSCRIBE`;

    return client.subscribe(sql, {
      onError: (message) => console.warn("qdb ws error", message),
      onSnapshot: (columns, rows) => {
        if (!rows.length) return;
        const row = rowFromColumns(columns, rows[0]);
        if (row) onRowRef.current(row);
      },
      onRow: (columns, values) => {
        const cols =
          columns.length > 0
            ? columns
            : ["symbol", "last", "bid_px1", "ask_px1", "seq"];
        const row = rowFromColumns(cols, values);
        if (row) {
          if (!row.symbol) row.symbol = symbol;
          onRowRef.current(row);
        }
      },
    });
  }, [qdbSymbol]);
}
