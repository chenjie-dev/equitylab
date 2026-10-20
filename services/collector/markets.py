"""币安现货与 Ondo 代币化美股：公开接口只在这里拉取，再写入 qdb。"""

from __future__ import annotations

import os
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


def backfill_markets() -> None:
    for symbol in BINANCE_SYMBOLS:
        try:
            _backfill_binance(symbol)
        except Exception as exc:
            print(f"binance backfill {symbol} failed: {exc}", flush=True)
    tokens = _rwa_tokens()
    _put_docs([{"key": "rwa:stocks", "value": {"code": "000000", "success": True, "count": len(tokens), "data": tokens}}])
    for token in tokens:
        ticker = str(token.get("ticker") or "").upper()
        if ticker not in RWA_TICKERS:
            continue
        try:
            _backfill_rwa(token)
        except Exception as exc:
            print(f"rwa backfill {ticker} failed: {exc}", flush=True)


def start_binance_ws() -> None:
    """启动币安 combined stream（报价/盘口/成交 docs）；失败时 REST 兜底。"""
    from binance_ws import start_feed

    start_feed(BINANCE_SYMBOLS, post=post, scale=scale, put_docs=_put_docs)


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
    """慢路径：WS 不健康时 REST 盘口；RWA 始终轮询。"""
    if BINANCE_SYMBOLS and not binance_ws_healthy():
        symbol = BINANCE_SYMBOLS[cycle % len(BINANCE_SYMBOLS)]
        try:
            _poll_binance_book(symbol)
        except Exception as exc:
            print(f"binance book {symbol} failed: {exc}", flush=True)
    try:
        _poll_rwa(cycle)
    except Exception as exc:
        print(f"rwa poll failed: {exc}", flush=True)


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


def _poll_rwa(cycle: int) -> None:
    if cycle % 30 == 0:
        try:
            status = requests.get(f"{RWA}{_RWA_STATUS}", timeout=15).json()
            _put_docs([{"key": "rwa:status", "value": status}])
            tokens = _rwa_tokens()
            _put_docs([{"key": "rwa:stocks", "value": {"code": "000000", "success": True, "count": len(tokens), "data": tokens}}])
        except Exception as exc:
            print(f"rwa catalog failed: {exc}", flush=True)
    tokens = _cached_tokens()
    batch = [t for t in tokens if str(t.get("ticker") or "").upper() in RWA_TICKERS]
    start = (cycle * 4) % max(len(batch), 1)
    for token in batch[start : start + 4]:
        _store_dynamic(token)


def _store_dynamic(token: dict) -> None:
    ticker = str(token.get("ticker") or "").upper()
    chain = str(token.get("chainId") or "56")
    contract = str(token.get("contractAddress") or "")
    if not ticker or not contract:
        return
    raw = requests.get(
        f"{RWA}{_RWA_DYNAMIC}",
        params={"chainId": chain, "contractAddress": contract},
        timeout=10,
    ).json()
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
                    "ts_ns": int(__import__("time").time() * 1_000_000_000),
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


def _backfill_rwa(token: dict) -> None:
    ticker = str(token.get("ticker") or "").upper()
    chain = str(token.get("chainId") or "56")
    contract = str(token.get("contractAddress") or "")
    qsym = f"ONDO:{ticker}"
    have = {int(row["ts"]) for row in get_klines(qsym, "1h")}
    rows = requests.get(
        f"{RWA}{_RWA_KLINE}",
        params={"chainId": chain, "contractAddress": contract, "interval": "1h", "limit": 200},
        timeout=20,
    ).json()
    infos = ((rows.get("data") or {}).get("klineInfos") or []) if isinstance(rows, dict) else []
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
                {"open": row[1], "high": row[2], "low": row[3], "close": row[4], "volume": row[5] if len(row) > 5 else 0},
            )
        )
    trades.sort(key=lambda item: item["ts_ns"])
    if trades:
        post("/v1/trades", {"items": trades})
        print(f"backfill {qsym} trades={len(trades)}", flush=True)
    _store_dynamic(token)


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
