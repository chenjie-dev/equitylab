"""单标的动量时序 IC：过去 lookback 收益 vs 前瞻 horizon 收益的 Spearman。

非截面、非 alphalens。标签用未来收益、因子用历史收益；调用方须在 assumptions 标明。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class MomentumIcResult:
    ic: float
    icir: float | None
    n_obs: int
    bars_used: int
    lookback: int
    horizon: int
    rolling_window: int
    rolling_ics: int


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        raise ValueError("need at least 2 points for correlation")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = 0.0
    dx2 = 0.0
    dy2 = 0.0
    if len(xs) != len(ys):
        raise ValueError("xs/ys length mismatch")
    for x, y in zip(xs, ys):
        dx = x - mx
        dy = y - my
        num += dx * dy
        dx2 += dx * dx
        dy2 += dy * dy
    den = math.sqrt(dx2 * dy2)
    if den < 1e-18:
        return 0.0
    return num / den


def _rank(values: Sequence[float]) -> list[float]:
    """平均秩（1-based）；并列取均值。"""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        # ranks i..j → average of (i+1)..(j+1)
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) != len(ys):
        raise ValueError("xs/ys length mismatch")
    if len(xs) < 3:
        raise ValueError("need at least 3 paired observations for Spearman IC")
    return _pearson(_rank(xs), _rank(ys))


def build_momentum_pairs(
    closes: Sequence[float],
    *,
    lookback: int,
    horizon: int,
) -> tuple[list[float], list[float]]:
    if lookback < 1 or horizon < 1:
        raise ValueError("lookback/horizon must be >= 1")
    n = len(closes)
    factors: list[float] = []
    labels: list[float] = []
    # t 从 lookback 到 n-1-horizon
    for t in range(lookback, n - horizon):
        c0 = closes[t - lookback]
        c1 = closes[t]
        c2 = closes[t + horizon]
        if c0 <= 0 or c1 <= 0 or c2 <= 0:
            continue
        factors.append(c1 / c0 - 1.0)
        labels.append(c2 / c1 - 1.0)
    return factors, labels


def compute_momentum_ic(
    closes: Sequence[float],
    *,
    lookback: int = 20,
    horizon: int = 5,
    min_obs: int = 30,
    rolling_window: int = 60,
) -> MomentumIcResult:
    """全样本 Spearman IC；ICIR = 滚动窗 Spearman 的 mean/std。"""
    factors, labels = build_momentum_pairs(
        closes, lookback=lookback, horizon=horizon
    )
    n_obs = len(factors)
    if n_obs < min_obs:
        raise ValueError(
            f"insufficient observations: n_obs={n_obs} < min_obs={min_obs} "
            f"(need more bars; lookback={lookback} horizon={horizon})"
        )
    ic = spearman(factors, labels)

    icir: float | None = None
    rolling_ics = 0
    if n_obs >= rolling_window and rolling_window >= 10:
        series: list[float] = []
        for end in range(rolling_window, n_obs + 1):
            start = end - rolling_window
            try:
                series.append(spearman(factors[start:end], labels[start:end]))
            except ValueError:
                continue
        rolling_ics = len(series)
        if rolling_ics >= 3:
            mean_ic = sum(series) / rolling_ics
            var = sum((x - mean_ic) ** 2 for x in series) / (rolling_ics - 1)
            std = math.sqrt(var)
            icir = mean_ic / std if std > 1e-12 else None

    return MomentumIcResult(
        ic=round(ic, 6),
        icir=round(icir, 6) if icir is not None else None,
        n_obs=n_obs,
        bars_used=len(closes),
        lookback=lookback,
        horizon=horizon,
        rolling_window=rolling_window,
        rolling_ics=rolling_ics,
    )
