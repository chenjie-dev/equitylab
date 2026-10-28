"use client";

/**
 * 多标的 qdb snapshots 订阅读（经 gateway `/api/market/qdb/ws`）。
 * 每标的一条 SUBSCRIBE（qdb WHERE 仅支持单 symbol =）；仅经 `@equitylab/qdb` Client。
 */

import { useEffect, useMemo, useRef } from "react";
import { Client, unscale } from "@equitylab/qdb";
import type { QdbSnapshotRow } from "./useQdbSnapshot";

function rowFromColumns(
  columns: string[],
  values: string[],
  fallbackSymbol: string,
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
    symbol: symbolI >= 0 ? values[symbolI] || fallbackSymbol : fallbackSymbol,
    last: unscale(values[lastI]),
    bid: bidI >= 0 ? unscale(values[bidI]) : undefined,
    ask: askI >= 0 ? unscale(values[askI]) : undefined,
    seq: seqI >= 0 ? Number(values[seqI]) || undefined : undefined,
  };
}

function emit(
  columns: string[],
  values: string[],
  fallback: string,
  onRow: (row: QdbSnapshotRow) => void,
) {
  const row = rowFromColumns(columns, values, fallback);
  if (row) onRow(row);
}

/**
 * @param qdbSymbols 如 `BINANCE:BTCUSDT`；去重后订阅；空数组断开全部
 */
export function useQdbSnapshots(
  qdbSymbols: readonly string[],
  onRow: (row: QdbSnapshotRow) => void,
): void {
  const onRowRef = useRef(onRow);
  onRowRef.current = onRow;

  const key = useMemo(() => {
    const uniq = [
      ...new Set(
        qdbSymbols.map((s) => s.trim()).filter((s) => s.length > 0),
      ),
    ];
    uniq.sort();
    return uniq.join("\n");
  }, [qdbSymbols]);

  useEffect(() => {
    if (!key) return;
    const symbols = key.split("\n");
    const closes: Array<() => void> = [];

    for (const symbol of symbols) {
      const safe = symbol.replace(/'/g, "");
      const client = new Client();
      const sql =
        `SELECT symbol, last, bid_px1, ask_px1, seq ` +
        `FROM snapshots WHERE symbol = '${safe}' SUBSCRIBE`;
      closes.push(
        client.subscribe(sql, {
          onError: (message) =>
            console.warn("qdb snapshots ws", safe, message),
          onSnapshot: (columns, rows) => {
            for (const values of rows) {
              emit(columns, values, safe, (r) => onRowRef.current(r));
            }
          },
          onRow: (columns, values) => {
            const cols =
              columns.length > 0
                ? columns
                : ["symbol", "last", "bid_px1", "ask_px1", "seq"];
            emit(cols, values, safe, (r) => onRowRef.current(r));
          },
        }),
      );
    }

    return () => {
      for (const c of closes) c();
    };
  }, [key]);
}
