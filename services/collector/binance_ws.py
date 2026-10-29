"""币安公开 WebSocket → qdb。只在 collector 回源；读路径仍订 qdb。"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Any, Callable

PostFn = Callable[[str, dict], None]
ScaleFn = Callable[[Any], int]
PutDocsFn = Callable[[list[dict]], None]

BINANCE_WS = os.environ.get("BINANCE_WS_URL", "wss://data-stream.binance.vision").rstrip("/")
BINANCE_WS_FALLBACK = os.environ.get(
    "BINANCE_WS_FALLBACK", "wss://stream.binance.com:9443"
).rstrip("/")
# 报价合并间隔：对齐 qdb live_rows ~50ms，避免每笔 bookTicker 打爆 HTTP
QUOTE_FLUSH_MS = float(os.environ.get("BINANCE_WS_QUOTE_FLUSH_MS", "50"))
DOC_FLUSH_MS = float(os.environ.get("BINANCE_WS_DOC_FLUSH_MS", "200"))
STALE_SEC = float(os.environ.get("BINANCE_WS_STALE_SEC", "8"))


def _env_flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


# 1=写入 /v1/trades|/v1/quotes；0=只写 docs（避免引擎锁饿死 /v1/klines）
WRITE_QDB_TRADES = _env_flag("BINANCE_WS_WRITE_TRADES", "1")
WRITE_QDB_QUOTES = _env_flag("BINANCE_WS_WRITE_QUOTES", "1")


def _http_proxy_kwargs() -> dict[str, Any]:
    """websocket-client 不读环境代理；优先 COLLECTOR_HTTPS_PROXY（宿主机出网旁路）。"""
    raw = (
        os.environ.get("COLLECTOR_HTTPS_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
        or ""
    ).strip()
    if not raw:
        return {}
    # http://host:port 或 host:port
    s = raw.split("://", 1)[-1]
    if "@" in s:
        s = s.rsplit("@", 1)[-1]
    host, _, port_s = s.partition(":")
    port_s = port_s.split("/", 1)[0]
    if not host or not port_s.isdigit():
        return {}
    return {
        "http_proxy_host": host,
        "http_proxy_port": int(port_s),
        "proxy_type": "http",
    }


class BinanceWsFeed:
    """combined stream: bookTicker + trade + depth20@100ms + ticker → quotes/docs。"""

    def __init__(
        self,
        symbols: list[str],
        *,
        post: PostFn,
        scale: ScaleFn,
        put_docs: PutDocsFn,
    ) -> None:
        self.symbols = [s.upper() for s in symbols if s.strip()]
        self._post = post
        self._scale = scale
        self._put_docs = put_docs
        self._lock = threading.Lock()
        self._state: dict[str, dict[str, Any]] = {
            s: {
                "last": 0.0,
                "bid": 0.0,
                "ask": 0.0,
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "pre_close": 0.0,
                "volume": 0.0,
                "amount": 0.0,
                "quote_dirty": False,
                "depth": None,
                "depth_dirty": False,
                "ticker_doc": None,
                "ticker_dirty": False,
                "trades": deque(maxlen=50),
                "trades_dirty": False,
                # 待写入 /v1/trades，驱动 qdb klines（docs 里的 trades 不够）
                "qdb_trades": [],
            }
            for s in self.symbols
        }
        self._last_msg = 0.0
        self._started = False
        self._stop = threading.Event()
        # CONNECT 代理 502 后改直连；稳定收包后再允许代理
        self._prefer_direct = False
        self._last_proxy_err = False

    def start(self) -> None:
        if self._started or not self.symbols:
            return
        self._started = True
        threading.Thread(target=self._run_forever, name="binance-ws", daemon=True).start()
        threading.Thread(target=self._flush_loop, name="binance-ws-flush", daemon=True).start()
        print(
            f"binance ws feed symbols={len(self.symbols)} "
            f"quote_flush_ms={int(QUOTE_FLUSH_MS)} doc_flush_ms={int(DOC_FLUSH_MS)}",
            flush=True,
        )

    def healthy(self) -> bool:
        if not self._started:
            return False
        return self._last_msg > 0 and (time.monotonic() - self._last_msg) < STALE_SEC

    def _stream_url(self, base: str) -> str:
        parts: list[str] = []
        for sym in self.symbols:
            s = sym.lower()
            parts.extend(
                [
                    f"{s}@bookTicker",
                    f"{s}@trade",
                    f"{s}@depth20@100ms",
                    f"{s}@ticker",
                ]
            )
        # combined: /stream?streams=a/b/c
        root = base.rstrip("/")
        if root.endswith("/ws"):
            root = root[: -len("/ws")]
        return f"{root}/stream?streams={'/'.join(parts)}"

    def _proxy_kwargs(self) -> dict[str, Any]:
        if self._prefer_direct:
            return {}
        return _http_proxy_kwargs()

    def _run_forever(self) -> None:
        try:
            import websocket
        except ImportError:
            print("binance ws: websocket-client missing; REST fallback only", flush=True)
            return
        bases = [BINANCE_WS]
        if BINANCE_WS_FALLBACK and BINANCE_WS_FALLBACK != BINANCE_WS:
            bases.append(BINANCE_WS_FALLBACK)
        backoff = 1.0
        base_i = 0
        # 短连接不把 backoff 清零，避免代理抖动时 1s 狂重连
        healthy_reset_sec = max(15.0, STALE_SEC * 2)
        while not self._stop.is_set():
            base = bases[base_i % len(bases)]
            url = self._stream_url(base)
            opened_at = time.monotonic()
            msgs_before = self._last_msg
            try:
                mode = "direct" if self._prefer_direct else "proxy-or-direct"
                print(f"binance ws connecting {base} ({mode}) …", flush=True)
                app = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=lambda _ws: print(f"binance ws open {base}", flush=True),
                )
                # ping 由库处理；Binance 约 3min 发 ping
                # Docker Desktop 出网 TLS 异常时走宿主机 CONNECT 代理（见 HTTPS_PROXY）
                app.run_forever(
                    ping_interval=60,
                    ping_timeout=20,
                    **self._proxy_kwargs(),
                )
            except Exception as exc:
                print(f"binance ws {base} failed: {exc}", flush=True)
                if "502" in str(exc) or "CONNECT" in str(exc).upper():
                    self._prefer_direct = True
                    self._last_proxy_err = True
            if self._stop.is_set():
                return
            lived = time.monotonic() - opened_at
            got_msgs = self._last_msg > msgs_before
            if got_msgs and lived >= healthy_reset_sec:
                backoff = 1.0
                if self._prefer_direct and not self._last_proxy_err:
                    # 直连已稳定；下次可再试代理（环境恢复）
                    self._prefer_direct = False
                self._last_proxy_err = False
            else:
                # 短命连接：轮换 endpoint，拉长退避
                base_i += 1
                if self._last_proxy_err:
                    self._prefer_direct = True
            print(f"binance ws reconnect in {backoff:.0f}s", flush=True)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def _on_error(self, _ws: Any, err: Any) -> None:
        text = str(err)
        print(f"binance ws error: {err}", flush=True)
        if "502" in text or "CONNECT" in text.upper():
            self._prefer_direct = True
            self._last_proxy_err = True

    def _on_close(self, _ws: Any, status: Any, msg: Any) -> None:
        print(f"binance ws closed status={status} msg={msg}", flush=True)

    def _on_message(self, _ws: Any, message: str | bytes) -> None:
        self._last_msg = time.monotonic()
        try:
            envelope = json.loads(message)
        except json.JSONDecodeError:
            return
        data = envelope.get("data") if isinstance(envelope, dict) else None
        stream = str(envelope.get("stream") or "") if isinstance(envelope, dict) else ""
        if not isinstance(data, dict):
            return
        if stream.endswith("@bookTicker") or ("b" in data and "a" in data and "s" in data and "e" not in data):
            self._on_book_ticker(data)
        elif data.get("e") == "trade":
            self._on_trade(data)
        elif data.get("e") == "24hrTicker":
            self._on_ticker(data)
        elif "bids" in data and "asks" in data:
            # partial depth：stream 名含 depth20，payload 无 e
            sym = self._symbol_from_stream(stream)
            if sym:
                self._on_depth(sym, data)

    def _symbol_from_stream(self, stream: str) -> str:
        # btcusdt@depth20@100ms → BTCUSDT
        head = stream.split("@", 1)[0]
        return head.upper() if head else ""

    def _on_book_ticker(self, data: dict) -> None:
        symbol = str(data.get("s") or "").upper()
        st = self._state.get(symbol)
        if not st:
            return
        bid = float(data.get("b") or 0)
        ask = float(data.get("a") or 0)
        with self._lock:
            st["bid"] = bid
            st["ask"] = ask
            # 无成交时用中间价驱动 last，避免盘口动而价不动
            if st["last"] <= 0 and bid > 0 and ask > 0:
                st["last"] = (bid + ask) / 2
            st["quote_dirty"] = True

    def _on_trade(self, data: dict) -> None:
        symbol = str(data.get("s") or "").upper()
        st = self._state.get(symbol)
        if not st:
            return
        price = float(data.get("p") or 0)
        qty = float(data.get("q") or 0)
        ts_ms = int(data.get("T") or data.get("E") or 0)
        trade_id = int(data.get("t") or 0)
        is_buyer_maker = bool(data.get("m"))
        with self._lock:
            if price > 0:
                st["last"] = price
            st["quote_dirty"] = True
            st["trades"].appendleft(
                {
                    "id": trade_id,
                    "price": f"{price:.8f}".rstrip("0").rstrip(".") if price else "0",
                    "qty": f"{qty:.8f}".rstrip("0").rstrip(".") if qty else "0",
                    "quoteQty": f"{price * qty:.8f}".rstrip("0").rstrip(".") if price and qty else "0",
                    "time": ts_ms,
                    "isBuyerMaker": is_buyer_maker,
                    "isBestMatch": True,
                }
            )
            st["trades_dirty"] = True
            if WRITE_QDB_TRADES and price > 0 and ts_ms > 0:
                # 币安 qty 常 <1；至少记 1，避免 volume=0 被上游丢掉
                vol_i = max(1, int(round(qty * 1e8)))
                st["qdb_trades"].append(
                    {
                        "exchange": "BINANCE",
                        "code": symbol,
                        "ts_ns": ts_ms * 1_000_000,
                        "price": self._scale(price),
                        "volume": vol_i,
                    }
                )

    def _on_ticker(self, data: dict) -> None:
        symbol = str(data.get("s") or "").upper()
        st = self._state.get(symbol)
        if not st:
            return
        # 映射成 REST 24hr ticker 形状，供前端列表
        doc = {
            "symbol": symbol,
            "priceChange": data.get("p"),
            "priceChangePercent": data.get("P"),
            "weightedAvgPrice": data.get("w"),
            "prevClosePrice": data.get("x"),
            "lastPrice": data.get("c"),
            "lastQty": data.get("Q"),
            "bidPrice": data.get("b"),
            "askPrice": data.get("a"),
            "openPrice": data.get("o"),
            "highPrice": data.get("h"),
            "lowPrice": data.get("l"),
            "volume": data.get("v"),
            "quoteVolume": data.get("q"),
            "openTime": data.get("O"),
            "closeTime": data.get("C"),
            "firstId": data.get("F"),
            "lastId": data.get("L"),
            "count": data.get("n"),
        }
        last = float(data.get("c") or 0)
        with self._lock:
            st["ticker_doc"] = doc
            st["ticker_dirty"] = True
            if last > 0:
                st["last"] = last
            st["open"] = float(data.get("o") or 0)
            st["high"] = float(data.get("h") or 0)
            st["low"] = float(data.get("l") or 0)
            st["pre_close"] = float(data.get("x") or data.get("o") or 0)
            st["volume"] = float(data.get("v") or 0)
            st["amount"] = float(data.get("q") or 0)
            st["quote_dirty"] = True

    def _on_depth(self, symbol: str, data: dict) -> None:
        st = self._state.get(symbol)
        if not st:
            return
        # depth20 流已限档；再裁一次防止异常大包进 docs
        bids = (data.get("bids") or [])[:20]
        asks = (data.get("asks") or [])[:20]
        with self._lock:
            st["depth"] = {
                "lastUpdateId": data.get("lastUpdateId"),
                "bids": bids,
                "asks": asks,
            }
            st["depth_dirty"] = True

    def _flush_loop(self) -> None:
        quote_every = max(QUOTE_FLUSH_MS, 20) / 1000.0
        doc_every = max(DOC_FLUSH_MS, 50) / 1000.0
        next_quote = time.monotonic()
        next_doc = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_quote:
                self._flush_quotes()
                next_quote = now + quote_every
            if now >= next_doc:
                self._flush_docs()
                next_doc = now + doc_every
            time.sleep(0.01)

    def _flush_quotes(self) -> None:
        items: list[dict] = []
        trade_items: list[dict] = []
        now_ns = int(time.time() * 1_000_000_000)
        with self._lock:
            for symbol, st in self._state.items():
                if st["qdb_trades"]:
                    trade_items.extend(st["qdb_trades"])
                    st["qdb_trades"] = []
                if not st["quote_dirty"]:
                    continue
                last = float(st["last"] or 0)
                if last <= 0:
                    continue
                st["quote_dirty"] = False
                items.append(
                    {
                        "exchange": "BINANCE",
                        "code": symbol,
                        "ts_ns": now_ns,
                        "last": self._scale(last),
                        "bid_px": self._scale(st["bid"]) if st["bid"] else 0,
                        "ask_px": self._scale(st["ask"]) if st["ask"] else 0,
                        "name": symbol,
                        "open": st["open"],
                        "high": st["high"],
                        "low": st["low"],
                        "pre_close": st["pre_close"] or last,
                        "price": last,
                        "volume": st["volume"],
                        "amount": st["amount"],
                    }
                )
        # quotes 先入队：snapshots 订阅读跟 /v1/quotes；trades 次之
        if WRITE_QDB_QUOTES and items:
            try:
                self._post("/v1/quotes", {"items": items})
            except Exception as exc:
                print(f"binance ws quote flush failed: {exc}", flush=True)
        if trade_items and WRITE_QDB_TRADES:
            # 限长，避免断线重连后积压打爆 qdb
            if len(trade_items) > 256:
                trade_items = trade_items[-256:]
            try:
                self._post("/v1/trades", {"items": trade_items})
            except Exception as exc:
                print(f"binance ws trade flush failed: {exc}", flush=True)

    def _flush_docs(self) -> None:
        docs: list[dict] = []
        with self._lock:
            for symbol, st in self._state.items():
                if st["depth_dirty"] and st["depth"] is not None:
                    st["depth_dirty"] = False
                    docs.append({"key": f"binance:depth:{symbol}", "value": st["depth"]})
                if st["ticker_dirty"] and st["ticker_doc"] is not None:
                    st["ticker_dirty"] = False
                    docs.append({"key": f"binance:ticker:{symbol}", "value": st["ticker_doc"]})
                if st["trades_dirty"] and st["trades"]:
                    st["trades_dirty"] = False
                    docs.append(
                        {
                            "key": f"binance:trades:{symbol}",
                            "value": list(st["trades"]),
                        }
                    )
        if docs:
            try:
                self._put_docs(docs)
            except Exception as exc:
                print(f"binance ws doc flush failed: {exc}", flush=True)


_FEED: BinanceWsFeed | None = None


def start_feed(
    symbols: list[str],
    *,
    post: PostFn,
    scale: ScaleFn,
    put_docs: PutDocsFn,
) -> BinanceWsFeed:
    global _FEED
    feed = BinanceWsFeed(symbols, post=post, scale=scale, put_docs=put_docs)
    feed.start()
    _FEED = feed
    return feed


def feed_healthy() -> bool:
    return bool(_FEED and _FEED.healthy())
