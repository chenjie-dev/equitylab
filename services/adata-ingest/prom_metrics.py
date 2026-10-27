"""adata-ingest Prometheus 指标。"""

from __future__ import annotations

import os
import threading

from prometheus_client import Counter, Gauge, start_http_server

UP = Gauge("equitylab_adata_ingest_up", "adata-ingest 进程心跳（1=存活）")
SKIP = Gauge("equitylab_adata_ingest_skip", "1=已跳过（ADATA_INGEST_SKIP）")
ROUND = Gauge("equitylab_adata_ingest_round", "当前轮次")
SYNC_TOTAL = Counter(
    "equitylab_adata_ingest_sync_total",
    "同步结果次数",
    ["dataset", "status"],
)

_started = False


def start_metrics_server() -> None:
    global _started
    if _started:
        return
    port = int(os.environ.get("METRICS_PORT", "9103"))
    start_http_server(port)
    UP.set(1)
    _started = True
    print(f"adata-ingest metrics listening :{port}/metrics", flush=True)


def set_skip(skip: bool) -> None:
    SKIP.set(1 if skip else 0)


def set_round(n: int) -> None:
    ROUND.set(max(0, n))


def inc_sync(dataset: str, status: str) -> None:
    SYNC_TOTAL.labels(dataset=dataset or "unknown", status=status or "unknown").inc()


def heartbeat_loop(interval_s: float = 15.0) -> None:
    def _run() -> None:
        import time

        while True:
            UP.set(1)
            time.sleep(interval_s)

    threading.Thread(target=_run, name="adata-ingest-metrics-hb", daemon=True).start()
