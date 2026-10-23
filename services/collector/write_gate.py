"""
qdb 写入门闸：单写者串行 HTTP，高优先（现货 quotes/trades/docs）插队，
低优先（RWA）合并后再发，避免 24 路 RWA 单条 POST 饿死 Binance snapshots。

docs 按 key 合并（后者覆盖）；quotes/trades 同优先队列内批量拼接。
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any, Callable, Literal

Priority = Literal["high", "low"]
PostFn = Callable[[str, dict[str, Any]], Any]

# 门闸刷盘间隔；对齐 qdb quotes 组提交 ~1ms，略松一点降低 HTTP 次数
FLUSH_MS = max(5.0, float(os.environ.get("QDB_WRITE_FLUSH_MS", "25")))
# 单批上限，避免巨大 JSON
MAX_QUOTE_BATCH = max(16, int(os.environ.get("QDB_WRITE_QUOTE_BATCH", "256")))
MAX_TRADE_BATCH = max(16, int(os.environ.get("QDB_WRITE_TRADE_BATCH", "256")))
MAX_DOC_BATCH = max(8, int(os.environ.get("QDB_WRITE_DOC_BATCH", "64")))


class WriteGate:
    """进程内唯一写出口；`start()` 后由后台线程刷盘。"""

    def __init__(self, post_fn: PostFn) -> None:
        self._post_fn = post_fn
        self._cv = threading.Condition()
        self._hi_quotes: deque[dict[str, Any]] = deque()
        self._hi_trades: deque[dict[str, Any]] = deque()
        self._hi_docs: dict[str, dict[str, Any]] = {}
        self._lo_quotes: deque[dict[str, Any]] = deque()
        self._lo_trades: deque[dict[str, Any]] = deque()
        self._lo_docs: dict[str, dict[str, Any]] = {}
        self._started = False
        self._stop = threading.Event()
        self._stats = {"hi": 0, "lo": 0, "err": 0}

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        threading.Thread(target=self._loop, name="qdb-write-gate", daemon=True).start()
        print(
            f"qdb write gate flush_ms={int(FLUSH_MS)} "
            f"quote_batch={MAX_QUOTE_BATCH} trade_batch={MAX_TRADE_BATCH} "
            f"doc_batch={MAX_DOC_BATCH}",
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
                q = self._hi_quotes if priority == "high" else self._lo_quotes
                q.extend(items)
                self._cv.notify()
            return
        if path.endswith("/trades"):
            with self._cv:
                q = self._hi_trades if priority == "high" else self._lo_trades
                q.extend(items)
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

    def post_sync(self, path: str, body: dict[str, Any]) -> Any:
        """旁路门闸（GC / 罕见路径）；仍串行占锁避免与刷盘打架。"""
        with self._cv:
            # 等队列略空再写，减少与热路径交错
            while (
                self._hi_quotes
                or self._hi_trades
                or self._hi_docs
            ) and not self._stop.is_set():
                self._cv.wait(timeout=0.05)
        return self._post_fn(path, body)

    def _drain(
        self,
        quotes: deque[dict[str, Any]],
        trades: deque[dict[str, Any]],
        docs: dict[str, dict[str, Any]],
        *,
        limit_q: int,
        limit_t: int,
        limit_d: int,
    ) -> tuple[list[dict], list[dict], list[dict]]:
        q_out: list[dict] = []
        t_out: list[dict] = []
        while quotes and len(q_out) < limit_q:
            q_out.append(quotes.popleft())
        while trades and len(t_out) < limit_t:
            t_out.append(trades.popleft())
        d_out: list[dict] = []
        if docs:
            keys = list(docs.keys())[:limit_d]
            for k in keys:
                d_out.append(docs.pop(k))
        return q_out, t_out, d_out

    def _loop(self) -> None:
        interval = FLUSH_MS / 1000.0
        last_stat = time.monotonic()
        fair_i = 0
        while not self._stop.is_set():
            with self._cv:
                if not self._pending():
                    self._cv.wait(timeout=interval)
                # 先抽高优先；高优先空再抽低优先。每隔几轮给低优先一小批，防饿死。
                hq, ht, hd = self._drain(
                    self._hi_quotes,
                    self._hi_trades,
                    self._hi_docs,
                    limit_q=MAX_QUOTE_BATCH,
                    limit_t=MAX_TRADE_BATCH,
                    limit_d=MAX_DOC_BATCH,
                )
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
                    cap_q = MAX_QUOTE_BATCH if not (hq or ht or hd) else max(16, MAX_QUOTE_BATCH // 4)
                    cap_t = MAX_TRADE_BATCH if not (hq or ht or hd) else max(16, MAX_TRADE_BATCH // 4)
                    cap_d = MAX_DOC_BATCH if not (hq or ht or hd) else max(4, MAX_DOC_BATCH // 4)
                    lq, lt, ld = self._drain(
                        self._lo_quotes,
                        self._lo_trades,
                        self._lo_docs,
                        limit_q=cap_q,
                        limit_t=cap_t,
                        limit_d=cap_d,
                    )
            # quotes 先于 trades：snapshots 订阅读跟 quotes
            self._flush_batch("/v1/quotes", hq, high=True)
            self._flush_batch("/v1/trades", ht, high=True)
            self._flush_batch("/v1/docs", hd, high=True)
            self._flush_batch("/v1/quotes", lq, high=False)
            self._flush_batch("/v1/trades", lt, high=False)
            self._flush_batch("/v1/docs", ld, high=False)
            now = time.monotonic()
            if now - last_stat >= 30.0:
                print(
                    f"qdb write gate stats hi={self._stats['hi']} "
                    f"lo={self._stats['lo']} err={self._stats['err']} "
                    f"q_pending={len(self._hi_quotes)+len(self._lo_quotes)} "
                    f"d_pending={len(self._hi_docs)+len(self._lo_docs)}",
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
