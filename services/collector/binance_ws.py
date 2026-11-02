"""币安公开 WebSocket → qdb。只在 collector 回源；读路径仍订 qdb。

全市场优化（运行态证据）：
- 全量 depth@100ms ×1300+ 对会打满 write_gate docs、触发分片断线。
- 热门：bookTicker+trade+depth20@100ms+ticker（实时盘口）
- 冷端（含 USDT）：仅 bookTicker+ticker；盘口/成交由 collector REST 轮转慢补
  （全市场 depth WS 会打满 write_gate，已用运行态数据证实）
"""

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
QUOTE_FLUSH_MS = float(os.environ.get("BINANCE_WS_QUOTE_FLUSH_MS", "50"))
DOC_FLUSH_MS = float(os.environ.get("BINANCE_WS_DOC_FLUSH_MS", "400"))
STALE_SEC = float(os.environ.get("BINANCE_WS_STALE_SEC", "20"))
WS_PING_INTERVAL = max(20, int(os.environ.get("BINANCE_WS_PING_INTERVAL", "45")))
WS_PING_TIMEOUT = max(10, int(os.environ.get("BINANCE_WS_PING_TIMEOUT", "30")))
# combined URL 长度约束：热分片可更小；冷端流更少可略大
WS_SHARD_SIZE = max(10, int(os.environ.get("BINANCE_WS_SHARD_SIZE", "40")))
WS_SHARD_STAGGER_SEC = float(os.environ.get("BINANCE_WS_SHARD_STAGGER_SEC", "0.25"))


def _env_flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


WRITE_QDB_TRADES = _env_flag("BINANCE_WS_WRITE_TRADES", "0")
WRITE_QDB_QUOTES = _env_flag("BINANCE_WS_WRITE_QUOTES", "1")


def _http_proxy_kwargs() -> dict[str, Any]:
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


def _ws_root(base: str) -> str:
    root = base.rstrip("/")
    if root.endswith("/ws"):
        root = root[: -len("/ws")]
    return root


# hot | cold
Tier = str


def _stream_names(symbols: list[str], tier: Tier) -> list[str]:
    parts: list[str] = []
    for sym in symbols:
        s = sym.lower()
        if tier == "hot":
            parts.extend(
                [
                    f"{s}@bookTicker",
                    f"{s}@trade",
                    f"{s}@depth20@100ms",
                    f"{s}@ticker",
                ]
            )
        else:
            parts.extend([f"{s}@bookTicker", f"{s}@ticker"])
    return parts


