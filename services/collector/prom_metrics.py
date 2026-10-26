"""Collector Prometheus 指标（独立 HTTP 端口，供 scrape）。"""

from __future__ import annotations

import os
import threading

from prometheus_client import Counter, Gauge, Histogram, start_http_server

COLLECTOR_UP = Gauge("equitylab_collector_up", "Collector process heartbeating")
CN_EQUITY_UNIVERSE = Gauge(
    "equitylab_cn_equity_universe_size", "A-share universe size in rotator/catalog"
)
CN_EQUITY_SKIP = Gauge(
    "equitylab_cn_equity_skip", "1 if COLLECTOR_SKIP_CN_EQUITY else 0"
)
CN_EQUITY_POLL = Histogram(
    "equitylab_cn_equity_poll_seconds",
    "A-share poll cycle duration seconds",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
BINANCE_WS_UP = Gauge("equitylab_binance_ws_up", "1 if Binance WS healthy")
QDB_WRITE_ERRORS = Counter(
    "equitylab_qdb_write_errors_total", "qdb write/post failures"
)

_started = False


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


def observe_poll(seconds: float) -> None:
    CN_EQUITY_POLL.observe(max(0.0, seconds))


def set_binance_ws(up: bool) -> None:
    BINANCE_WS_UP.set(1 if up else 0)


def inc_qdb_error() -> None:
    QDB_WRITE_ERRORS.inc()


def heartbeat_loop(interval_s: float = 15.0) -> None:
    """Keep up=1 while process lives."""

    def _run() -> None:
        import time

        while True:
            COLLECTOR_UP.set(1)
            time.sleep(interval_s)

    threading.Thread(target=_run, name="collector-metrics-hb", daemon=True).start()
