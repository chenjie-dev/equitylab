"""Collector Prometheus 指标（独立 HTTP 端口，供 scrape）。"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, start_http_server

COLLECTOR_UP = Gauge(
    "equitylab_collector_up", "采集器进程心跳（1=存活）"
)
CN_EQUITY_UNIVERSE = Gauge(
    "equitylab_cn_equity_universe_size", "正在轮询的 A 股标的数"
)
CN_EQUITY_SKIP = Gauge(
    "equitylab_cn_equity_skip", "1=已跳过 A 股采集（COLLECTOR_SKIP_CN_EQUITY）"
)
CN_EQUITY_POLL = Histogram(
    "equitylab_cn_equity_poll_seconds",
    "A 股单轮 REST 拉价耗时（秒）",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
CN_EQUITY_FULL_CYCLE = Gauge(
    "equitylab_cn_equity_full_cycle_seconds",
    "估测扫完一整轮 A 股报价约需秒数",
)
BINANCE_WS_UP = Gauge("equitylab_binance_ws_up", "币安 WebSocket 是否健康（1=通）")
QDB_WRITE_ERRORS = Counter(
    "equitylab_qdb_write_errors_total", "写 qdb 失败累计次数"
)
QUOTE_LAST_SUCCESS = Gauge(
    "equitylab_quote_last_success_unixtime",
    "该市场最后一次成功写报价的 unix 秒（看板用 time()-值 看年龄）",
    ["market"],
)
QUOTES_WRITTEN = Counter(
    "equitylab_quotes_written_total",
    "写入报价累计条数（rate 即吞吐）",
    ["market"],
)
WRITE_GATE_PENDING = Gauge(
    "equitylab_write_gate_pending",
    "写队列积压条数（kind=quotes/trades/docs）",
    ["kind"],
)
WRITE_GATE_TRADE_DROPS = Gauge(
    "equitylab_write_gate_trade_drops_total",
    "成交队列溢出丢弃累计（gauge 展示计数）",
)
SNAPSHOT_AGE_MAX = Gauge(
    "equitylab_snapshot_age_seconds",
    "样本集内最大报价年龄秒数（sample=seed 为种子盘口）",
    ["sample"],
)
SNAPSHOT_STALE = Gauge(
    "equitylab_snapshot_stale_count",
    "样本中超过 STALE_QUOTE_SEC 未更新的只数（休市可偏高）",
    ["sample"],
)

# 本进程内每标的最后写价时间（unix），供 seed 新鲜度旁路
_last_write_by_symbol: dict[str, float] = {}
_lock = threading.Lock()
_started = False

STALE_QUOTE_SEC = float(os.environ.get("STALE_QUOTE_SEC", "120"))
FRESHNESS_INTERVAL_SEC = float(os.environ.get("FRESHNESS_SCAN_SEC", "30"))


def start_metrics_server() -> None:
    global _started
    if _started:
        return
    port = int(os.environ.get("METRICS_PORT", "9101"))
    start_http_server(port)
    COLLECTOR_UP.set(1)
    _started = True
    print(f"collector metrics listening :{port}/metrics", flush=True)


def set_skip(skip: bool) -> None:
    CN_EQUITY_SKIP.set(1 if skip else 0)


def set_universe(n: int) -> None:
    CN_EQUITY_UNIVERSE.set(max(0, n))


def set_full_cycle_seconds(sec: float) -> None:
    CN_EQUITY_FULL_CYCLE.set(max(0.0, sec))


def observe_poll(seconds: float) -> None:
    CN_EQUITY_POLL.observe(max(0.0, seconds))


def set_binance_ws(up: bool) -> None:
    BINANCE_WS_UP.set(1 if up else 0)


def inc_qdb_error() -> None:
    QDB_WRITE_ERRORS.inc()


def _market_of_exchange(exchange: str) -> str:
    ex = (exchange or "").upper()
    if ex in ("SSE", "SZSE", "BSE"):
        return "cn_equity"
    if ex in ("BINANCE", "ONDO"):
        return "binance"
    return "other"


def record_quotes(items: list[dict[str, Any]]) -> None:
    """报价入队/写入成功后调用。"""
    if not items:
        return
    now = time.time()
    counts: dict[str, int] = {}
    with _lock:
        for item in items:
            if not isinstance(item, dict):
                continue
            ex = str(item.get("exchange") or "")
            code = str(item.get("code") or "")
            market = _market_of_exchange(ex)
            counts[market] = counts.get(market, 0) + 1
            if ex and code:
                _last_write_by_symbol[f"{ex}:{code}"] = now
    for market, n in counts.items():
        QUOTE_LAST_SUCCESS.labels(market=market).set(now)
        QUOTES_WRITTEN.labels(market=market).inc(n)


def last_write_age(symbol: str) -> float | None:
    with _lock:
        ts = _last_write_by_symbol.get(symbol)
    if ts is None:
        return None
    return max(0.0, time.time() - ts)


def refresh_write_gate_gauges() -> None:
    try:
        from write_gate import get_gate

        gate = get_gate()
        if gate is None:
            return
        pending = gate.pending_counts()
        WRITE_GATE_PENDING.labels(kind="quotes").set(pending.get("quotes", 0))
        WRITE_GATE_PENDING.labels(kind="trades").set(pending.get("trades", 0))
        WRITE_GATE_PENDING.labels(kind="docs").set(pending.get("docs", 0))
        WRITE_GATE_TRADE_DROPS.set(pending.get("trade_drop", 0))
    except Exception:
        pass


def set_seed_freshness(*, max_age: float, stale_count: int) -> None:
    SNAPSHOT_AGE_MAX.labels(sample="seed").set(max(0.0, max_age))
    SNAPSHOT_STALE.labels(sample="seed").set(max(0, stale_count))


def heartbeat_loop(interval_s: float = 15.0) -> None:
    def _run() -> None:
        while True:
            COLLECTOR_UP.set(1)
            refresh_write_gate_gauges()
            time.sleep(interval_s)

    threading.Thread(target=_run, name="collector-metrics-hb", daemon=True).start()


def start_freshness_worker(seed_codes: list[str], exchange_fn) -> None:
    """周期性根据本进程 last-write map 统计 seed 新鲜度。"""

    def _run() -> None:
        while True:
            try:
                ages: list[float] = []
                stale = 0
                now = time.time()
                for code in seed_codes:
                    try:
                        ex = exchange_fn(code)
                    except Exception:
                        continue
                    sym = f"{ex}:{code}"
                    with _lock:
                        ts = _last_write_by_symbol.get(sym)
                    if ts is None:
                        # 从未写过：视为极旧
                        age = STALE_QUOTE_SEC * 10
                    else:
                        age = max(0.0, now - ts)
                    ages.append(age)
                    if age > STALE_QUOTE_SEC:
                        stale += 1
                if ages:
                    set_seed_freshness(max_age=max(ages), stale_count=stale)
                else:
                    set_seed_freshness(max_age=0.0, stale_count=0)
            except Exception as exc:
                print(f"freshness worker failed: {exc}", flush=True)
            time.sleep(max(5.0, FRESHNESS_INTERVAL_SEC))

    threading.Thread(target=_run, name="collector-freshness", daemon=True).start()
