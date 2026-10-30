"""采集公开行情并写入 qdb。本进程是唯一回源方；读路径只查 qdb。"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime

import requests
from equitylab_qdb import Client, scale as qdb_scale
from equitylab_qdb import PRICE_SCALE as SCALE

import cn_equity_universe as cn_u

# 默认与 research `_SEED_CODES` / 前端 PRIORITY 对齐（沪深北 + ETF）；
# 全市场：CN_EQUITY_UNIVERSE=full（默认）拉新浪 hs_a → docs cn-equity:codes，报价 round-robin。
INTERVAL = float(os.environ.get("COLLECTOR_INTERVAL_MS", "500")) / 1000
UA = {"User-Agent": "equitylab-collector", "Referer": "https://finance.sina.com.cn"}
# 进程级 qdb 客户端（读写）；写纪律：仅本进程回源
qdb = Client(timeout=30.0)

# 主流指数（与前端 index-strip 对齐）；须带交易所，避免 000001→平安银行
INDEX_SEED: list[tuple[str, str]] = [
    ("SSE", "000001"),
    ("SZSE", "399001"),
    ("SZSE", "399006"),
    ("SSE", "000300"),
    ("SSE", "000016"),
    ("SSE", "000852"),
]


def _env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def main() -> None:
    import prom_metrics as pm

    pm.start_metrics_server()
    pm.heartbeat_loop()

    seed = cn_u.seed_codes_from_env()
    wait_qdb()
    # 单写者门闸：高优先现货/A 股，低优先 RWA，避免并发单条 POST 饿死 snapshots
    from write_gate import start_gate

    start_gate(_post_raw)
    skip_cn_equity = _env_flag("COLLECTOR_SKIP_CN_EQUITY", "0")
    pm.set_skip(skip_cn_equity)

    kline_codes: list[str] = list(seed)
    rotator: cn_u.QuoteRotator | None = None
    codes: list[str] = list(seed)

    if not skip_cn_equity:
        print(
            f"collector cn_equity universe mode={cn_u.universe_mode()} "
            f"seed={len(seed)} batch={cn_u.quote_batch_size()} "
            f"(resolving…)",
            flush=True,
        )
        rows, doc = cn_u.resolve_universe(seed=seed)
        codes = [r["code"] for r in rows]
        kline_codes = list(doc.get("kline_codes") or seed)
        post("/v1/docs", {"items": cn_u.codes_doc_items(doc)})
        rotator = cn_u.QuoteRotator(codes, seed=seed)
        pm.set_universe(len(codes))
        # 每批实际旋转量 ≈ min(batch, 100-热门seed)；估算全表一轮滞后
        rotate_n = max(1, len(codes) - len(seed))
        seed_slots = cn_u.quote_seed_prepend_n()
        per_tick = max(
            1,
            min(cn_u.quote_batch_size(), cn_u.SINA_HQ_BATCH_MAX - seed_slots),
        )
        lag_s = (rotate_n / per_tick) * INTERVAL if codes else 0.0
        pm.set_full_cycle_seconds(lag_s)
        print(
            f"collector cn_equity catalog count={doc['count']} source={doc['source']} "
            f"kline_backfill={len(kline_codes)} quote_full_cycle_s≈{lag_s:.0f} "
            f"doc={cn_u.CODES_DOC_KEY}",
            flush=True,
        )
        threading.Thread(
            target=_universe_refresh_worker,
            args=(seed, rotator),
            name="collector-cn-equity-universe",
            daemon=True,
        ).start()
    else:
        pm.set_full_cycle_seconds(0.0)
        pm.set_universe(0)

    pm.start_freshness_worker(seed, cn_equity_exchange)

    # 币安：WS 推送写 qdb；A 股 REST 热路径（分批）；盘口/RWA/回填后台。
    print(
        f"collector cadence interval_ms={int(INTERVAL * 1000)} "
        f"cn_equity={'skip' if skip_cn_equity else len(codes)} "
        f"(binance=ws→qdb; cn_equity={'off' if skip_cn_equity else 'rest batched'})",
        flush=True,
    )
    import markets

    # A 股 seed 回填独占 qdb 写路径；现货 WS / RWA 并行会把 write_gate 打满，
    # 导致 backfill Read timeout、live poll 起不来。全部放到回填完成后再启动。
    # A 股历史回填必须在首轮 live poll 之前完成：qdb 对「早于当前未闭合桶」的
    # 成交记 late_tick，不进 K 线。全宇宙时默认只回填 seed（CN_EQUITY_KLINE_CODES）。
    # 粗填沪深北工作日日历（节假日由日线再确认）
    try:
        from equitylab_market import pg as pg_market

        if pg_market.enabled():
            for ex in ("SSE", "SZSE", "BSE"):
                n = pg_market.seed_calendar_weekdays(ex)
                print(f"pg_market calendar seed {ex} rows≈{n}", flush=True)
    except Exception as exc:
        print(f"pg_market calendar seed failed: {exc}", flush=True)

    if not skip_cn_equity and kline_codes:
        print(
            f"collector cn_equity backfill {len(kline_codes)} symbols "
            f"(blocking before live poll; full-universe klines deferred)",
            flush=True,
        )
        for code in kline_codes:
            try:
                backfill(code)
            except Exception as exc:
                print(f"backfill {code} failed: {exc}", flush=True)
        print("collector cn_equity backfill done", flush=True)
        print(
            f"collector index backfill {len(INDEX_SEED)} symbols",
            flush=True,
        )
        for ex, code in INDEX_SEED:
            try:
                backfill_ex(ex, code)
            except Exception as exc:
                print(f"backfill index {ex}:{code} failed: {exc}", flush=True)
        print("collector index backfill done", flush=True)
        # 回填后再立刻刷一轮 seed 报价，列表首屏不必等完整 round-robin
        try:
            from volume_anchor import VolumeState

            prime_vol: dict[str, VolumeState] = {}
            poll_quotes(list(kline_codes), prime_vol)
            print(
                f"collector cn_equity prime quotes n={len(kline_codes)}",
                flush=True,
            )
        except Exception as exc:
            print(f"collector cn_equity prime quotes failed: {exc}", flush=True)
    else:
        print("collector cn_equity backfill skipped (COLLECTOR_SKIP_CN_EQUITY)", flush=True)

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

    # 成交量锚点：带 trade_date + trading_calendar（见 volume_anchor / session_calendar）
    from volume_anchor import VolumeState
    import session_calendar as sess_cal

    sess_cal.refresh(force=True)
    last_vol: dict[str, VolumeState] = {}
    cycle = 0
    while True:
        t0 = time.monotonic()
        session_day = sess_cal.is_cn_session_day()
        if not skip_cn_equity and rotator is not None:
            try:
                batch = rotator.next_batch()
                poll_quotes(batch, last_vol)
            except Exception as exc:
                print(f"cn_equity poll failed: {exc}", flush=True)
                pm.inc_qdb_error()
            try:
                poll_index_quotes(last_vol)
            except Exception as exc:
                print(f"cn_equity index poll failed: {exc}", flush=True)
                pm.inc_qdb_error()
        # WS 健康时 noop；断流才 REST 兜底
        try:
            markets.poll_quotes_hot()
        except Exception as exc:
            print(f"binance rest fallback failed: {exc}", flush=True)
        poll_s = time.monotonic() - t0
        pm.observe_poll(poll_s)
        ws_ok = False
        try:
            ws_ok = markets.binance_ws_healthy()
        except Exception:
            pass
        pm.set_binance_ws(ws_ok)
        if rotator is not None:
            pm.set_universe(len(rotator.codes))
        if cycle % 60 == 0:
            elapsed_ms = int(poll_s * 1000)
            n = len(rotator.codes) if rotator else 0
            print(
                f"collector tick cycle={cycle} cn_equity_ms={elapsed_ms} "
                f"cn_equity_n={n} session_day={session_day} "
                f"binance_ws={'up' if ws_ok else 'down'}",
                flush=True,
            )
        cycle += 1
        sleep_for = sess_cal.poll_interval_sec(INTERVAL)
        remain = sleep_for - (time.monotonic() - t0)
        if remain > 0:
            time.sleep(remain)


def _universe_refresh_worker(seed: list[str], rotator: cn_u.QuoteRotator) -> None:
    """定期重拉 hs_a，刷新 cn-equity:codes 与内存 rotator（默认 6h）。"""
    while True:
        time.sleep(cn_u.universe_refresh_sec())
        if cn_u.universe_mode() != "full":
            continue
        try:
            rows, doc = cn_u.resolve_universe(seed=seed)
            post("/v1/docs", {"items": cn_u.codes_doc_items(doc)})
            rotator.set_codes([r["code"] for r in rows], seed=seed)
            print(
                f"cn_equity universe refreshed count={doc['count']} source={doc['source']}",
                flush=True,
            )
        except Exception as exc:
            print(f"cn_equity universe refresh failed: {exc}", flush=True)


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
    exchange, code6 = split_symbol(code)
    backfill_ex(exchange, code6)


def backfill_ex(exchange: str, code: str) -> None:
    """按交易所回填 K 线（指数用 SSE:000001，勿走个股前缀）。

    启动期只灌最近若干棒进 qdb（防 /v1/trades 120s 卡住拖死 live poll）；
    冷库日线/分钟仍尽量写满 Postgres。
    """
    from retention import cutoff_ns

    from equitylab_market import pg as pg_market
    from equitylab_market.sina import klines as sina_klines_pkg

    code6 = _cn_code6(code)
    symbol = f"{exchange}:{code6}"
    qdb_bar_cap = max(16, int(os.environ.get("COLLECTOR_BACKFILL_QDB_BARS", "48")))
    post_timeout = max(5.0, float(os.environ.get("COLLECTOR_BACKFILL_POST_TIMEOUT", "20")))
    try:
        have_5m = {int(row["ts"]) for row in get_klines(symbol, "5m", limit=500)}
        have_1d = {int(row["ts"]) for row in get_klines(symbol, "1d", limit=400)}
    except Exception as exc:
        print(f"backfill {symbol} klines probe failed: {exc}", flush=True)
        have_5m, have_1d = set(), set()
    minute = sina_klines_pkg(code6, scale_min=5, limit=500, exchange=exchange)
    daily = sina_klines_pkg(code6, scale_min=240, limit=300, exchange=exchange)
    # 历史棒同时落 Postgres market.*（冷库）；失败不阻断 qdb 回填
    try:
        stats = pg_market.ingest_sina_klines(
            exchange, code6, daily=daily, minute=minute, minute_period="5m"
        )
        if stats["daily"] or stats["minute"]:
            print(
                f"pg_market {symbol} daily={stats['daily']} minute={stats['minute']}",
                flush=True,
            )
    except Exception as exc:
        print(f"pg_market {symbol} failed: {exc}", flush=True)
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
    # 默认不把历史 trades 灌进 qdb：冷启动大批量 /v1/trades 易把引擎拖死，
    # live poll 起不来 → 列表长期无现价。冷库已在 PG；K 线可由盘中成交再长。
    # 需要种子 K 线时设 COLLECTOR_BACKFILL_QDB_TRADES=1。
    write_qdb_trades = _env_flag("COLLECTOR_BACKFILL_QDB_TRADES", "0")
    if not write_qdb_trades:
        return
    if len(events) > qdb_bar_cap:
        events = events[-qdb_bar_cap:]
    trades: list[dict] = []
    for ts, bar, _kind in events:
        trades.extend(ohlc_trades(exchange, code6, ts, bar))
    if trades:
        # 直写 qdb；短超时，单批失败即停本票，不拖全表
        batch = 128
        written = 0
        for i in range(0, len(trades), batch):
            chunk = trades[i : i + batch]
            try:
                qdb.post_json("/v1/trades", {"items": chunk}, timeout=post_timeout)
                written += len(chunk)
            except Exception as exc:
                print(
                    f"backfill {symbol} trades batch failed "
                    f"written={written}/{len(trades)}: {exc}",
                    flush=True,
                )
                break
        print(f"backfill {symbol} trades={written}/{len(trades)}", flush=True)


def poll_index_quotes(last_vol: dict) -> None:
    """主流指数报价 → qdb（sh000001 等；与个股 000001 分交易所）。"""
    from equitylab_market.sina import sina_symbol_ex

    symbols = ",".join(sina_symbol_ex(ex, code) for ex, code in INDEX_SEED)
    text = requests.get(
        f"https://hq.sinajs.cn/list={symbols}", headers=UA, timeout=8
    ).content.decode("gb18030", "replace")
    _ingest_sina_hq(parse_sina(text), last_vol, vol_key_prefix="idx:")


def poll_quotes(codes: list[str], last_vol: dict) -> None:
    symbols = ",".join(sina_symbol(c) for c in codes)
    text = requests.get(f"https://hq.sinajs.cn/list={symbols}", headers=UA, timeout=8).content.decode("gb18030", "replace")
    _ingest_sina_hq(parse_sina(text), last_vol)


def _shanghai_clock_date() -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    except Exception:
        return time.strftime("%Y-%m-%d", time.localtime())


def _ingest_sina_hq(
    rows: list[dict],
    last_vol: dict,
    *,
    vol_key_prefix: str = "",
) -> None:
    """把 parse_sina 行写入 quotes / trades / depth docs。

    trades：volume_anchor + trading_calendar；非交易日不写 trades（quotes/docs 仍更新）。
    """
    from volume_anchor import next_volume_anchor
    import session_calendar as sess_cal

    quotes = []
    trades = []
    depth_docs: list[dict] = []
    now_ns = int(time.time() * 1_000_000_000)
    clock_date = _shanghai_clock_date()
    session_day = sess_cal.is_cn_session_day(clock_date)
    for row in rows:
        px = float(row.get("price") or 0)
        pre = float(row.get("pre_close") or 0)
        # 新浪停牌/退市常见全 0；写入会盖掉旧好价且列表显示 0.00
        if px <= 0:
            if pre <= 0:
                continue
            px = pre
        quotes.append(
            {
                "exchange": row["exchange"],
                "code": row["code"],
                "ts_ns": now_ns,
                "last": scale(px),
                # qdb QuoteIn：bid_px/ask_px 为 scale 整数（第 1 档）
                "bid_px": scale(row["bid"]) if row.get("bid") else 0,
                "ask_px": scale(row["ask"]) if row.get("ask") else 0,
                "name": row["name"],
                "open": row["open"] or px,
                "high": row["high"] or px,
                "low": row["low"] or px,
                "pre_close": pre or px,
                "price": px,
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
                    "key": f"cn-equity:depth:{symbol}",
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
        vol_key = f"{vol_key_prefix}{row['exchange']}:{row['code']}"
        state, delta, _reason = next_volume_anchor(
            last_vol.get(vol_key),
            vol,
            trade_date=row.get("trade_date"),
            clock_date=clock_date,
            is_trading_day=session_day,
        )
        last_vol[vol_key] = state
        # 休市日禁止 trades 进 qdb（防假 5m）；quotes 仍刷最新价
        if session_day and delta > 0:
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
    # 名称含「停牌」时记一条当日 suspend（冷库）
    try:
        from equitylab_market import pg as pg_market

        if pg_market.enabled():
            for row in rows:
                pg_market.maybe_mark_suspend_from_quote(
                    row["exchange"],
                    row["code"],
                    name=str(row.get("name") or ""),
                    volume=row.get("volume"),
                    price=row.get("price"),
                )
    except Exception:
        pass


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
    from equitylab_market.sina import klines

    return klines(code, scale_min=scale_min, limit=limit, timeout=20.0)


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
        # 新浪字段：30=日期 YYYY-MM-DD，31=时间 HH:MM:SS（累计量所属交易日）
        trade_date = ""
        trade_time = ""
        if len(parts) > 30 and parts[30]:
            raw_d = parts[30].strip().replace("/", "-")
            if len(raw_d) >= 10:
                trade_date = raw_d[:10]
        if len(parts) > 31 and parts[31]:
            trade_time = parts[31].strip()
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
                "trade_date": trade_date,
                "trade_time": trade_time,
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
    try:
        qdb.post_json(path, body)
    except Exception:
        try:
            import prom_metrics as pm

            pm.inc_qdb_error()
        except Exception:
            pass
        raise


def post(path: str, body: dict, *, priority: str = "high") -> None:
    """兼容 markets / binance_ws：path 如 /v1/quotes。

    priority=high：币安 WS / A 股（snapshots 热路径）。
    priority=low：RWA 扫盘（可合并、可被高优先插队）。
    """
    from write_gate import get_gate

    gate = get_gate()
    if gate is None:
        _post_raw(path, body)
        _record_quotes_metric(path, body)
        return
    if priority == "sync":
        gate.post_sync(path, body)
        _record_quotes_metric(path, body)
        return
    gate.enqueue(path, body, priority="low" if priority == "low" else "high")
    _record_quotes_metric(path, body)


def _record_quotes_metric(path: str, body: dict) -> None:
    if not path.endswith("/quotes"):
        return
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items:
        return
    try:
        import prom_metrics as pm

        pm.record_quotes(items)
    except Exception:
        pass


def _cn_code6(raw: str) -> str:
    from equitylab_market.symbols import code6

    return code6(raw) or "000000"


def cn_equity_exchange(code: str) -> str:
    """6 位 A 股码 → qdb 交易所标签（委托 equitylab_market.symbols）。"""
    from equitylab_market.symbols import cn_equity_exchange as _ex

    return _ex(code)


def sina_symbol(code: str) -> str:
    from equitylab_market.sina import sina_symbol as _sina_symbol

    return _sina_symbol(code)


def split_symbol(code: str) -> tuple[str, str]:
    from equitylab_market.symbols import cn_equity_exchange, code6

    c = code6(code) or "000000"
    return cn_equity_exchange(c), c


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
