"""A 股宇宙：公共逻辑在 equitylab_market.cn_universe；本模块保留报价旋转器。

盘中报价默认关闭（COLLECTOR_SKIP_CN_EQUITY=1）；目录刷新由 history-ingest 负责。
"""

from __future__ import annotations

import os

from equitylab_market.cn_universe import (  # noqa: F401
    CODES_DOC_KEY,
    DEFAULT_SEED,
    SINA_HQ_BATCH_MAX,
    build_codes_doc,
    codes_doc_items,
    fetch_hs_a_count,
    fetch_hs_a_universe,
    kline_backfill_codes,
    merge_seed_rows,
    quote_batch_size,
    resolve_universe,
    seed_codes_from_env,
    sina_symbol,
    universe_mode,
    universe_refresh_sec,
)
from equitylab_market.symbols import cn_equity_exchange  # noqa: F401


def quote_seed_prepend_n() -> int:
    try:
        n = int(os.environ.get("CN_EQUITY_QUOTE_SEED_N", "12"))
    except ValueError:
        n = 12
    return max(0, min(SINA_HQ_BATCH_MAX - 1, n))


def rotate_lanes() -> int:
    try:
        n = int(os.environ.get("CN_EQUITY_ROTATE_LANES", "2"))
    except ValueError:
        n = 2
    return max(1, min(4, n))


class QuoteRotator:
    """全表 round-robin；每 tick 取一批，可选每批前置 seed（保证热门新鲜）。"""

    def __init__(
        self,
        codes: list[str],
        *,
        seed: list[str] | None = None,
        batch: int | None = None,
        prepend_seed: bool = True,
    ) -> None:
        self.codes = list(codes)
        self.seed = list(seed or [])
        self.batch = batch if batch is not None else quote_batch_size()
        self.prepend_seed = prepend_seed
        self.seed_prepend_n = quote_seed_prepend_n()
        self._i = 0
        self._seed_set = set(self.seed)
        self._rotate = [c for c in self.codes if c not in self._seed_set] or list(
            self.codes
        )

    def set_codes(self, codes: list[str], seed: list[str] | None = None) -> None:
        self.codes = list(codes)
        if seed is not None:
            self.seed = list(seed)
            self._seed_set = set(self.seed)
        self._rotate = [c for c in self.codes if c not in self._seed_set] or list(
            self.codes
        )
        if self._i >= len(self._rotate):
            self._i = 0

    def hot_seed(self) -> list[str]:
        if not self.prepend_seed or not self.seed or self.seed_prepend_n <= 0:
            return []
        return list(self.seed[: self.seed_prepend_n])

    def next_rotate_batch(self) -> list[str]:
        if not self.codes:
            return []
        rotate = self._rotate
        if not rotate:
            return list(self.codes)[:SINA_HQ_BATCH_MAX]
        take = min(max(1, self.batch), SINA_HQ_BATCH_MAX, len(rotate))
        chunk: list[str] = []
        for _ in range(take):
            chunk.append(rotate[self._i % len(rotate)])
            self._i = (self._i + 1) % len(rotate)
        return chunk

    def next_batch(self) -> list[str]:
        if not self.codes:
            return []
        hot = self.hot_seed()
        rotate = self._rotate
        if not rotate:
            return list(dict.fromkeys([*hot, *self.codes]))[:SINA_HQ_BATCH_MAX]
        seed_n = len(hot)
        room = max(1, SINA_HQ_BATCH_MAX - seed_n)
        take = min(max(1, self.batch), room, len(rotate))
        chunk: list[str] = []
        for _ in range(take):
            chunk.append(rotate[self._i % len(rotate)])
            self._i = (self._i + 1) % len(rotate)
        if seed_n:
            return list(dict.fromkeys([*hot, *chunk]))
        return chunk
