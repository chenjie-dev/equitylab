"""采集公开行情并写入 qdb。本进程是唯一回源方；读路径只查 qdb。"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import requests

QDB = os.environ.get("QDB_URL", "http://qdb:9090").rstrip("/")
CODES = os.environ.get(
    "COLLECTOR_CODES",
    "600519,000001,300750,601318,000858,002594,600036,601012,688981,510300",
)
INTERVAL = float(os.environ.get("COLLECTOR_INTERVAL_MS", "1000")) / 1000
SCALE = 10_000
UA = {"User-Agent": "equitylab-collector", "Referer": "https://finance.sina.com.cn"}


def main() -> None:
    codes = [c.strip() for c in CODES.split(",") if c.strip()]
    wait_qdb()
    print(f"collector backfill {len(codes)} symbols", flush=True)
    for code in codes:
        try:
            backfill(code)
        except Exception as exc:
            print(f"backfill {code} failed: {exc}", flush=True)
    import markets

    try:
        markets.backfill_markets()
    except Exception as exc:
        print(f"market backfill failed: {exc}", flush=True)
    last_vol: dict[str, int] = {}
    cycle = 0
    while True:
        try:
            poll_quotes(codes, last_vol)
            markets.poll_markets(cycle)
        except Exception as exc:
            print(f"poll failed: {exc}", flush=True)
        cycle += 1
        time.sleep(INTERVAL)


def wait_qdb() -> None:
    for _ in range(60):
        try:
            r = requests.get(f"{QDB}/v1/snapshots", timeout=2)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
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
    r = requests.get(f"{QDB}/v1/klines", params={"symbol": symbol, "period": period}, timeout=10)
    if r.status_code == 404:
        return []
    r.raise_for_status()
    return list(r.json().get("data") or [])


def post(path: str, body: dict) -> None:
    r = requests.post(f"{QDB}{path}", json=body, timeout=120)
    r.raise_for_status()


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
    return int(round(float(value) * SCALE))


def num(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


if __name__ == "__main__":
    main()
