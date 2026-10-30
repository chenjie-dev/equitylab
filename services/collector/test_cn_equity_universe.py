"""Unit tests for A-share universe catalog + quote rotator."""

from __future__ import annotations

from cn_equity_universe import (
    QuoteRotator,
    SINA_HQ_BATCH_MAX,
    build_codes_doc,
    merge_seed_rows,
)


def test_merge_seed_adds_etf_and_keeps_hs_a():
    universe = [
        {"code": "600519", "name": "贵州茅台", "exchange": "SSE", "sina": "sh600519"},
        {"code": "000001", "name": "平安银行", "exchange": "SZSE", "sina": "sz000001"},
        {"code": "830879", "name": "基康仪器", "exchange": "BSE", "sina": "bj830879"},
    ]
    rows = merge_seed_rows(universe, ["600519", "510300", "830879"])
    codes = [r["code"] for r in rows]
    assert codes[:3] == ["600519", "510300", "830879"]
    by = {r["code"]: r for r in rows}
    assert by["510300"]["exchange"] == "SSE"
    assert by["600519"]["name"] == "贵州茅台"


def test_quote_rotator_prepends_seed_and_caps_sina_batch():
    seed = [f"{i:06d}" for i in range(1, 23)]  # 22
    rotate = [f"{i:06d}" for i in range(100000, 100200)]
    rot = QuoteRotator(seed + rotate, seed=seed, batch=100, prepend_seed=True)
    rot.seed_prepend_n = 12  # 显式：默认热门 12，旋转批更大
    batch = rot.next_batch()
    assert len(batch) <= SINA_HQ_BATCH_MAX
    assert len(batch) == 100  # 12 hot seed + 88 rotate（吃满新浪硬顶）
    assert batch[0] == "000001"
    assert set(seed[:12]).issubset(set(batch))
    assert seed[12] not in batch  # 超出 prepend 的 seed 走旋转队列
    batch2 = rot.next_batch()
    assert batch2[0] == "000001"
    assert batch != batch2


def test_quote_rotator_parallel_seed_and_full_rotate():
    seed = [f"{i:06d}" for i in range(1, 23)]
    rotate = [f"{i:06d}" for i in range(100000, 100200)]
    rot = QuoteRotator(seed + rotate, seed=seed, batch=100, prepend_seed=True)
    rot.seed_prepend_n = 12
    hot = rot.hot_seed()
    chunk = rot.next_rotate_batch()
    assert hot == seed[:12]
    assert len(chunk) == 100
    assert not set(hot).intersection(chunk)
    chunk2 = rot.next_rotate_batch()
    assert chunk != chunk2


def test_rotate_lanes_advances_without_overlap():
    from cn_equity_universe import rotate_lanes

    assert 1 <= rotate_lanes() <= 4
    seed = [f"{i:06d}" for i in range(1, 5)]
    rotate = [f"{i:06d}" for i in range(100000, 100300)]
    rot = QuoteRotator(seed + rotate, seed=seed, batch=100, prepend_seed=True)
    rot.seed_prepend_n = 2
    a = rot.next_rotate_batch()
    b = rot.next_rotate_batch()
    assert len(a) == 100 and len(b) == 100
    assert not set(a).intersection(b)


def test_build_codes_doc_shape():
    rows = merge_seed_rows([], ["600519", "000001"])
    doc = build_codes_doc(
        rows, mode="seed", kline_codes=["600519"], source="seed"
    )
    assert doc["count"] == 2
    assert doc["universe"] == "seed"
    assert doc["kline_codes"] == ["600519"]
    assert {c["code"] for c in doc["codes"]} == {"600519", "000001"}
