"""币安现货与 Ondo 代币化美股：公开接口只在这里拉取，再写入 qdb。"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from main import get_klines, ohlc_trades, post, scale
from retention import (
    cutoff_ns,
    filter_binance_kline_rows,
    start_docs_gc,
    trim_rwa_kline_doc,
)

# 默认 vision：部分网络 api.binance.com 超时；Docker Desktop 直连 TLS 失败时用 COLLECTOR_HTTPS_PROXY
BINANCE = os.environ.get("BINANCE_REST_URL", "https://data-api.binance.vision").rstrip("/")
BINANCE_FALLBACK = os.environ.get(
    "BINANCE_REST_FALLBACK", "https://api.binance.com"
).rstrip("/")
RWA = os.environ.get("BINANCE_RWA_BASE_URL", "https://www.binance.com").rstrip("/")


def _proxy_from_env(*names: str) -> dict[str, str] | None:
    """宿主机 CONNECT 代理；勿设全局 HTTP_PROXY（会拖死新浪 A 股）。"""
    for name in names:
        raw = (os.environ.get(name) or "").strip()
        if raw:
            return {"http": raw, "https": raw}
    return None


def _upstream_proxies() -> dict[str, str] | None:
    """现货 REST（vision / api.binance）。"""
    return _proxy_from_env(
        "COLLECTOR_HTTPS_PROXY", "HTTPS_PROXY", "https_proxy"
    )


def _rwa_proxies() -> dict[str, str] | None:
    """RWA 走 www.binance.com；可与现货代理分离（如 Clash 7897 vs host-connect 18080）。"""
    return _proxy_from_env(
        "COLLECTOR_RWA_PROXY",
        "COLLECTOR_HTTPS_PROXY",
        "HTTPS_PROXY",
        "https_proxy",
    )
BINANCE_SYMBOLS = [
    s.strip().upper()
    for s in os.environ.get(
        "BINANCE_SYMBOLS",
        "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT,DOGEUSDT,ADAUSDT,AVAXUSDT,DOTUSDT,LINKUSDT,POLUSDT,LTCUSDT,NEARUSDT,UNIUSDT,ATOMUSDT,APTUSDT",
    ).split(",")
    if s.strip()
]
RWA_TICKERS = [
    s.strip().upper()
    for s in os.environ.get(
        "RWA_TICKERS",
        "AAPL,NVDA,TSLA,MSFT,AMZN,GOOGL,META,SPY,QQQ,AMD,NFLX,COIN,MSTR,PLTR,BABA",
    ).split(",")
    if s.strip()
]
_RWA_LIST = "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/rwa/stock/detail/list/ai"
_RWA_STATUS = "/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/rwa/market/status/ai"
_RWA_DYNAMIC = "/bapi/defi/v2/public/wallet-direct/buw/wallet/market/token/rwa/dynamic/ai"
_RWA_KLINE = "/bapi/defi/v1/public/wallet-direct/buw/wallet/dex/market/token/kline/ai"
# 全市场并行扫盘；前端只读聚合 doc `rwa:board`。设 0 可停（www.binance.com 不可达时）
# 默认降并发：扫盘并行拉上游，但 qdb 写入经 write_gate 低优先合并
RWA_WORKERS = max(0, int(os.environ.get("RWA_WORKERS", "8")))
RWA_CHUNK = max(8, int(os.environ.get("RWA_CHUNK", "32")))
# K 线：全市场持续写 `rwa:kline:{TICKER}:{interval}`，读路径优先此 doc
RWA_KLINE_WORKERS = max(0, int(os.environ.get("RWA_KLINE_WORKERS", "4")))
RWA_KLINE_CHUNK = max(4, int(os.environ.get("RWA_KLINE_CHUNK", "16")))
# rwa:board 全量覆盖写节流（秒）；避免每 chunk 重写巨大 JSON 饿死现货
RWA_BOARD_FLUSH_SEC = max(0.2, float(os.environ.get("RWA_BOARD_FLUSH_SEC", "1.5")))
# 仅热门 ticker 写引擎 /v1/quotes（snapshots）；冷门只落 board/docs
RWA_ENGINE_QUOTES_HOT_ONLY = os.environ.get(
    "RWA_ENGINE_QUOTES_HOT_ONLY", "1"
).strip().lower() not in ("0", "false", "no", "off")
RWA_KLINE_INTERVALS = [
    s.strip()
    for s in os.environ.get(
        "RWA_KLINE_INTERVALS", "1h,1d,15m,5m,4h,1m,12h"
    ).split(",")
    if s.strip()
]
# 现货 K 线：WS 不订 kline；须 REST 持续补齐（读路径 map 到这些 period）
_kline_iv_raw = os.environ.get("BINANCE_KLINE_INTERVALS", "1m,5m,15m,1h,4h,1d").strip()
BINANCE_KLINE_INTERVALS = (
    []
    if _kline_iv_raw.lower() in ("", "0", "off", "none", "-")
    else [s.strip() for s in _kline_iv_raw.split(",") if s.strip()]
)
# docs / REST 只保留最近 N 根（硬顶），覆盖写入，禁止无限堆积
_BINANCE_KLINE_LIMIT_MAX = 500
BINANCE_KLINE_LIMIT = min(
    _BINANCE_KLINE_LIMIT_MAX,
    max(5, int(os.environ.get("BINANCE_KLINE_LIMIT", "180"))),
)
BINANCE_KLINE_REFRESH = max(2, int(os.environ.get("BINANCE_KLINE_REFRESH", "8")))
BINANCE_KLINE_PAUSE = float(os.environ.get("BINANCE_KLINE_PAUSE_SEC", "1.0"))
_RWA_KLINE_LIMIT_MAX = 300
RWA_KLINE_DOC_LIMIT = min(
    _RWA_KLINE_LIMIT_MAX,
    max(5, int(os.environ.get("RWA_KLINE_LIMIT", "200"))),
)
_BOARD: dict[str, dict[str, Any]] = {}
_BOARD_LOCK = threading.Lock()
_board_dirty = False
_last_board_flush_at = 0.0
_rwa_cursor = 0
_last_catalog_at = 0.0
_rwa_kline_cursor = 0
_rwa_kline_interval_i = 0
_binance_kline_i = 0
_HOT_TICKERS = {t.upper() for t in RWA_TICKERS}


def backfill_markets() -> None:
    # 启动全量回填会长时间占住 qdb engine（apply_trades+fsync），饿死 /v1/klines。
    # 持续刷新走 start_binance_kline_feed；缺历史时再显式开 BINANCE_KLINE_BACKFILL=1。
    do_backfill = os.environ.get("BINANCE_KLINE_BACKFILL", "0").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
        "",
    )
    if not BINANCE_KLINE_INTERVALS:
        print("binance kline backfill skipped (BINANCE_KLINE_INTERVALS=off)", flush=True)
    elif not do_backfill:
        print(
            "binance kline backfill skipped (BINANCE_KLINE_BACKFILL=0; feed still runs)",
            flush=True,
        )
    else:
        for symbol in BINANCE_SYMBOLS:
            try:
                _backfill_binance(symbol)
            except Exception as exc:
                print(f"binance backfill {symbol} failed: {exc}", flush=True)
    if RWA_WORKERS <= 0 and RWA_KLINE_WORKERS <= 0:
        print("rwa backfill skipped (RWA workers=0)", flush=True)
        return
    tokens = _rwa_tokens()
    _put_docs(
        [
            {
                "key": "rwa:stocks",
                "value": {
                    "code": "000000",
                    "success": True,
                    "count": len(tokens),
                    "data": tokens,
                },
            }
        ],
        priority="low",
    )
    # 热门先种 1h K 线；全市场由 start_rwa_kline_feed 持续补齐
    for token in tokens:
        ticker = str(token.get("ticker") or "").upper()
        if ticker not in RWA_TICKERS:
            continue
        try:
            _store_rwa_klines(token, "1h", limit=200, write_trades=True)
        except Exception as exc:
            print(f"rwa backfill {ticker} failed: {exc}", flush=True)


def start_binance_ws() -> None:
    """启动币安 combined stream（报价/盘口/成交 docs）；失败时 REST 兜底。"""
    from binance_ws import start_feed

    start_feed(BINANCE_SYMBOLS, post=post, scale=scale, put_docs=_put_docs)


def start_rwa_feed() -> None:
    """独立线程：全量 Ondo 美股持续扫盘写入 qdb（含聚合 board）。"""
    threading.Thread(target=_rwa_worker, name="collector-rwa", daemon=True).start()


def start_rwa_kline_feed() -> None:
    """独立线程：全市场各周期 K 线持续写入 `rwa:kline:*`。"""
    threading.Thread(target=_rwa_kline_worker, name="collector-rwa-kline", daemon=True).start()


def start_binance_kline_feed() -> None:
    """独立线程：现货 REST K 线持续写入 qdb（补 WS 不推 kline 的缺口）。"""
    if not BINANCE_SYMBOLS or not BINANCE_KLINE_INTERVALS:
        return
    threading.Thread(
        target=_binance_kline_worker, name="collector-binance-kline", daemon=True
    ).start()


def binance_ws_healthy() -> bool:
    from binance_ws import feed_healthy

    return feed_healthy()


def poll_quotes_hot() -> None:
    """热路径 REST 兜底：WS 健康时跳过，避免覆盖推送价。"""
    if binance_ws_healthy():
        return
    try:
        _poll_binance_tickers()
    except Exception as exc:
        print(f"binance tickers failed: {exc}", flush=True)


def poll_slow(cycle: int) -> None:
    """慢路径：WS 不健康时 REST 盘口（RWA 由 start_rwa_feed 独立线程负责）。"""
    if BINANCE_SYMBOLS and not binance_ws_healthy():
        symbol = BINANCE_SYMBOLS[cycle % len(BINANCE_SYMBOLS)]
        try:
            _poll_binance_book(symbol)
        except Exception as exc:
            print(f"binance book {symbol} failed: {exc}", flush=True)


def poll_markets(cycle: int) -> None:
    """兼容旧调用：热+慢同线程（优先用 poll_quotes_hot / poll_slow）。"""
    poll_quotes_hot()
    poll_slow(cycle)


def _backfill_binance(symbol: str) -> None:
    """首次回填各原生周期；之后由 start_binance_kline_feed 持续刷新。"""
    qsym = f"BINANCE:{symbol}"
    total = 0
    for interval in BINANCE_KLINE_INTERVALS:
        limit = 500 if interval in ("1m", "5m", "15m") else 300
        n = _store_binance_klines(symbol, interval, limit=limit, only_missing=True)
        total += n
    if total:
        print(f"backfill {qsym} trades={total}", flush=True)


def _binance_kline_worker() -> None:
    global _binance_kline_i
    n_sym = len(BINANCE_SYMBOLS)
    n_iv = len(BINANCE_KLINE_INTERVALS)
    print(
        f"binance kline feed symbols={n_sym} intervals={BINANCE_KLINE_INTERVALS} "
        f"limit={BINANCE_KLINE_LIMIT}",
        flush=True,
    )
    while True:
        if not n_sym or not n_iv:
            time.sleep(5.0)
            continue
        symbol = BINANCE_SYMBOLS[_binance_kline_i % n_sym]
        interval = BINANCE_KLINE_INTERVALS[(_binance_kline_i // n_sym) % n_iv]
        _binance_kline_i += 1
        try:
            n = _store_binance_klines(
                symbol,
                interval,
                limit=BINANCE_KLINE_LIMIT,
                only_missing=False,
                keep_last=BINANCE_KLINE_REFRESH,
            )
            if n and _binance_kline_i % 32 == 0:
                print(
                    f"binance kline refresh {symbol}:{interval} trades={n}",
                    flush=True,
                )
        except Exception as exc:
            print(f"binance kline {symbol}:{interval} failed: {exc}", flush=True)
        time.sleep(BINANCE_KLINE_PAUSE)


def _store_binance_klines(
    symbol: str,
    interval: str,
    *,
    limit: int,
    only_missing: bool,
    keep_last: int | None = None,
) -> int:
    """REST K 线 → docs（读路径主源）；可选再写 trades 喂引擎聚合。

    qdb 对早于当前桶的成交只进 ticks 不进 K 线（late-tick），水位已被 live
    推到「现在」后无法靠回补 trades 填历史。图表历史一律读 `binance:kline:*` docs。
    """
    qsym = f"BINANCE:{symbol}"
    retain = min(limit, BINANCE_KLINE_LIMIT, _BINANCE_KLINE_LIMIT_MAX)
    rows = _binance_klines(symbol, interval, retain)
    if not rows:
        return 0
    # 根数硬顶 + 15 天时间窗；整 key 覆盖，不与旧 doc 合并
    rows = filter_binance_kline_rows(rows[-retain:])
    if not rows:
        return 0
    _put_docs([{"key": f"binance:kline:{symbol}:{interval}", "value": {"data": rows}}])
    write_trades = os.environ.get("BINANCE_KLINE_WRITE_TRADES", "0").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
        "",
    )
    if not write_trades:
        return len(rows)
    trade_rows = rows
    if keep_last is not None and keep_last > 0:
        trade_rows = rows[-keep_last:]
    have: set[int] = set()
    if only_missing:
        have = {int(row["ts"]) for row in get_klines(qsym, interval)}
    cut = cutoff_ns()
    trades: list[dict] = []
    for row in trade_rows:
        ts = int(row[0]) * 1_000_000
        if ts < cut:
            continue
        if only_missing and ts in have:
            continue
        trades.extend(
            ohlc_trades(
                "BINANCE",
                symbol,
                ts,
                {
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5],
                },
            )
        )
    if not trades:
        return len(rows)
    # 小批次 + 间隙，避免 apply_trades+fsync 长时间占住 engine 饿死 /v1/klines
    batch = 64
    pause = float(os.environ.get("BINANCE_KLINE_WRITE_PAUSE_SEC", "0.15"))
    for i in range(0, len(trades), batch):
        post("/v1/trades", {"items": trades[i : i + batch]})
        if pause > 0 and i + batch < len(trades):
            time.sleep(pause)
    return len(trades)


def _binance_get(path: str, params: dict | None = None, timeout: int = 8) -> Any:
    """主站失败立刻换 fallback；短 timeout 避免 SSL 卡死整轮采集。"""
    bases = [BINANCE]
    if BINANCE_FALLBACK and BINANCE_FALLBACK != BINANCE:
        bases.append(BINANCE_FALLBACK)
    last_err: Exception | None = None
    for base in bases:
        try:
            r = requests.get(
                f"{base}{path}",
                params=params or {},
                timeout=timeout,
                proxies=_upstream_proxies(),
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last_err = exc
            continue
    assert last_err is not None
    raise last_err


def _poll_binance_tickers() -> None:
    import json

    rows: list[Any] = []
    try:
        data = _binance_get(
            "/api/v3/ticker/24hr",
            {"symbols": json.dumps(BINANCE_SYMBOLS, separators=(",", ":"))},
            timeout=5,
        )
        rows = [data] if isinstance(data, dict) else list(data or [])
    except Exception as batch_exc:
        print(f"binance batch ticker failed ({batch_exc}); per-symbol", flush=True)
        for symbol in BINANCE_SYMBOLS:
            try:
                one = _binance_get("/api/v3/ticker/24hr", {"symbol": symbol}, timeout=4)
                if isinstance(one, dict):
                    rows.append(one)
            except Exception as exc:
                print(f"binance ticker {symbol} failed: {exc}", flush=True)
    docs = []
    quotes = []
    now_ns = int(__import__("time").time() * 1_000_000_000)
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        docs.append({"key": f"binance:ticker:{symbol}", "value": row})
        price = float(row.get("lastPrice") or 0)
        quotes.append(
            {
                "exchange": "BINANCE",
                "code": symbol,
                "ts_ns": now_ns,
                "last": scale(price),
                "name": symbol,
                "open": float(row.get("openPrice") or 0),
                "high": float(row.get("highPrice") or 0),
                "low": float(row.get("lowPrice") or 0),
                "pre_close": float(row.get("prevClosePrice") or row.get("openPrice") or 0),
                "price": price,
                "volume": float(row.get("volume") or 0),
                "amount": float(row.get("quoteVolume") or 0),
            }
        )
    # REST 兜底：默认写 quotes；BINANCE_WS_WRITE_QUOTES=0 时只落 docs，避免饿死 /v1/klines
    write_quotes = os.environ.get("BINANCE_WS_WRITE_QUOTES", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if write_quotes and quotes:
        post("/v1/quotes", {"items": quotes})
    _put_docs(docs)


def _poll_binance_book(symbol: str) -> None:
    depth = _binance_get("/api/v3/depth", {"symbol": symbol, "limit": 20}, timeout=5)
    trades = _binance_get("/api/v3/trades", {"symbol": symbol, "limit": 50}, timeout=5)
    if isinstance(depth, dict):
        depth = {
            **depth,
            "bids": (depth.get("bids") or [])[:20],
            "asks": (depth.get("asks") or [])[:20],
        }
    if isinstance(trades, list) and len(trades) > 50:
        trades = trades[-50:]
    _put_docs(
        [
            {"key": f"binance:depth:{symbol}", "value": depth},
            {"key": f"binance:trades:{symbol}", "value": trades},
        ]
    )


def _rwa_priority_tokens(tokens: list[dict]) -> list[dict]:
    """热门 ticker 优先写 board/quote，避免全市场扫完才有 AAPL。"""
    want = {t.upper() for t in RWA_TICKERS}
    if not want:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for tok in tokens:
        ticker = str(tok.get("ticker") or "").upper()
        if ticker not in want or ticker in seen:
            continue
        if str(tok.get("chainId") or "") not in ("", "56"):
            continue
        out.append(tok)
        seen.add(ticker)
    return out


def _rwa_store_chunk(chunk: list[dict]) -> tuple[int, int]:
    """并行拉上游；docs/quotes 收齐后各打一批低优先写入（禁止每标的单条 POST）。"""
    ok = 0
    fail = 0
    if not chunk:
        return ok, fail
    docs: list[dict] = []
    quotes: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(RWA_WORKERS, len(chunk))) as pool:
        futs = {
            pool.submit(_fetch_dynamic, tok): str(tok.get("ticker") or "").upper()
            for tok in chunk
        }
        for fut in as_completed(futs):
            ticker = futs[fut]
            try:
                result = fut.result()
                if result is None:
                    continue
                d_items, q_item = result
                docs.extend(d_items)
                if q_item is not None:
                    quotes.append(q_item)
                ok += 1
            except Exception as exc:
                fail += 1
                print(f"rwa dynamic {ticker} failed: {exc}", flush=True)
    if docs:
        _put_docs(docs, priority="low")
    if quotes:
        post("/v1/quotes", {"items": quotes}, priority="low")
    return ok, fail


def _rwa_worker() -> None:
    global _rwa_cursor, _last_catalog_at
    if RWA_WORKERS <= 0:
        print("rwa feed disabled (RWA_WORKERS=0)", flush=True)
        return
    print(f"rwa feed start workers={RWA_WORKERS} chunk={RWA_CHUNK}", flush=True)
    _hydrate_board()
    passes = 0
    priority_done = False
    while True:
        t0 = time.monotonic()
        try:
            now = time.monotonic()
            if now - _last_catalog_at > 60.0:
                _refresh_rwa_catalog()
                _last_catalog_at = now
                priority_done = False
            tokens = _ensure_tokens()
            if not tokens:
                time.sleep(2.0)
                continue
            if not priority_done:
                hot = _rwa_priority_tokens(tokens)
                ok, fail = _rwa_store_chunk(hot)
                _flush_board(force=True)
                print(
                    f"rwa priority tickers={len(hot)} ok={ok} fail={fail} "
                    f"ms={int((time.monotonic() - t0) * 1000)}",
                    flush=True,
                )
                priority_done = True
                continue
            n = len(tokens)
            start = _rwa_cursor
            chunk = [tokens[(start + i) % n] for i in range(min(RWA_CHUNK, n))]
            _rwa_cursor = (start + len(chunk)) % n
            full_pass = len(chunk) >= n or (start + len(chunk)) >= n
            ok, fail = _rwa_store_chunk(chunk)
            _flush_board(force=full_pass)
            if full_pass:
                passes += 1
                with _BOARD_LOCK:
                    board_n = len(_BOARD)
                print(
                    f"rwa pass={passes} universe={n} board={board_n} "
                    f"chunk_ok={ok} chunk_fail={fail} "
                    f"ms={int((time.monotonic() - t0) * 1000)}",
                    flush=True,
                )
        except Exception as exc:
            print(f"rwa sweep failed: {exc}", flush=True)
            time.sleep(1.0)


def _refresh_rwa_catalog() -> None:
    try:
        status = requests.get(
            f"{RWA}{_RWA_STATUS}", timeout=30, proxies=_rwa_proxies()
        ).json()
        _put_docs([{"key": "rwa:status", "value": status}], priority="low")
        tokens = _rwa_tokens()
        _put_docs(
            [
                {
                    "key": "rwa:stocks",
                    "value": {
                        "code": "000000",
                        "success": True,
                        "count": len(tokens),
                        "data": tokens,
                    },
                }
            ],
            priority="low",
        )
    except Exception as exc:
        print(f"rwa catalog failed: {exc}", flush=True)


def _hydrate_board() -> None:
    try:
        from main import qdb

        doc = qdb.get_doc("rwa:board")
        data = doc.get("data") if isinstance(doc, dict) else None
        if isinstance(data, dict) and data:
            with _BOARD_LOCK:
                _BOARD.update(data)
            print(f"rwa board hydrate n={len(data)}", flush=True)
    except Exception as exc:
        print(f"rwa board hydrate failed: {exc}", flush=True)


def _flush_board(*, force: bool = False) -> None:
    """节流全量 board 覆盖写；force 用于优先热门扫完立刻可见。"""
    global _board_dirty, _last_board_flush_at
    now = time.monotonic()
    with _BOARD_LOCK:
        if not _BOARD:
            return
        if not force and not _board_dirty:
            return
        if not force and (now - _last_board_flush_at) < RWA_BOARD_FLUSH_SEC:
            return
        snapshot = dict(_BOARD)
        _board_dirty = False
        _last_board_flush_at = now
    _put_docs(
        [
            {
                "key": "rwa:board",
                "value": {
                    "updatedAt": int(time.time()),
                    "count": len(snapshot),
                    "data": snapshot,
                },
            }
        ],
        priority="low",
    )


def _board_put(token: dict, dynamic: dict | None) -> None:
    global _board_dirty
    ticker = str(token.get("ticker") or "").upper()
    if not ticker:
        return
    info = (dynamic or {}).get("tokenInfo") or {}
    row = {
        "ticker": ticker,
        "symbol": token.get("symbol"),
        "chainId": str(token.get("chainId") or "56"),
        "contractAddress": str(token.get("contractAddress") or ""),
        "price": info.get("price"),
        "priceChange24h": info.get("priceChange24h"),
        "priceChangePct24h": info.get("priceChangePct24h"),
        "ts": int(time.time()),
    }
    with _BOARD_LOCK:
        _BOARD[ticker] = row
        _board_dirty = True


def _rwa_get(path: str, params: dict | None = None, timeout: int = 12) -> Any:
    """RWA bapi：短超时易 EOF/Read timeout，加重试一次。"""
    last_err: Exception | None = None
    for _ in range(2):
        try:
            r = requests.get(
                f"{RWA}{path}",
                params=params or {},
                timeout=timeout,
                proxies=_rwa_proxies(),
            )
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last_err = exc
            continue
    assert last_err is not None
    raise last_err


def _fetch_dynamic(
    token: dict,
) -> tuple[list[dict], dict | None] | None:
    """拉 dynamic；返回 (docs, optional_quote)。写入由 chunk 批量提交。"""
    ticker = str(token.get("ticker") or "").upper()
    chain = str(token.get("chainId") or "56")
    contract = str(token.get("contractAddress") or "")
    if not ticker or not contract:
        return None
    raw = _rwa_get(_RWA_DYNAMIC, {"chainId": chain, "contractAddress": contract}, timeout=12)
    dynamic = raw.get("data") if isinstance(raw, dict) else None
    docs = [
        {"key": f"rwa:dynamic:{chain}:{contract}", "value": raw},
        {
            "key": f"rwa:quote:{ticker}",
            "value": {
                "ticker": ticker,
                "token": token,
                "chainId": chain,
                "contractAddress": contract,
                "dynamic": dynamic,
            },
        },
    ]
    _board_put(token, dynamic if isinstance(dynamic, dict) else None)
    info = (dynamic or {}).get("tokenInfo") or {}
    price = float(info.get("price") or 0)
    quote: dict | None = None
    if price > 0:
        hot = ticker in _HOT_TICKERS
        if hot or not RWA_ENGINE_QUOTES_HOT_ONLY:
            pct = info.get("priceChangePct24h")
            pre = (
                price / (1 + float(pct) / 100)
                if pct not in (None, "")
                else price
            )
            quote = {
                "exchange": "ONDO",
                "code": ticker,
                "ts_ns": int(time.time() * 1_000_000_000),
                "last": scale(price),
                "name": ticker,
                "price": price,
                "pre_close": pre,
                "volume": float(info.get("volume24h") or 0),
                "amount": float(
                    (dynamic or {}).get("stockInfo", {}).get("marketCap") or 0
                ),
            }
    return docs, quote


def _rwa_kline_worker() -> None:
    global _rwa_kline_cursor, _rwa_kline_interval_i
    if RWA_KLINE_WORKERS <= 0:
        print("rwa kline feed disabled (RWA_KLINE_WORKERS=0)", flush=True)
        return
    intervals = RWA_KLINE_INTERVALS or ["1h"]
    print(
        f"rwa kline feed start workers={RWA_KLINE_WORKERS} chunk={RWA_KLINE_CHUNK} "
        f"intervals={','.join(intervals)}",
        flush=True,
    )
    passes = 0
    while True:
        t0 = time.monotonic()
        try:
            tokens = _ensure_tokens()
            if not tokens:
                time.sleep(2.0)
                continue
            n = len(tokens)
            # 线性扫完一轮再换周期（禁止取模跨尾，否则会提前切 interval）
            if _rwa_kline_cursor >= n:
                _rwa_kline_cursor = 0
                _rwa_kline_interval_i = (_rwa_kline_interval_i + 1) % len(intervals)
                passes += 1
                print(
                    f"rwa kline pass={passes} next_interval="
                    f"{intervals[_rwa_kline_interval_i % len(intervals)]} universe={n}",
                    flush=True,
                )
            interval = intervals[_rwa_kline_interval_i % len(intervals)]
            start = _rwa_kline_cursor
            end = min(start + RWA_KLINE_CHUNK, n)
            chunk = tokens[start:end]
            _rwa_kline_cursor = end
            # 1h 顺带写 trades 喂 qdb 聚合；其它周期只落 doc
            write_trades = interval == "1h"
            ok = 0
            fail = 0
            with ThreadPoolExecutor(max_workers=min(RWA_KLINE_WORKERS, len(chunk))) as pool:
                futs = {
                    pool.submit(
                        _store_rwa_klines, tok, interval, RWA_KLINE_DOC_LIMIT, write_trades
                    ): str(tok.get("ticker") or "").upper()
                    for tok in chunk
                }
                for fut in as_completed(futs):
                    ticker = futs[fut]
                    try:
                        fut.result()
                        ok += 1
                    except Exception as exc:
                        fail += 1
                        print(f"rwa kline {ticker}:{interval} failed: {exc}", flush=True)
            print(
                f"rwa kline {interval} [{start}:{end}]/{n} ok={ok} fail={fail} "
                f"ms={int((time.monotonic() - t0) * 1000)}",
                flush=True,
            )
        except Exception as exc:
            print(f"rwa kline sweep failed: {exc}", flush=True)
            time.sleep(1.0)


def _store_rwa_klines(
    token: dict,
    interval: str,
    limit: int = 200,
    write_trades: bool = False,
) -> None:
    ticker = str(token.get("ticker") or "").upper()
    chain = str(token.get("chainId") or "56")
    contract = str(token.get("contractAddress") or "")
    if not ticker or not contract:
        return
    retain = min(limit, RWA_KLINE_DOC_LIMIT, _RWA_KLINE_LIMIT_MAX)
    raw = _rwa_get(
        _RWA_KLINE,
        {
            "chainId": chain,
            "contractAddress": contract,
            "interval": interval,
            "limit": retain,
        },
        timeout=20,
    )
    # 根数硬顶 + 15 天时间窗后再落 docs（覆盖写）
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, dict):
            infos = data.get("klineInfos")
            if isinstance(infos, list):
                if len(infos) > retain:
                    infos = infos[-retain:]
                data = {**data, "klineInfos": infos}
                raw = {**raw, "data": data}
        raw = trim_rwa_kline_doc(raw)
    _put_docs(
        [{"key": f"rwa:kline:{ticker}:{interval}", "value": raw}],
        priority="low",
    )
    # 引擎 trades 只喂热门，避免全市场 1h 回补占住引擎
    if not write_trades or ticker not in _HOT_TICKERS:
        return
    infos = ((raw.get("data") or {}).get("klineInfos") or []) if isinstance(raw, dict) else []
    if not infos:
        return
    infos = infos[-retain:]
    qsym = f"ONDO:{ticker}"
    have = {int(row["ts"]) for row in get_klines(qsym, "1h")}
    cut = cutoff_ns()
    trades = []
    for row in infos:
        ts = int(row[0]) * 1_000_000
        if ts < cut or ts in have:
            continue
        trades.extend(
            ohlc_trades(
                "ONDO",
                ticker,
                ts,
                {
                    "open": row[1],
                    "high": row[2],
                    "low": row[3],
                    "close": row[4],
                    "volume": row[5] if len(row) > 5 else 0,
                },
            )
        )
    trades.sort(key=lambda item: item["ts_ns"])
    if not trades:
        return
    # 小批 + 低优先，与现货 quotes 错峰
    batch = 64
    pause = float(os.environ.get("RWA_KLINE_WRITE_PAUSE_SEC", "0.2"))
    for i in range(0, len(trades), batch):
        post(
            "/v1/trades",
            {"items": trades[i : i + batch]},
            priority="low",
        )
        if pause > 0 and i + batch < len(trades):
            time.sleep(pause)


def _rwa_tokens() -> list[dict]:
    raw = requests.get(
        f"{RWA}{_RWA_LIST}",
        params={"type": "1"},
        timeout=60,
        proxies=_rwa_proxies(),
    ).json()
    rows = raw.get("data") if isinstance(raw, dict) else []
    best: dict[str, dict] = {}
    for row in rows or []:
        ticker = str(row.get("ticker") or "").upper()
        if not ticker:
            continue
        prev = best.get(ticker)
        if prev is None or str(row.get("chainId")) == "56":
            best[ticker] = row
    _TOKEN_CACHE.clear()
    _TOKEN_CACHE.extend(best.values())
    return list(_TOKEN_CACHE)


def _cached_tokens() -> list[dict]:
    return list(_TOKEN_CACHE)


def _ensure_tokens() -> list[dict]:
    """内存缓存 → qdb `rwa:stocks` → 上游列表。避免每次慢轮询卡在空缓存。"""
    if _TOKEN_CACHE:
        return list(_TOKEN_CACHE)
    try:
        from main import qdb

        doc = qdb.get_doc("rwa:stocks")
        rows = doc.get("data") if isinstance(doc, dict) else None
        if isinstance(rows, list) and rows:
            _TOKEN_CACHE.clear()
            _TOKEN_CACHE.extend(rows)
            return list(_TOKEN_CACHE)
    except Exception as exc:
        print(f"rwa tokens hydrate failed: {exc}", flush=True)
    try:
        tokens = _rwa_tokens()
        _put_docs(
            [
                {
                    "key": "rwa:stocks",
                    "value": {
                        "code": "000000",
                        "success": True,
                        "count": len(tokens),
                        "data": tokens,
                    },
                }
            ],
            priority="low",
        )
        return tokens
    except Exception as exc:
        print(f"rwa tokens refresh failed: {exc}", flush=True)
        return []


def _binance_klines(symbol: str, interval: str, limit: int) -> list[list]:
    data = _binance_get(
        "/api/v3/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
        timeout=20,
    )
    return data if isinstance(data, list) else []


def _put_docs(items: list[dict], *, priority: str = "high") -> None:
    if items:
        post("/v1/docs", {"items": items}, priority=priority)


def start_retention_gc() -> None:
    """定时清理 docs 中超龄 K 线（默认 15 天）。"""

    def get_doc(key: str) -> Any | None:
        from main import qdb

        return qdb.get_doc(key)

    def put_docs_gc(items: list[dict]) -> None:
        # GC 走低优先，不挡现货 quotes
        _put_docs(items, priority="low")

    start_docs_gc(
        get_doc=get_doc,
        put_docs=put_docs_gc,
        binance_symbols=list(BINANCE_SYMBOLS),
        binance_intervals=list(BINANCE_KLINE_INTERVALS),
        rwa_tickers=list(RWA_TICKERS),
        rwa_intervals=list(RWA_KLINE_INTERVALS),
    )


_TOKEN_CACHE: list[dict[str, Any]] = []
