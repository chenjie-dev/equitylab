"""
qdb 写入保留策略：不保留超过 QDB_RETENTION_DAYS（默认 15）天的 docs K 线。

说明：qdb 引擎 WAL（ticks / 聚合 klines）本版无 HTTP 删除接口，无法在业务侧按日裁剪；
本模块只清理 collector 写入的 docs（binance:kline:* / rwa:kline:*），并在回填时拒绝过旧 trades。
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable

RETENTION_DAYS = max(1, int(os.environ.get("QDB_RETENTION_DAYS", "15")))
# 定时 GC 间隔（秒）；默认 1 小时
GC_INTERVAL_SEC = max(60, int(os.environ.get("QDB_RETENTION_GC_SEC", "3600")))


def cutoff_ms(now: float | None = None) -> int:
    t = time.time() if now is None else now
    return int((t - RETENTION_DAYS * 86400) * 1000)


def cutoff_ns(now: float | None = None) -> int:
    return cutoff_ms(now) * 1_000_000


def filter_binance_kline_rows(
    rows: list[Any], *, now: float | None = None
) -> list[Any]:
    """币安数组行：`[openTimeMs, o, h, l, c, v, …]`。"""
    cut = cutoff_ms(now)
    out: list[Any] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or not row:
            continue
        try:
            ts = int(row[0])
        except (TypeError, ValueError):
            continue
        if ts >= cut:
            out.append(row)
    return out


def filter_rwa_kline_infos(
    infos: list[Any], *, now: float | None = None
) -> list[Any]:
    """RWA klineInfos：`[openTimeSec, o, h, l, c, …]`。"""
    cut_sec = cutoff_ms(now) // 1000
    out: list[Any] = []
    for row in infos:
        if not isinstance(row, (list, tuple)) or not row:
            continue
        try:
            ts = int(row[0])
        except (TypeError, ValueError):
            continue
        if ts >= cut_sec:
            out.append(row)
    return out


def trim_rwa_kline_doc(raw: Any, *, now: float | None = None) -> Any:
    if not isinstance(raw, dict):
        return raw
    data = raw.get("data")
    if not isinstance(data, dict):
        return raw
    infos = data.get("klineInfos")
    if not isinstance(infos, list):
        return raw
    trimmed = filter_rwa_kline_infos(infos, now=now)
    if len(trimmed) == len(infos):
        return raw
    return {**raw, "data": {**data, "klineInfos": trimmed}}


def start_docs_gc(
    *,
    get_doc: Callable[[str], Any | None],
    put_docs: Callable[[list[dict[str, Any]]], None],
    binance_symbols: list[str],
    binance_intervals: list[str],
    rwa_tickers: list[str],
    rwa_intervals: list[str],
) -> None:
    """后台定时：重写超龄 docs K 线。"""

    def loop() -> None:
        print(
            f"qdb retention gc days={RETENTION_DAYS} interval_sec={GC_INTERVAL_SEC}",
            flush=True,
        )
        while True:
            try:
                pruned = _gc_once(
                    get_doc=get_doc,
                    put_docs=put_docs,
                    binance_symbols=binance_symbols,
                    binance_intervals=binance_intervals,
                    rwa_tickers=rwa_tickers,
                    rwa_intervals=rwa_intervals,
                )
                if pruned:
                    print(f"qdb retention gc pruned_keys={pruned}", flush=True)
            except Exception as exc:
                print(f"qdb retention gc failed: {exc}", flush=True)
            time.sleep(GC_INTERVAL_SEC)

    threading.Thread(target=loop, name="qdb-retention-gc", daemon=True).start()


def _gc_once(
    *,
    get_doc: Callable[[str], Any | None],
    put_docs: Callable[[list[dict[str, Any]]], None],
    binance_symbols: list[str],
    binance_intervals: list[str],
    rwa_tickers: list[str],
    rwa_intervals: list[str],
) -> int:
    items: list[dict[str, Any]] = []
    for symbol in binance_symbols:
        for interval in binance_intervals:
            key = f"binance:kline:{symbol}:{interval}"
            doc = get_doc(key)
            if not isinstance(doc, dict):
                continue
            rows = doc.get("data")
            if not isinstance(rows, list):
                continue
            trimmed = filter_binance_kline_rows(rows)
            if len(trimmed) == len(rows):
                continue
            items.append({"key": key, "value": {**doc, "data": trimmed}})

    for ticker in rwa_tickers:
        for interval in rwa_intervals:
            key = f"rwa:kline:{ticker}:{interval}"
            doc = get_doc(key)
            if doc is None:
                continue
            trimmed_doc = trim_rwa_kline_doc(doc)
            if trimmed_doc is doc:
                continue
            items.append({"key": key, "value": trimmed_doc})

    if not items:
        return 0
    # 分批写，避免一次过大
    batch = 32
    for i in range(0, len(items), batch):
        put_docs(items[i : i + batch])
    return len(items)
