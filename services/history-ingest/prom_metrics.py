"""history-ingest Prometheus 指标（独立 HTTP 端口）。"""

from __future__ import annotations

import os
import threading

from prometheus_client import Counter, Gauge, start_http_server

INGEST_UP = Gauge("equitylab_history_ingest_up", "history-ingest process heartbeating")
UNIVERSE = Gauge("equitylab_history_ingest_universe", "Universe size this round")
COVERAGE_OK = Gauge(
    "equitylab_history_ingest_coverage_ok", "Symbols meeting MIN_BARS in window"
)
COVERAGE_RATIO = Gauge(
    "equitylab_history_ingest_coverage_ratio",
    "ok / universe coverage ratio (0–1)",
)
GAPS_QUEUED = Gauge(
    "equitylab_history_ingest_gaps_queued", "Gaps queued for fill this round"
)
FILL_TOTAL = Counter(
    "equitylab_history_ingest_fill_total",
    "Fill attempts by status",
    ["status"],
)
ROUND = Gauge("equitylab_history_ingest_round", "Current cover round number")
SKIP = Gauge("equitylab_history_ingest_skip", "1 if HISTORY_INGEST_SKIP else 0")
BAR_DAILY_ROWS = Gauge(
    "equitylab_market_bar_daily_rows",
    "SELECT count(*) FROM market.bar_daily",
)

_started = False


def start_metrics_server() -> None:
    global _started
    if _started:
        return
    port = int(os.environ.get("METRICS_PORT", "9102"))
    start_http_server(port)
    INGEST_UP.set(1)
    _started = True
    print(f"history-ingest metrics listening :{port}/metrics", flush=True)


def set_skip(skip: bool) -> None:
    SKIP.set(1 if skip else 0)


def set_cover(*, universe: int, ok: int, gaps: int, round_n: int) -> None:
    u = max(0, universe)
    o = max(0, ok)
    UNIVERSE.set(u)
    COVERAGE_OK.set(o)
    COVERAGE_RATIO.set((o / u) if u > 0 else 0.0)
    GAPS_QUEUED.set(max(0, gaps))
    ROUND.set(max(0, round_n))


def set_bar_daily_rows(n: int | None) -> None:
    if n is None:
        return
    BAR_DAILY_ROWS.set(max(0, n))


def inc_fill(status: str) -> None:
    FILL_TOTAL.labels(status=status or "unknown").inc()


def heartbeat_loop(interval_s: float = 15.0) -> None:
    def _run() -> None:
        import time

        while True:
            INGEST_UP.set(1)
            time.sleep(interval_s)

    threading.Thread(target=_run, name="history-ingest-metrics-hb", daemon=True).start()
