"""采集公开行情并写入 qdb。本进程是唯一回源方；读路径只查 qdb。"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime

import requests
from equitylab_qdb import Client, scale as qdb_scale
from equitylab_qdb import PRICE_SCALE as SCALE

# 默认与 research `_SEED_CODES` / 前端 PRIORITY 对齐（沪深北 + ETF）；
# 扩大列表：设 QDB_FEED_CODES 或 COLLECTOR_CODES（Compose 透传前者）。
_DEFAULT_ASHARE_CODES = (
    "600519,000001,300750,601318,000858,002594,600036,601012,688981,510300,"
    "830879,835185,000568,600900,601899,300059,002475,600276,000333,601166,"
    "600030,002415"
)
CODES = os.environ.get("COLLECTOR_CODES", _DEFAULT_ASHARE_CODES)
INTERVAL = float(os.environ.get("COLLECTOR_INTERVAL_MS", "500")) / 1000
UA = {"User-Agent": "equitylab-collector", "Referer": "https://finance.sina.com.cn"}
# 进程级 qdb 客户端（读写）；写纪律：仅本进程回源
qdb = Client(timeout=30.0)


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def main() -> None:
    codes = [c.strip() for c in CODES.split(",") if c.strip()]
    wait_qdb()
    # 单写者门闸：高优先现货/A 股，低优先 RWA，避免并发单条 POST 饿死 snapshots
    from write_gate import start_gate

    start_gate(_post_raw)
    skip_ashare = _env_flag("COLLECTOR_SKIP_ASHARE", "0")
    # 币安：WS 推送写 qdb；A 股仍 REST 热路径；盘口/RWA/回填后台。
    print(
        f"collector cadence interval_ms={int(INTERVAL * 1000)} "
        f"ashare={'skip' if skip_ashare else len(codes)} "
        f"(binance=ws→qdb; ashare={'off' if skip_ashare else 'rest hot-path'})",
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
    try:
        markets.start_retention_gc()
    except Exception as exc:
        print(f"retention gc start failed: {exc}", flush=True)

    # A 股历史回填必须在首轮 live poll 之前完成：qdb 对「早于当前未闭合桶」的
    # 成交记 late_tick，不进 K 线。若先 poll 再 backfill，日/分钟历史会永久空洞。
    if not skip_ashare and codes:
        print(
            f"collector ashare backfill {len(codes)} symbols (blocking before live poll)",
            flush=True,
        )
        for code in codes:
            try:
                backfill(code)
            except Exception as exc:
                print(f"backfill {code} failed: {exc}", flush=True)
        print("collector ashare backfill done", flush=True)
    else:
        print("collector ashare backfill skipped (COLLECTOR_SKIP_ASHARE)", flush=True)

    threading.Thread(
        target=_market_backfill_worker,
        args=(markets,),
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
        if not skip_ashare and codes:
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


def _market_backfill_worker(markets: object) -> None:
    try:
        markets.backfill_markets()  # type: ignore[attr-defined]
    except Exception as exc:
        print(f"market backfill failed: {exc}", flush=True)
    print("collector market backfill done", flush=True)


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
    from retention import cutoff_ns

    exchange, _ = split_symbol(code)
    symbol = f"{exchange}:{code.zfill(6)}"
    have_5m = {int(row["ts"]) for row in get_klines(symbol, "5m")}
    have_1d = {int(row["ts"]) for row in get_klines(symbol, "1d")}
    minute = sina_klines(code, 5, 500)
    daily = sina_klines(code, 240, 300)
    covered = {bar["day"][:10] for bar in minute}
    cut = cutoff_ns()
    events: list[tuple[int, dict, str]] = []
    for bar in daily:
        day = bar["day"][:10]
        if day in covered:
            continue
        ts = bar_ts(day)
        if ts < cut or ts in have_1d:
            continue
        events.append((ts, bar, "1d"))
    for bar in minute:
        ts = bar_ts(bar["day"])
        if ts < cut or ts in have_5m:
            continue
        events.append((ts, bar, "5m"))
    events.sort(key=lambda item: item[0])
    trades: list[dict] = []
    for ts, bar, _kind in events:
        trades.extend(ohlc_trades(exchange, code, ts, bar))
    if trades:
        # 启动期尚无 live poll：直写 qdb，避免与币安高优先队列抢、并保证先于未闭合桶落盘
        batch = 256
        for i in range(0, len(trades), batch):
            _post_raw("/v1/trades", {"items": trades[i : i + batch]})
        print(f"backfill {symbol} trades={len(trades)}", flush=True)


def poll_quotes(codes: list[str], last_vol: dict[str, int]) -> None:
    symbols = ",".join(sina_symbol(c) for c in codes)
    text = requests.get(f"https://hq.sinajs.cn/list={symbols}", headers=UA, timeout=8).content.decode("gb18030", "replace")
    quotes = []
    trades = []
    depth_docs: list[dict] = []
    now_ns = int(time.time() * 1_000_000_000)
    for row in parse_sina(text):
        quotes.append(
            {
                "exchange": row["exchange"],
                "code": row["code"],
                "ts_ns": now_ns,
                "last": scale(row["price"]),
                # qdb QuoteIn：bid_px/ask_px 为 scale 整数（第 1 档）
                "bid_px": scale(row["bid"]) if row.get("bid") else 0,
                "ask_px": scale(row["ask"]) if row.get("ask") else 0,
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
        # 五档进 docs（引擎 quotes 只落买一/卖一）；读路径经 GET /v1/docs
        bids = row.get("bids") or []
        asks = row.get("asks") or []
        if bids or asks:
            symbol = f"{row['exchange']}:{row['code']}"
            depth_docs.append(
                {
                    "key": f"ashare:depth:{symbol}",
                    "value": {
                        "symbol": symbol,
                        "bids": bids,
                        "asks": asks,
                        "ts_ns": now_ns,
                        "source": "sina",
                    },
                }
            )
        vol = int(row["volume"])
        prev = last_vol.get(row["code"])
        # 首见只记量、不写 trade，避免把「当日累计成交量」整笔打进当前 5m 桶
        if prev is None:
            last_vol[row["code"]] = vol
        else:
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
    if depth_docs:
        post("/v1/docs", {"items": depth_docs})


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
        elif sym.startswith("bj"):
            # 北交所：新浪 hq_str_bj830879 / bj920088 → qdb BSE:6 位码
            exchange, code = "BSE", sym[2:8]
        else:
            continue
        payload = quoted.split('"')[1] if '"' in quoted else ""
        parts = payload.split(",")
        if len(parts) < 10 or not parts[3]:
            continue
        # 新浪：10–19 买一～买五（量/价交替）；20–29 卖一～卖五
        # 6/7 为竞买卖价；缺档时回落
        bids = _sina_levels(parts, start=10)
        asks = _sina_levels(parts, start=20)
        bid = bids[0]["price"] if bids else (
            num(parts[6]) if len(parts) > 6 else None
        )
        ask = asks[0]["price"] if asks else (
            num(parts[7]) if len(parts) > 7 else None
        )
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
                "bid": bid,
                "ask": ask,
                "bids": bids,
                "asks": asks,
                "volume": num(parts[8]),
                "amount": num(parts[9]),
            }
        )
    return rows


def _sina_levels(parts: list[str], *, start: int) -> list[dict]:
    """解析新浪五档：start 起连续 5 组 (量, 价)。"""
    out: list[dict] = []
    for i in range(5):
        vol_i = start + i * 2
        px_i = start + i * 2 + 1
        if px_i >= len(parts):
            break
        px = num(parts[px_i]) if parts[px_i] else None
        vol = num(parts[vol_i]) if vol_i < len(parts) and parts[vol_i] else None
        if px is None or px <= 0:
            continue
        out.append({"price": px, "volume": vol or 0})
    return out


def get_klines(symbol: str, period: str, *, limit: int = 5000) -> list[dict]:
    """回填去重用；默认窗口对齐 qdb `limit` 上限 5000。"""
    return qdb.klines(symbol, period, limit=limit)


def _post_raw(path: str, body: dict) -> None:
    """直连 qdb（仅 write_gate 刷盘线程调用）。"""
    qdb.post_json(path, body)


def post(path: str, body: dict, *, priority: str = "high") -> None:
    """兼容 markets / binance_ws：path 如 /v1/quotes。

    priority=high：币安 WS / A 股（snapshots 热路径）。
    priority=low：RWA 扫盘（可合并、可被高优先插队）。
    """
    from write_gate import get_gate

    gate = get_gate()
    if gate is None:
        _post_raw(path, body)
        return
    if priority == "sync":
        gate.post_sync(path, body)
        return
    gate.enqueue(path, body, priority="low" if priority == "low" else "high")


def _ashare_code6(raw: str) -> str:
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    return digits[-6:].zfill(6) if digits else "000000"


def ashare_exchange(code: str) -> str:
    """6 位 A 股码 → qdb 交易所标签。

    北交所优先：4/8 开头（原新三板精选层等）或 92xxxx（北交所新号段）。
    须先于「9→SSE」判断，否则 920088 会被误标为沪市。
    """
    code = _ashare_code6(code)
    if code.startswith(("4", "8")) or code.startswith("92"):
        return "BSE"
    if code.startswith(("5", "6", "9")):
        return "SSE"
    return "SZSE"


def sina_symbol(code: str) -> str:
    code = _ashare_code6(code)
    prefix = {"SSE": "sh", "SZSE": "sz", "BSE": "bj"}[ashare_exchange(code)]
    return prefix + code


def split_symbol(code: str) -> tuple[str, str]:
    code = _ashare_code6(code)
    return ashare_exchange(code), code


def bar_ts(day: str) -> int:
    """新浪 K 线时间为北京时间；写成绝对 ns（勿当 UTC，否则盘中桶错位 8h）。"""
    from zoneinfo import ZoneInfo

    raw = day.strip().replace("T", " ")
    fmt = "%Y-%m-%d %H:%M:%S" if " " in raw else "%Y-%m-%d"
    naive = datetime.strptime(raw[:19] if " " in raw else raw[:10], fmt)
    dt = naive.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
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
