"""币安现货与 Ondo 代币化美股：公开接口只在这里拉取，再写入 qdb。"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests

from main import get_klines, ohlc_trades, post, scale

# api.binance.com 比 data-api.binance.vision 在部分网络更稳（后者易 SSL EOF）
BINANCE = os.environ.get("BINANCE_REST_URL", "https://api.binance.com").rstrip("/")
BINANCE_FALLBACK = os.environ.get(
    "BINANCE_REST_FALLBACK", "https://data-api.binance.vision"
).rstrip("/")
RWA = os.environ.get("BINANCE_RWA_BASE_URL", "https://www.binance.com").rstrip("/")
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
# 全市场并行扫盘；前端只读聚合 doc `rwa:board`
RWA_WORKERS = max(4, int(os.environ.get("RWA_WORKERS", "24")))
RWA_CHUNK = max(8, int(os.environ.get("RWA_CHUNK", "48")))
# K 线：全市场持续写 `rwa:kline:{TICKER}:{interval}`，读路径优先此 doc
RWA_KLINE_WORKERS = max(4, int(os.environ.get("RWA_KLINE_WORKERS", "16")))
RWA_KLINE_CHUNK = max(4, int(os.environ.get("RWA_KLINE_CHUNK", "24")))
RWA_KLINE_INTERVALS = [
    s.strip()
    for s in os.environ.get(
        "RWA_KLINE_INTERVALS", "1h,1d,15m,5m,4h,1m,12h"
    ).split(",")
    if s.strip()
]
_BOARD: dict[str, dict[str, Any]] = {}
_BOARD_LOCK = threading.Lock()
_rwa_cursor = 0
_last_catalog_at = 0.0
_rwa_kline_cursor = 0
_rwa_kline_interval_i = 0


def backfill_markets() -> None:
    for symbol in BINANCE_SYMBOLS:
        try:
            _backfill_binance(symbol)
        except Exception as exc:
            print(f"binance backfill {symbol} failed: {exc}", flush=True)
    tokens = _rwa_tokens()
    _put_docs([{"key": "rwa:stocks", "value": {"code": "000000", "success": True, "count": len(tokens), "data": tokens}}])
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
    qsym = f"BINANCE:{symbol}"
    have_15 = {int(row["ts"]) for row in get_klines(qsym, "15m")}
    have_1d = {int(row["ts"]) for row in get_klines(qsym, "1d")}
    minute = _binance_klines(symbol, "15m", 500)
    daily = _binance_klines(symbol, "1d", 300)
    covered = {int(row[0]) // 86_400_000 for row in minute}
    events: list[tuple[int, list]] = []
    for row in daily:
        ts = int(row[0]) * 1_000_000
        if int(row[0]) // 86_400_000 in covered or ts in have_1d:
            continue
        events.append((ts, row))
    for row in minute:
        ts = int(row[0]) * 1_000_000
        if ts in have_15:
            continue
        events.append((ts, row))
    events.sort(key=lambda item: item[0])
    trades = []
    for ts, row in events:
        trades.extend(
            ohlc_trades(
                "BINANCE",
                symbol,
                ts,
                {"open": row[1], "high": row[2], "low": row[3], "close": row[4], "volume": row[5]},
            )
        )
    if trades:
        post("/v1/trades", {"items": trades})
        print(f"backfill {qsym} trades={len(trades)}", flush=True)


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
    # 先写 quotes 推订阅，再落 ticker docs（列表 REST）
    if quotes:
        post("/v1/quotes", {"items": quotes})
    _put_docs(docs)


def _poll_binance_book(symbol: str) -> None:
    depth = _binance_get("/api/v3/depth", {"symbol": symbol, "limit": 50}, timeout=5)
    trades = _binance_get("/api/v3/trades", {"symbol": symbol, "limit": 50}, timeout=5)
    _put_docs(
        [
            {"key": f"binance:depth:{symbol}", "value": depth},
            {"key": f"binance:trades:{symbol}", "value": trades},
        ]
    )


def _rwa_worker() -> None:
    global _rwa_cursor, _last_catalog_at
    print(f"rwa feed start workers={RWA_WORKERS} chunk={RWA_CHUNK}", flush=True)
    _hydrate_board()
    passes = 0
    while True:
        t0 = time.monotonic()
        try:
            now = time.monotonic()
            if now - _last_catalog_at > 60.0:
                _refresh_rwa_catalog()
                _last_catalog_at = now
            tokens = _ensure_tokens()
            if not tokens:
                time.sleep(2.0)
                continue
            n = len(tokens)
            start = _rwa_cursor
            chunk = [tokens[(start + i) % n] for i in range(min(RWA_CHUNK, n))]
            _rwa_cursor = (start + len(chunk)) % n
            full_pass = len(chunk) >= n or (start + len(chunk)) >= n
            ok = 0
            fail = 0
            with ThreadPoolExecutor(max_workers=min(RWA_WORKERS, len(chunk))) as pool:
                futs = {
                    pool.submit(_store_dynamic, tok): str(tok.get("ticker") or "").upper()
                    for tok in chunk
                }
                for fut in as_completed(futs):
                    ticker = futs[fut]
                    try:
                        fut.result()
                        ok += 1
                    except Exception as exc:
                        fail += 1
                        print(f"rwa dynamic {ticker} failed: {exc}", flush=True)
            _flush_board()
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
        status = requests.get(f"{RWA}{_RWA_STATUS}", timeout=30).json()
        _put_docs([{"key": "rwa:status", "value": status}])
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
            ]
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


def _flush_board() -> None:
    with _BOARD_LOCK:
        snapshot = dict(_BOARD)
    if not snapshot:
        return
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
        ]
    )


def _board_put(token: dict, dynamic: dict | None) -> None:
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


def _rwa_get(path: str, params: dict | None = None, timeout: int = 12) -> Any:
    """RWA bapi：短超时易 EOF/Read timeout，加重试一次。"""
    last_err: Exception | None = None
    for _ in range(2):
        try:
            r = requests.get(f"{RWA}{path}", params=params or {}, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            last_err = exc
            continue
    assert last_err is not None
    raise last_err


def _store_dynamic(token: dict) -> None:
    ticker = str(token.get("ticker") or "").upper()
    chain = str(token.get("chainId") or "56")
    contract = str(token.get("contractAddress") or "")
    if not ticker or not contract:
        return
    raw = _rwa_get(_RWA_DYNAMIC, {"chainId": chain, "contractAddress": contract}, timeout=12)
    dynamic = raw.get("data") if isinstance(raw, dict) else None
    _put_docs(
        [
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
    )
    _board_put(token, dynamic if isinstance(dynamic, dict) else None)
    info = (dynamic or {}).get("tokenInfo") or {}
    price = float(info.get("price") or 0)
    if price <= 0:
        return
    post(
        "/v1/quotes",
        {
            "items": [
                {
                    "exchange": "ONDO",
                    "code": ticker,
                    "ts_ns": int(time.time() * 1_000_000_000),
                    "last": scale(price),
                    "name": ticker,
                    "price": price,
                    "pre_close": price / (1 + float(info.get("priceChangePct24h") or 0) / 100) if info.get("priceChangePct24h") else price,
                    "volume": float(info.get("volume24h") or 0),
                    "amount": float((dynamic or {}).get("stockInfo", {}).get("marketCap") or 0),
                }
            ]
        },
    )


def _rwa_kline_worker() -> None:
    global _rwa_kline_cursor, _rwa_kline_interval_i
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
                    pool.submit(_store_rwa_klines, tok, interval, 200, write_trades): str(
                        tok.get("ticker") or ""
                    ).upper()
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
    raw = _rwa_get(
        _RWA_KLINE,
        {
            "chainId": chain,
            "contractAddress": contract,
            "interval": interval,
            "limit": limit,
        },
        timeout=20,
    )
    _put_docs([{"key": f"rwa:kline:{ticker}:{interval}", "value": raw}])
    if not write_trades:
        return
    infos = ((raw.get("data") or {}).get("klineInfos") or []) if isinstance(raw, dict) else []
    if not infos:
        return
    qsym = f"ONDO:{ticker}"
    have = {int(row["ts"]) for row in get_klines(qsym, "1h")}
    trades = []
    for row in infos:
        ts = int(row[0]) * 1_000_000
        if ts in have:
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
    if trades:
        post("/v1/trades", {"items": trades})


def _rwa_tokens() -> list[dict]:
    raw = requests.get(f"{RWA}{_RWA_LIST}", params={"type": "1"}, timeout=60).json()
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
            ]
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


def _put_docs(items: list[dict]) -> None:
    if items:
        post("/v1/docs", {"items": items})


_TOKEN_CACHE: list[dict[str, Any]] = []
