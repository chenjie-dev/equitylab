"""授权回源边车：akshare → market（P0–P3），与 adata-ingest 并行。

产品面仍为 cn-equity；source_code=akshare。不写 qdb。
参考：https://github.com/akfamily/akshare
"""

from __future__ import annotations

import os
import time

from equitylab_market import pg as pg_market

import p0_sync
import p1_sync
import p2_sync
import p3_sync
import prom_metrics as pm
import util

IDLE_SEC = float(os.environ.get("AKSHARE_INGEST_IDLE_SEC", "3600"))


def _import_ak():
    import akshare as ak  # noqa: WPS433

    return ak


def run_round(ak) -> None:
    stocks = p0_sync.run_p0(ak, inc_sync=pm.inc_sync)
    p1_sync.run_p1(ak, stocks, inc_sync=pm.inc_sync)
    p2_sync.run_p2(ak, stocks, inc_sync=pm.inc_sync)
    p3_sync.run_p3(ak, inc_sync=pm.inc_sync)


def main() -> None:
    pm.start_metrics_server()
    pm.heartbeat_loop()
    if util.env_flag("AKSHARE_INGEST_SKIP", "0"):
        pm.set_skip(True)
        print("akshare-ingest skip=1 idle", flush=True)
        while True:
            time.sleep(3600)
    pm.set_skip(False)
    if not pg_market.enabled():
        print("akshare-ingest DATABASE_URL missing; exit", flush=True)
        return
    print(
        f"akshare-ingest start idle_sec={IDLE_SEC} "
        f"stock_limit={util.int_env('AKSHARE_INGEST_STOCK_LIMIT', 80)}",
        flush=True,
    )
    ak = _import_ak()
    round_n = 0
    while True:
        round_n += 1
        pm.set_round(round_n)
        try:
            run_round(ak)
            pm.inc_sync("round", "ok")
        except Exception as exc:
            pm.inc_sync("round", "fail")
            print(f"akshare-ingest round_failed: {exc}", flush=True)
        time.sleep(max(60.0, IDLE_SEC))


if __name__ == "__main__":
    main()
