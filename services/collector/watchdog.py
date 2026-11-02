"""采集进程守护：检测 qdb / 币安 WS / catalog / write_gate，暴露 /health 并做有限自愈。

观察项来自近期全市场不稳：qdb 重建、WS 分片断流、catalog 丢失、docs 积压。
自愈有冷却，避免风暴；Compose healthcheck 可据此重启容器。
"""

from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.request import urlopen

INTERVAL_SEC = float(os.environ.get("COLLECTOR_WATCHDOG_SEC", "15"))
HEALTH_PORT = int(os.environ.get("COLLECTOR_HEALTH_PORT", "9105"))
# 热分片不健康超过此时长 → 重启 WS
WS_DOWN_RESTART_SEC = float(os.environ.get("COLLECTOR_WATCHDOG_WS_RESTART_SEC", "90"))
# docs 积压持续超过此时长只告警（冷 REST 已有背压）
DOCS_PENDING_WARN = int(os.environ.get("COLLECTOR_WATCHDOG_DOCS_WARN", "400"))
ACTION_COOLDOWN_SEC = float(os.environ.get("COLLECTOR_WATCHDOG_ACTION_COOLDOWN_SEC", "180"))

_lock = threading.Lock()
_state: dict[str, Any] = {
    "ok": False,
    "ts": 0.0,
    "checks": {},
    "last_action": "",
    "last_action_at": 0.0,
}
_ws_down_since: float | None = None
_qdb_was_down = False
_started = False


def _qdb_base() -> str:
    return os.environ.get("QDB_URL", "http://qdb:9090").rstrip("/")