class BinanceWsFeed:
    """单分片 combined stream → quotes/docs。"""

    def __init__(
        self,
        symbols: list[str],
        *,
        shard_id: int,
        tier: Tier,
        post: PostFn,
        scale: ScaleFn,
        put_docs: PutDocsFn,
        put_docs_low: PutDocsFn | None = None,
    ) -> None:
        self.symbols = [s.upper() for s in symbols if s.strip()]
        self.shard_id = shard_id
        self.tier = tier
        self._post = post
        self._scale = scale
        self._put_docs = put_docs
        self._put_docs_low = put_docs_low or put_docs
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
                "qdb_trades": [],
            }
            for s in self.symbols
        }
        self._last_msg = 0.0
        self._started = False
        self._stop = threading.Event()
        self._prefer_direct = False
        self._last_proxy_err = False

    def start(self, *, delay_sec: float = 0.0) -> None:
        if self._started or not self.symbols:
            return
        self._started = True

        def _boot() -> None:
            if delay_sec > 0:
                time.sleep(delay_sec)
            if self._stop.is_set():
                return
            threading.Thread(
                target=self._run_forever,
                name=f"binance-ws-{self.shard_id}",
                daemon=True,
            ).start()
            threading.Thread(
                target=self._flush_loop,
                name=f"binance-ws-flush-{self.shard_id}",
                daemon=True,
            ).start()
            print(
                f"binance ws shard={self.shard_id} tier={self.tier} "
                f"symbols={len(self.symbols)} streams={len(_stream_names(self.symbols, self.tier))}",
                flush=True,
            )

        threading.Thread(
            target=_boot, name=f"binance-ws-boot-{self.shard_id}", daemon=True
        ).start()

    def stop(self) -> None:
        self._stop.set()

    def healthy(self) -> bool:
        if not self._started:
            return False
        return self._last_msg > 0 and (time.monotonic() - self._last_msg) < STALE_SEC

    def _stream_url(self, base: str) -> str:
        root = _ws_root(base)
        return f"{root}/stream?streams={'/'.join(_stream_names(self.symbols, self.tier))}"

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
        healthy_reset_sec = max(15.0, STALE_SEC * 2)
        while not self._stop.is_set():
            base = bases[base_i % len(bases)]
            url = self._stream_url(base)
            opened_at = time.monotonic()
            msgs_before = self._last_msg
            try:
                mode = "direct" if self._prefer_direct else "proxy-or-direct"
                print(
                    f"binance ws shard={self.shard_id} connecting {base} "
                    f"tier={self.tier} ({mode}) …",
                    flush=True,
                )
                app = websocket.WebSocketApp(
                    url,
                    on_message=self._on_message,
                    on_error=self._on_error,
                    on_close=self._on_close,
                    on_open=lambda _ws: print(
                        f"binance ws shard={self.shard_id} open {base}",
                        flush=True,
                    ),
                )
                app.run_forever(
                    ping_interval=WS_PING_INTERVAL,
                    ping_timeout=WS_PING_TIMEOUT,
                    **self._proxy_kwargs(),
                )
            except Exception as exc:
                print(f"binance ws shard={self.shard_id} {base} failed: {exc}", flush=True)
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
                    self._prefer_direct = False
                self._last_proxy_err = False
            else:
                base_i += 1
                if self._last_proxy_err:
                    self._prefer_direct = True
            print(
                f"binance ws shard={self.shard_id} reconnect in {backoff:.0f}s",
                flush=True,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)

    def _on_error(self, _ws: Any, err: Any) -> None:
        text = str(err)
        print(f"binance ws shard={self.shard_id} error: {err}", flush=True)
        low = text.lower()
        if (
            "502" in text
            or "CONNECT" in text.upper()
            or "ssl" in low
            or "wrong version" in low
            or "record layer" in low
        ):
            self._prefer_direct = True
            self._last_proxy_err = True

    def _on_close(self, _ws: Any, status: Any, msg: Any) -> None:
        print(
            f"binance ws shard={self.shard_id} closed status={status} msg={msg}",
            flush=True,
        )

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
        if stream.endswith("@bookTicker") or (
            "b" in data and "a" in data and "s" in data and "e" not in data
        ):
            self._on_book_ticker(data)
        elif data.get("e") == "trade":
            self._on_trade(data)
        elif data.get("e") == "24hrTicker":
            self._on_ticker(data)
        elif "bids" in data and "asks" in data:
            sym = self._symbol_from_stream(stream) or str(data.get("s") or "").upper()
            if sym:
                self._on_depth(sym, data)

    def _symbol_from_stream(self, stream: str) -> str:
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
                    "quoteQty": f"{price * qty:.8f}".rstrip("0").rstrip(".")
                    if price and qty
                    else "0",
                    "time": ts_ms,
                    "isBuyerMaker": is_buyer_maker,
                    "isBestMatch": True,
                }
            )
            st["trades_dirty"] = True
            if WRITE_QDB_TRADES and price > 0 and ts_ms > 0:
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
        # 冷端 ticker/depth docs 降频，避免 18 分片同时打满 write_gate
        base_doc = max(DOC_FLUSH_MS, 50)
        if self.tier != "hot":
            base_doc = max(base_doc, float(os.environ.get("BINANCE_WS_COLD_DOC_FLUSH_MS", "2000")))
        doc_every = base_doc / 1000.0
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
        if WRITE_QDB_QUOTES and items:
            batch = 256
            for i in range(0, len(items), batch):
                try:
                    self._post("/v1/quotes", {"items": items[i : i + batch]})
                except Exception as exc:
                    print(
                        f"binance ws shard={self.shard_id} quote flush failed: {exc}",
                        flush=True,
                    )
                    break
        if trade_items and WRITE_QDB_TRADES:
            if len(trade_items) > 256:
                trade_items = trade_items[-256:]
            try:
                self._post("/v1/trades", {"items": trade_items})
            except Exception as exc:
                print(
                    f"binance ws shard={self.shard_id} trade flush failed: {exc}",
                    flush=True,
                )

    def _flush_docs(self) -> None:
        hi_docs: list[dict] = []
        lo_docs: list[dict] = []
        with self._lock:
            for symbol, st in self._state.items():
                if st["ticker_dirty"] and st["ticker_doc"] is not None:
                    st["ticker_dirty"] = False
                    hi_docs.append(
                        {"key": f"binance:ticker:{symbol}", "value": st["ticker_doc"]}
                    )
                if st["depth_dirty"] and st["depth"] is not None:
                    st["depth_dirty"] = False
                    lo_docs.append({"key": f"binance:depth:{symbol}", "value": st["depth"]})
                if st["trades_dirty"] and st["trades"]:
                    st["trades_dirty"] = False
                    lo_docs.append(
                        {
                            "key": f"binance:trades:{symbol}",
                            "value": list(st["trades"]),
                        }
                    )
        for docs, put in ((hi_docs, self._put_docs), (lo_docs, self._put_docs_low)):
            if not docs:
                continue
            batch = 64
            for i in range(0, len(docs), batch):
                try:
                    put(docs[i : i + batch])
                except Exception as exc:
                    print(
                        f"binance ws shard={self.shard_id} doc flush failed: {exc}",
                        flush=True,
                    )
                    break


