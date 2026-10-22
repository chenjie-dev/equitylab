"""采集公开行情并写入 qdb。本进程是唯一回源方；读路径只查 qdb。"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

import requests
from equitylab_qdb import Client, scale as qdb_scale
from equitylab_qdb import PRICE_SCALE as SCALE

CODES = os.environ.get(
    "COLLECTOR_CODES",
    "600519,000001,300750,601318,000858,002594,600036,601012,688981,510300",
)
INTERVAL = float(os.environ.get("COLLECTOR_INTERVAL_MS", "500")) / 1000
UA = {"User-Agent": "equitylab-collector", "Referer": "https://finance.sina.com.cn"}
# 进程级 qdb 客户端（读写）；写纪律：仅本进程回源
qdb = Client(timeout=30.0)


def main() -> None:
    codes = [c.strip() for c in CODES.split(",") if c.strip()]
    wait_qdb()
    # 币安：WS 推送写 qdb；A 股仍 REST 热路径；盘口/RWA/回填后台。
    print(
        f"collector cadence interval_ms={int(INTERVAL * 1000)} "
        f"ashare={len(codes)} (binance=ws→qdb; ashare=rest hot-path)",
        flush=True,
    )
    import markets

    try:
        markets.start_binance_ws()
    except Exception as exc:
        print(f"binance ws start failed: {exc}", flush=True)
    try:
        markets.start_binance_kline_feed()
    except Exception as exc:
        print(f"binance kline feed start failed: {exc}", flush=True)
    try:
        markets.start_rwa_feed()
    except Exception as exc:
        print(f"rwa feed start failed: {exc}", flush=True)
    try:
        markets.start_rwa_kline_feed()
    except Exception as exc:
        print(f"rwa kline feed start failed: {exc}", flush=True)

    threading.Thread(
        target=_backfill_worker,
        args=(codes, markets),
        name="collector-backfill",
        daemon=True,
    ).start()
    threading.Thread(
        target=_slow_worker,
        args=(markets,),
        name="collector-slow",
        daemon=True,
    ).start()

    last_vol: dict[str, int] = {}
    cycle = 0
    while True:
        t0 = time.monotonic()
        try:
            poll_quotes(codes, last_vol)
        except Exception as exc:
            print(f"ashare poll failed: {exc}", flush=True)
        # WS 健康时 noop；断流才 REST 兜底
        try:
            markets.poll_quotes_hot()
        except Exception as exc:
            print(f"binance rest fallback failed: {exc}", flush=True)
        if cycle % 60 == 0:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            ws_ok = False
            try:
                ws_ok = markets.binance_ws_healthy()
            except Exception:
                pass
            print(
                f"collector tick cycle={cycle} ashare_ms={elapsed_ms} "
                f"binance_ws={'up' if ws_ok else 'down'}",
                flush=True,
            )
        cycle += 1
        remain = INTERVAL - (time.monotonic() - t0)
        if remain > 0:
            time.sleep(remain)


def _backfill_worker(codes: list[str], markets: object) -> None:
    print(f"collector backfill {len(codes)} symbols (background)", flush=True)
    for code in codes:
        try:
            backfill(code)
        except Exception as exc:
            print(f"backfill {code} failed: {exc}", flush=True)
    try:
        markets.backfill_markets()  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"market backfill failed: {exc}", flush=True)
    print("collector backfill done", flush=True)


def _slow_worker(markets: object) -> None:
    """盘口/成交 docs：独立节奏，不阻塞 quotes（RWA 另有 collector-rwa 线程）。"""
    cycle = 0
    while True:
        t0 = time.monotonic()
        try:
            markets.poll_slow(cycle)  # type: ignore[attr-defined]
        except Exception as exc:
            print(f"slow poll failed: {exc}", flush=True)
        cycle += 1
        # ~1s 一轮；每轮只刷 1～2 个 depth，避免打爆上游
        remain = 1.0 - (time.monotonic() - t0)
        if remain > 0:
            time.sleep(remain)


def wait_qdb() -> None:
    if not qdb.wait_ready(timeout=60.0):
        raise SystemExit("qdb not ready")


def backfill(code: str) -> None:
    exchange, _ = split_symbol(code)
    symbol = f"{exchange}:{code.zfill(6)}"
    have_5m = {int(row["ts"]) for row in get_klines(symbol, "5m")}
    have_1d = {int(row["ts"]) for row in get_klines(symbol, "1d")}
    minute = sina_klines(code, 5, 500)
    daily = sina_klines(code, 240, 300)
    covered = {bar["day"][:10] for bar in minute}
    events: list[tuple[int, dict, str]] = []
    for bar in daily:
        day = bar["day"][:10]
        if day in covered:
            continue
        ts = bar_ts(day)
        if ts in have_1d:
            continue
        events.append((ts, bar, "1d"))
    for bar in minute:
        ts = bar_ts(bar["day"])
        if ts in have_5m:
            continue
        events.append((ts, bar, "5m"))
    events.sort(key=lambda item: item[0])
    trades: list[dict] = []
    for ts, bar, _kind in events:
        trades.extend(ohlc_trades(exchange, code, ts, bar))
    if trades:
        post("/v1/trades", {"items": trades})
        print(f"backfill {symbol} trades={len(trades)}", flush=True)


def poll_quotes(codes: list[str], last_vol: dict[str, int]) -> None:
    symbols = ",".join(sina_symbol(c) for c in codes)
    text = requests.get(f"https://hq.sinajs.cn/list={symbols}", headers=UA, timeout=8).content.decode("gb18030", "replace")
    quotes = []
    trades = []
    now_ns = int(time.time() * 1_000_000_000)
    for row in parse_sina(text):
        quotes.append(
            {
                "exchange": row["exchange"],
                "code": row["code"],
                "ts_ns": now_ns,
                "last": scale(row["price"]),
                "name": row["name"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "pre_close": row["pre_close"],
                "price": row["price"],
                "volume": row["volume"],
                "amount": row["amount"],
            }
        )
        vol = int(row["volume"])
        prev = last_vol.get(row["code"], 0)
        delta = vol - prev if vol > prev else 0
        last_vol[row["code"]] = max(vol, prev)
        if delta > 0:
            trades.append(
                {
                    "exchange": row["exchange"],
                    "code": row["code"],
                    "ts_ns": now_ns,
                    "price": scale(row["price"]),
                    "volume": delta,
                }
            )
    if quotes:
        post("/v1/quotes", {"items": quotes})
    if trades:
        post("/v1/trades", {"items": trades})


def ohlc_trades(exchange: str, code: str, ts: int, bar: dict) -> list[dict]:
    prices = [bar["open"], bar["high"], bar["low"], bar["close"]]
    volume = int(float(bar["volume"]))
    out = []
    for i, price in enumerate(prices):
        out.append(
            {
                "exchange": exchange,
                "code": code.zfill(6) if code.isdigit() else code,
                "ts_ns": ts + i * 1_000_000,
                "price": scale(price),
                "volume": volume if i == 3 else 0,
            }
        )
    return out


def sina_klines(code: str, scale_min: int, limit: int) -> list[dict]:
    r = requests.get(
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData",
        params={"symbol": sina_symbol(code), "scale": scale_min, "ma": "no", "datalen": limit},
        headers=UA,
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []
    return [
        {
            "day": str(item.get("day") or ""),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "close": item.get("close"),
            "volume": item.get("volume") or 0,
        }
        for item in data
        if item.get("day")
    ]


def parse_sina(body: str) -> list[dict]:
    rows = []
    for line in body.splitlines():
        if "hq_str_" not in line or '="' not in line:
            continue
        head, _, rest = line.partition("hq_str_")
        sym, _, quoted = rest.partition("=")
        sym = sym.strip()
        if sym.startswith("sh"):
            exchange, code = "SSE", sym[2:8]
        elif sym.startswith("sz"):
            exchange, code = "SZSE", sym[2:8]
        else:
            continue
        payload = quoted.split('"')[1] if '"' in quoted else ""
        parts = payload.split(",")
        if len(parts) < 10 or not parts[3]:
            continue
        rows.append(
            {
                "exchange": exchange,
                "code": code,
                "name": parts[0],
                "open": num(parts[1]),
                "pre_close": num(parts[2]),
                "price": num(parts[3]),
                "high": num(parts[4]),
                "low": num(parts[5]),
                "volume": num(parts[8]),
                "amount": num(parts[9]),
            }
        )
    return rows


def get_klines(symbol: str, period: str) -> list[dict]:
    return qdb.klines(symbol, period)


def post(path: str, body: dict) -> None:
    """兼容 markets / binance_ws：path 如 /v1/quotes。"""
    qdb.post_json(path, body)


def sina_symbol(code: str) -> str:
    code = "".join(ch for ch in code if ch.isdigit())[-6:].zfill(6)
    return ("sh" if code.startswith(("5", "6", "9")) else "sz") + code


def split_symbol(code: str) -> tuple[str, str]:
    code = "".join(ch for ch in code if ch.isdigit())[-6:].zfill(6)
    exchange = "SSE" if code.startswith(("5", "6", "9")) else "SZSE"
    return exchange, code


def bar_ts(day: str) -> int:
    raw = day.strip().replace("T", " ")
    fmt = "%Y-%m-%d %H:%M:%S" if " " in raw else "%Y-%m-%d"
    dt = datetime.strptime(raw[:19] if " " in raw else raw[:10], fmt).replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1_000_000_000)


def scale(value) -> int:
    return qdb_scale(value)


def num(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    main()
