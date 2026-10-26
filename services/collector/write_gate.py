"""
qdb 写入门闸：单写者串行 HTTP，高优先（现货 quotes/trades/docs）插队，
低优先（RWA）合并后再发，避免 24 路 RWA 单条 POST 饿死 Binance snapshots。

docs 按 key 合并（后者覆盖）；**quotes 按 exchange:code 合并（只保留最新）**，
避免 FIFO 积压把过期报价覆盖快照（A 股盘中「价格倒退 / 落后新浪数元」）。
每轮先刷 quotes 再刷 trades；不再「有 quotes 就整轮跳过 trades」（会饿死 K 线回填）。
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict, deque
from typing import Any, Callable, Literal

Priority = Literal["high", "low"]
PostFn = Callable[[str, dict[str, Any]], Any]

# 门闸刷盘间隔；对齐 qdb quotes 组提交 ~1ms，略松一点降低 HTTP 次数
FLUSH_MS = max(5.0, float(os.environ.get("QDB_WRITE_FLUSH_MS", "25")))
# 单批上限，避免巨大 JSON
MAX_QUOTE_BATCH = max(16, int(os.environ.get("QDB_WRITE_QUOTE_BATCH", "256")))
MAX_TRADE_BATCH = max(16, int(os.environ.get("QDB_WRITE_TRADE_BATCH", "256")))
MAX_DOC_BATCH = max(8, int(os.environ.get("QDB_WRITE_DOC_BATCH", "64")))
# 成交队列软顶：超出则丢弃最旧（保 quotes 时效；回填可重跑）
MAX_TRADE_PENDING = max(1_000, int(os.environ.get("QDB_WRITE_TRADE_PENDING", "20000")))


def _quote_key(item: dict[str, Any]) -> str:
    ex = str(item.get("exchange") or "")
    code = str(item.get("code") or "")
    return f"{ex}:{code}"


class WriteGate:
    """进程内唯一写出口；`start()` 后由后台线程刷盘。"""

    def __init__(self, post_fn: PostFn) -> None:
        self._post_fn = post_fn
        self._cv = threading.Condition()
        # quotes：按标的合并，只留最新（OrderedDict 保插入序，更新时 move_to_end）
        self._hi_quotes: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lo_quotes: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._hi_trades: deque[dict[str, Any]] = deque()
        self._lo_trades: deque[dict[str, Any]] = deque()
        self._hi_docs: dict[str, dict[str, Any]] = {}
        self._lo_docs: dict[str, dict[str, Any]] = {}
        self._started = False
        self._stop = threading.Event()
        self._stats = {"hi": 0, "lo": 0, "err": 0, "trade_drop": 0}

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._loop, name="qdb-write-gate", daemon=True).start()
        print(
            f"qdb write gate flush_ms={int(FLUSH_MS)} "
            f"quote_batch={MAX_QUOTE_BATCH} trade_batch={MAX_TRADE_BATCH} "
            f"doc_batch={MAX_DOC_BATCH} trade_pending_cap={MAX_TRADE_PENDING}",
            flush=True,
        )

    def enqueue(
        self,
        path: str,
        body: dict[str, Any],
        *,
        priority: Priority = "high",
    ) -> None:
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list) or not items:
            return
        if path.endswith("/quotes"):
            with self._cv:
                bucket = self._hi_quotes if priority == "high" else self._lo_quotes
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    key = _quote_key(item)
                    if not key or key == ":":
                        continue
                    if key in bucket:
                        del bucket[key]
                    bucket[key] = item
                self._cv.notify()
            return
        if path.endswith("/trades"):
            with self._cv:
                q = self._hi_trades if priority == "high" else self._lo_trades
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    q.append(item)
                self._trim_trades(q)
                self._cv.notify()
            return
        if path.endswith("/docs"):
            with self._cv:
                bucket = self._hi_docs if priority == "high" else self._lo_docs
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    key = item.get("key")
                    if key is None:
                        continue
                    bucket[str(key)] = item
                self._cv.notify()
            return
        # 未知路径：同步旁路
        self.post_sync(path, body)

    def _trim_trades(self, q: deque[dict[str, Any]]) -> None:
        while len(q) > MAX_TRADE_PENDING:
            q.popleft()
            self._stats["trade_drop"] += 1

    def pending_counts(self) -> dict[str, int]:
        """供 Prometheus：队列积压与 trade_drop 累计。"""
        with self._cv:
            return {
                "quotes": len(self._hi_quotes) + len(self._lo_quotes),
                "trades": len(self._hi_trades) + len(self._lo_trades),
                "docs": len(self._hi_docs) + len(self._lo_docs),
                "trade_drop": int(self._stats.get("trade_drop") or 0),
                "err": int(self._stats.get("err") or 0),
            }

    def post_sync(self, path: str, body: dict[str, Any]) -> Any:
        """旁路门闸（GC / 回填）；短暂让 quotes 先走，超时仍写（币安会持续补 quotes）。"""
        deadline = time.monotonic() + 2.0
        with self._cv:
            while (
                self._hi_quotes
                and time.monotonic() < deadline
                and not self._stop.is_set()
            ):
                self._cv.wait(timeout=0.05)
        return self._post_fn(path, body)

    def _drain_quotes(
        self, quotes: OrderedDict[str, dict[str, Any]], *, limit: int
    ) -> list[dict]:
        out: list[dict] = []
        while quotes and len(out) < limit:
            _k, item = quotes.popitem(last=False)
            out.append(item)
        return out

    def _drain_trades(self, trades: deque[dict[str, Any]], *, limit: int) -> list[dict]:
        out: list[dict] = []
        while trades and len(out) < limit:
            out.append(trades.popleft())
        return out

    def _drain_docs(self, docs: dict[str, dict[str, Any]], *, limit: int) -> list[dict]:
        out: list[dict] = []
        if docs:
            keys = list(docs.keys())[:limit]
            for k in keys:
                out.append(docs.pop(k))
        return out

    def _loop(self) -> None:
        interval = FLUSH_MS / 1000.0
        last_stat = time.monotonic()
        fair_i = 0
        while not self._stop.is_set():
            with self._cv:
                if not self._pending():
                    self._cv.wait(timeout=interval)
                # 先抽高优先 quotes（已按标的合并，队列极短），再抽 trades/docs
                hq = self._drain_quotes(self._hi_quotes, limit=MAX_QUOTE_BATCH)
                ht = self._drain_trades(self._hi_trades, limit=MAX_TRADE_BATCH)
                hd = self._drain_docs(self._hi_docs, limit=MAX_DOC_BATCH)
                lq: list[dict] = []
                lt: list[dict] = []
                ld: list[dict] = []
                lo_n = (
                    len(self._lo_quotes)
                    + len(self._lo_trades)
                    + len(self._lo_docs)
                )
                fair_i += 1
                take_lo = (not hq and not ht and not hd) or fair_i % 4 == 0 or lo_n > 500
                if take_lo and lo_n:
                    cap_q = (
                        MAX_QUOTE_BATCH
                        if not (hq or ht or hd)
                        else max(16, MAX_QUOTE_BATCH // 4)
                    )
                    cap_t = (
                        MAX_TRADE_BATCH
                        if not (hq or ht or hd)
                        else max(16, MAX_TRADE_BATCH // 4)
                    )
                    cap_d = (
                        MAX_DOC_BATCH
                        if not (hq or ht or hd)
                        else max(4, MAX_DOC_BATCH // 4)
                    )
                    lq = self._drain_quotes(self._lo_quotes, limit=cap_q)
                    lt = self._drain_trades(self._lo_trades, limit=cap_t)
                    ld = self._drain_docs(self._lo_docs, limit=cap_d)
            # quotes 先于 trades：snapshots 订阅读跟 quotes
            self._flush_batch("/v1/quotes", hq, high=True)
            self._flush_batch("/v1/trades", ht, high=True)
            self._flush_batch("/v1/docs", hd, high=True)
            self._flush_batch("/v1/quotes", lq, high=False)
            self._flush_batch("/v1/trades", lt, high=False)
            self._flush_batch("/v1/docs", ld, high=False)
            now = time.monotonic()
            if now - last_stat >= 30.0:
                with self._cv:
                    q_n = len(self._hi_quotes) + len(self._lo_quotes)
                    t_n = len(self._hi_trades) + len(self._lo_trades)
                    d_n = len(self._hi_docs) + len(self._lo_docs)
                    drop = self._stats["trade_drop"]
                print(
                    f"qdb write gate stats hi={self._stats['hi']} "
                    f"lo={self._stats['lo']} err={self._stats['err']} "
                    f"q_pending={q_n} t_pending={t_n} d_pending={d_n} "
                    f"trade_drop={drop}",
                    flush=True,
                )
                last_stat = now
            if not self._pending_unlocked():
                time.sleep(min(0.005, interval))

    def _pending(self) -> bool:
        return bool(
            self._hi_quotes
            or self._hi_trades
            or self._hi_docs
            or self._lo_quotes
            or self._lo_trades
            or self._lo_docs
        )

    def _pending_unlocked(self) -> bool:
        with self._cv:
            return self._pending()

    def _flush_batch(
        self, path: str, items: list[dict[str, Any]], *, high: bool
    ) -> None:
        if not items:
            return
        try:
            self._post_fn(path, {"items": items})
            self._stats["hi" if high else "lo"] += len(items)
        except Exception as exc:
            self._stats["err"] += 1
            print(f"qdb write gate {path} failed n={len(items)}: {exc}", flush=True)


_GATE: WriteGate | None = None


def get_gate() -> WriteGate | None:
    return _GATE


def start_gate(post_fn: PostFn) -> WriteGate:
    global _GATE
    gate = WriteGate(post_fn)
    gate.start()
    _GATE = gate
    return gate