_HUB_FEEDS: list[BinanceWsFeed] = []
_HUB_LOCK = threading.Lock()
_HOT_SET: set[str] = set()


def classify_symbol(symbol: str, hot: set[str]) -> Tier:
    return "hot" if symbol.upper() in hot else "cold"


def start_feed(
    symbols: list[str],
    *,
    post: PostFn,
    scale: ScaleFn,
    put_docs: PutDocsFn,
    put_docs_low: PutDocsFn | None = None,
    hot_symbols: list[str] | None = None,
) -> BinanceWsFeed | None:
    """按热/冷分层 + 分片启动；错峰连接。"""
    global _HUB_FEEDS, _HOT_SET
    syms = [s.upper() for s in symbols if s.strip()]
    if not syms:
        return None
    hot = {s.upper() for s in (hot_symbols or []) if s.strip()}
    _HOT_SET = set(hot)

    buckets: dict[Tier, list[str]] = {"hot": [], "cold": []}
    for s in syms:
        buckets[classify_symbol(s, hot)].append(s)

    with _HUB_LOCK:
        for old in _HUB_FEEDS:
            old.stop()
        _HUB_FEEDS = []
        feeds: list[BinanceWsFeed] = []
        shard_i = 0
        for tier, group in buckets.items():
            if not group:
                continue
            # 冷端每对仅 2 流，分片可略大以减少连接数
            size = WS_SHARD_SIZE if tier == "hot" else max(WS_SHARD_SIZE, 80)
            for i in range(0, len(group), size):
                chunk = group[i : i + size]
                feed = BinanceWsFeed(
                    chunk,
                    shard_id=shard_i,
                    tier=tier,
                    post=post,
                    scale=scale,
                    put_docs=put_docs,
                    put_docs_low=put_docs_low,
                )
                feed.start(delay_sec=shard_i * WS_SHARD_STAGGER_SEC)
                feeds.append(feed)
                shard_i += 1
        _HUB_FEEDS = feeds
        print(
            f"binance ws hub symbols={len(syms)} shards={len(feeds)} "
            f"hot={len(buckets['hot'])} cold={len(buckets['cold'])} "
            f"shard_size={WS_SHARD_SIZE} stagger_s={WS_SHARD_STAGGER_SEC}",
            flush=True,
        )
        return feeds[0] if feeds else None


def feed_health_stats() -> dict[str, int]:
    """分片健康统计，供 watchdog / 指标。"""
    with _HUB_LOCK:
        feeds = list(_HUB_FEEDS)
    hot_ok = hot_total = cold_ok = cold_total = 0
    for f in feeds:
        if f.tier == "hot":
            hot_total += 1
            if f.healthy():
                hot_ok += 1
        else:
            cold_total += 1
            if f.healthy():
                cold_ok += 1
    return {
        "hot_ok": hot_ok,
        "hot_total": hot_total,
        "cold_ok": cold_ok,
        "cold_total": cold_total,
        "shards": len(feeds),
    }


def feed_healthy() -> bool:
    st = feed_health_stats()
    if st["shards"] <= 0:
        return False
    # 热门全活；冷端至少一半（错峰启动期）
    hot_ok = st["hot_total"] == 0 or st["hot_ok"] >= st["hot_total"]
    cold_ok = st["cold_total"] == 0 or st["cold_ok"] >= max(1, st["cold_total"] // 2)
    return bool(hot_ok and cold_ok)


def hot_set() -> set[str]:
    return set(_HOT_SET)
