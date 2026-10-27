"""动量时序 IC：合成序列，不依赖 PG。"""

from __future__ import annotations

import math

import pytest

from app.factors.momentum_ic import (
    compute_momentum_ic,
    spearman,
    build_momentum_pairs,
)


def test_spearman_perfect_positive():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert abs(spearman(xs, ys) - 1.0) < 1e-9


def test_spearman_perfect_negative():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [50.0, 40.0, 30.0, 20.0, 10.0]
    assert abs(spearman(xs, ys) + 1.0) < 1e-9


def test_momentum_pairs_alignment():
    # 单调上涨：动量与前瞻收益同向
    closes = [float(100 + i) for i in range(40)]
    f, lab = build_momentum_pairs(closes, lookback=5, horizon=2)
    assert len(f) == len(lab) == 40 - 5 - 2
    assert all(x > 0 for x in f)
    assert all(y > 0 for y in lab)


def test_compute_momentum_ic_positive_trend():
    closes = [float(100 + i) for i in range(120)]
    r = compute_momentum_ic(
        closes, lookback=10, horizon=5, min_obs=30, rolling_window=40
    )
    assert r.n_obs >= 30
    assert r.ic > 0.5
    assert r.bars_used == 120


def test_compute_momentum_ic_insufficient():
    closes = [100.0 + i for i in range(20)]
    with pytest.raises(ValueError, match="insufficient"):
        compute_momentum_ic(closes, lookback=10, horizon=5, min_obs=30)