def check_qdb() -> dict[str, Any]:
    url = f"{_qdb_base()}/v1/snapshots?symbols=BINANCE:BTCUSDT"
    try:
        with urlopen(url, timeout=3) as resp:
            code = getattr(resp, "status", 200)
            body = resp.read(200)
        ok = 200 <= int(code) < 300
        return {"ok": ok, "status": int(code), "hint": body[:40].decode("utf-8", "replace")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def check_catalog() -> dict[str, Any]:
    try:
        from main import qdb

        doc = qdb.get_doc("binance:exchangeInfo")
        count = 0
        if isinstance(doc, dict):
            count = int(doc.get("count") or len(doc.get("symbols") or []))
        want = 0
        try:
            from markets import BINANCE_SYMBOLS

            want = len(BINANCE_SYMBOLS)
        except Exception:
            pass
        ok = count >= max(16, want // 2) if want else count >= 16
        return {"ok": ok, "count": count, "want": want}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def check_ws() -> dict[str, Any]:
    try:
        from binance_ws import feed_health_stats

        st = feed_health_stats()
        hot_n = int(st.get("hot_total") or 0)
        hot_ok = int(st.get("hot_ok") or 0)
        cold_n = int(st.get("cold_total") or 0)
        cold_ok = int(st.get("cold_ok") or 0)
        # 热门必须活；冷端至少一半（错峰启动期放宽）
        hot_fine = hot_n == 0 or hot_ok >= hot_n
        cold_fine = cold_n == 0 or cold_ok >= max(1, cold_n // 2)
        return {
            "ok": bool(hot_fine and cold_fine),
            "hot_ok": hot_ok,
            "hot_total": hot_n,
            "cold_ok": cold_ok,
            "cold_total": cold_n,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def check_write_gate() -> dict[str, Any]:
    try:
        from write_gate import get_gate

        gate = get_gate()
        if gate is None:
            return {"ok": True, "pending": {}, "note": "gate-not-started"}
        p = gate.pending_counts()
        docs = int(p.get("docs") or 0)
        quotes = int(p.get("quotes") or 0)
        # 积压高不算硬失败（有背压），但标 warn
        ok = docs < DOCS_PENDING_WARN * 3 and quotes < 2000
        return {
            "ok": ok,
            "warn": docs >= DOCS_PENDING_WARN,
            "docs": docs,
            "quotes": quotes,
            "trades": int(p.get("trades") or 0),
            "err": int(p.get("err") or 0),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:160]}


def snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _set_state(ok: bool, checks: dict[str, Any], action: str = "") -> None:
    with _lock:
        _state["ok"] = ok
        _state["ts"] = time.time()
        _state["checks"] = checks
        if action:
            _state["last_action"] = action
            _state["last_action_at"] = time.time()


def _can_act() -> bool:
    with _lock:
        last = float(_state.get("last_action_at") or 0)
    return (time.time() - last) >= ACTION_COOLDOWN_SEC


def _act(name: str, fn: Any) -> None:
    if not _can_act():
        print(f"watchdog skip action={name} (cooldown)", flush=True)
        return
    try:
        print(f"watchdog action={name}", flush=True)
        fn()
        with _lock:
            _state["last_action"] = name
            _state["last_action_at"] = time.time()
        try:
            import prom_metrics as pm

            pm.inc_watchdog_action(name)
        except Exception:
            pass
    except Exception as exc:
        print(f"watchdog action={name} failed: {exc}", flush=True)


def _loop() -> None:
    global _ws_down_since, _qdb_was_down
    while True:
        qdb = check_qdb()
        cat = check_catalog() if qdb.get("ok") else {"ok": False, "skipped": "qdb-down"}
        ws = check_ws()
        gate = check_write_gate()
        checks = {"qdb": qdb, "catalog": cat, "ws": ws, "write_gate": gate}

        # qdb 恢复：重发 catalog + 重启 WS（分片可能在断连风暴里）
        if qdb.get("ok"):
            if _qdb_was_down:
                _qdb_was_down = False

                def _recover() -> None:
                    from markets import publish_binance_exchange_info, _restart_binance_ws

                    publish_binance_exchange_info()
                    _restart_binance_ws()

                _act("qdb_recover_catalog_ws", _recover)
        else:
            _qdb_was_down = True

        # 热 WS 持续不健康 → 重启
        if qdb.get("ok") and not ws.get("ok"):
            if _ws_down_since is None:
                _ws_down_since = time.monotonic()
            elif (time.monotonic() - _ws_down_since) >= WS_DOWN_RESTART_SEC:

                def _restart_ws() -> None:
                    from markets import _restart_binance_ws

                    _restart_binance_ws()

                _act("restart_binance_ws", _restart_ws)
                _ws_down_since = time.monotonic()
        else:
            _ws_down_since = None

        # catalog 缺失且 qdb 通（heal 可能在冷却）→ 守护补一刀
        if (
            qdb.get("ok")
            and isinstance(cat, dict)
            and not cat.get("ok")
            and not cat.get("skipped")
        ):
            want = int(cat.get("want") or 0)
            count = int(cat.get("count") or 0)
            if want > 64 and count < max(64, want // 2):

                def _pub() -> None:
                    from markets import publish_binance_exchange_info

                    publish_binance_exchange_info()

                _act("republish_catalog", _pub)

        # qdb 挂 / catalog 缺失 / WS 热路径不健康 → 503（Compose healthcheck）
        overall = bool(qdb.get("ok")) and bool(ws.get("ok")) and bool(cat.get("ok", True))
        if gate.get("warn"):
            print(
                f"watchdog warn docs_pending={gate.get('docs')} "
                f"quotes_pending={gate.get('quotes')}",
                flush=True,
            )
        _set_state(overall, checks)
        try:
            import prom_metrics as pm

            pm.set_watchdog(
                ok=overall,
                qdb_ok=bool(qdb.get("ok")),
                catalog_ok=bool(cat.get("ok")),
                ws_ok=bool(ws.get("ok")),
                ws_hot_ok=int(ws.get("hot_ok") or 0),
                ws_hot_total=int(ws.get("hot_total") or 0),
                ws_cold_ok=int(ws.get("cold_ok") or 0),
                ws_cold_total=int(ws.get("cold_total") or 0),
            )
        except Exception:
            pass
        if not overall:
            print(
                f"watchdog unhealthy qdb={qdb.get('ok')} catalog={cat.get('ok')} "
                f"ws={ws.get('ok')} hot={ws.get('hot_ok')}/{ws.get('hot_total')} "
                f"cold={ws.get('cold_ok')}/{ws.get('cold_total')}",
                flush=True,
            )
        time.sleep(INTERVAL_SEC)


class _HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        if self.path not in ("/health", "/healthz", "/"):
            self.send_response(404)
            self.end_headers()
            return
        st = snapshot()
        # qdb 短暂重启：503 让编排感知；自愈中也算不健康
        code = 200 if st.get("ok") else 503
        body = json.dumps(st, ensure_ascii=False, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_health_server() -> None:
    def _run() -> None:
        httpd = ThreadingHTTPServer(("0.0.0.0", HEALTH_PORT), _HealthHandler)
        print(f"collector watchdog health :{HEALTH_PORT}/health", flush=True)
        httpd.serve_forever()

    threading.Thread(target=_run, name="collector-health", daemon=True).start()


def start_watchdog() -> None:
    global _started
    if _started:
        return
    _started = True
    start_health_server()
    threading.Thread(target=_loop, name="collector-watchdog", daemon=True).start()
    print(
        f"collector watchdog interval={INTERVAL_SEC:.0f}s "
        f"ws_restart_after={WS_DOWN_RESTART_SEC:.0f}s cooldown={ACTION_COOLDOWN_SEC:.0f}s",
        flush=True,
    )
